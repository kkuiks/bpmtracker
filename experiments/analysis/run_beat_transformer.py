"""Run pinned official Beat Transformer with its real five-stem frontend.

Requires separately provisioned source, weights, and isolated frontend Python.
All output is an unreviewed comparison proposal, not an accepted musical map.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import soundfile as sf
import torch

from beat_transformer import FPS, UPSTREAM_COMMIT, file_hash, load_model, infer_frames, validate_logits


def run_frontend(python, arguments):
    subprocess.run([str(python), str(Path(__file__).with_name("beat_transformer_frontend.py")), *map(str, arguments)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/models/beat-transformer/fold_4_trf_param.pt"))
    parser.add_argument("--upstream-dir", type=Path, default=Path("data/models/beat-transformer/upstream"))
    parser.add_argument("--frontend-python", type=Path, default=Path("data/cache/beat-transformer/frontend-venv/bin/python"))
    parser.add_argument("--spleeter-model-root", type=Path, default=Path("data/models/beat-transformer/spleeter"))
    parser.add_argument("--features", type=Path, help="reuse a provenance-checked feature cache")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--core-frames", type=int, default=2048)
    parser.add_argument("--context-frames", type=int, default=2048)
    parser.add_argument("--enable-cudnn", action="store_true", help="diagnostic only: this host's cuDNN workspace exceeded 2 GiB")
    parser.add_argument("--verify-chunk-prefix-seconds", type=float, default=0)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    if args.threads <= 0 or args.core_frames <= 0:
        parser.error("threads and core frames must be positive")
    if args.max_seconds is not None and (not np.isfinite(args.max_seconds) or args.max_seconds <= 0):
        parser.error("max-seconds must be finite and positive")
    if not np.isfinite(args.verify_chunk_prefix_seconds) or args.verify_chunk_prefix_seconds < 0:
        parser.error("chunk verification duration must be finite and nonnegative")
    info = sf.info(args.audio)
    if not info.format.startswith("WAV"):
        parser.error("use canonical WAV input")
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA unavailable; obtain permitted GPU access or explicitly use CPU")
    checkpoint_meta = json.loads(args.checkpoint.with_suffix(".json").read_text())
    if checkpoint_meta["upstream_commit"] != UPSTREAM_COMMIT or file_hash(args.checkpoint) != checkpoint_meta["sha256"]:
        parser.error("checkpoint provenance mismatch")
    upstream = json.loads((args.upstream_dir / "provenance.json").read_text())
    if upstream["commit"] != UPSTREAM_COMMIT:
        parser.error("unexpected upstream version")
    for entry in upstream["files"]:
        if file_hash(args.upstream_dir / entry["path"]) != entry["sha256"]:
            parser.error("upstream source was modified: " + entry["path"])
    args.output_dir.mkdir(parents=True)
    started = time.perf_counter()
    features_path = args.features or args.output_dir / "features.npz"
    if args.features is None:
        command = ["prepare", "--audio", args.audio, "--output", features_path,
                   "--model-root", args.spleeter_model_root, "--threads", args.threads]
        if args.max_seconds is not None:
            command += ["--max-seconds", args.max_seconds]
        run_frontend(args.frontend_python, command)
    feature_meta = json.loads(features_path.with_suffix(".json").read_text())
    expected_frames = info.frames if args.max_seconds is None else min(info.frames, round(args.max_seconds*info.samplerate))
    if feature_meta["audio_sha256"] != file_hash(args.audio) or feature_meta["feature_sha256"] != file_hash(features_path):
        raise ValueError("feature cache does not match the audio or feature bytes")
    if feature_meta["analyzed_source_frames"] != expected_frames or feature_meta["source_frame_offset"] != 0 or feature_meta["frame_time_offset_seconds"] != 0:
        raise ValueError("feature cache has different support/origin")
    with np.load(features_path, allow_pickle=False) as values:
        if float(values["fps"]) != FPS:
            raise ValueError("unexpected frontend frame rate")
        features = values["features"]
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    # On this MX450, cuDNN workspace inflated allocated memory beyond physical
    # VRAM. Native float32 convolutions match saved logits within 1.4e-5 and
    # keep the measured peak near 1 GiB; no model weights/architecture change.
    torch.backends.cudnn.enabled = args.enable_cudnn
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    print(f"Loading pinned Beat Transformer fold4 on {device}; features {features.shape}", flush=True)
    model = load_model(args.upstream_dir, args.checkpoint, device)
    ready = time.perf_counter()
    logits, spans = infer_frames(model, features, device, args.core_frames, args.context_frames)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    inferred = time.perf_counter()
    validate_logits(logits[:, 0], logits[:, 1])
    memory = None if device.type != "cuda" else {
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
        "device_total_bytes": torch.cuda.get_device_properties(device).total_memory,
    }
    verification = None
    if args.verify_chunk_prefix_seconds:
        count = min(features.shape[1], round(args.verify_chunk_prefix_seconds*FPS))
        prefix = features[:, :count]
        full, _ = infer_frames(model, prefix, device, core_frames=count, context_frames=args.context_frames)
        chunked, _ = infer_frames(model, prefix, device, core_frames=args.core_frames, context_frames=args.context_frames)
        error = np.abs(full-chunked)
        verification = {"frames": count, "max_absolute_logit_error": float(error.max()),
                        "mean_absolute_logit_error": float(error.mean()), "tolerance": .0001,
                        "passed": bool(np.allclose(full, chunked, rtol=0, atol=.0001))}
        if not verification["passed"]:
            raise ValueError("chunk/full comparison failed: " + str(verification))
    np.savez_compressed(args.output_dir / "logits.npz", beat=logits[:, 0], downbeat=logits[:, 1],
                        fps=np.array(FPS), source_frame_offset=np.array(0), frame_time_offset_seconds=np.array(0.))
    run_frontend(args.frontend_python, ["decode", "--logits", args.output_dir / "logits.npz",
                                      "--output", args.output_dir / "official-decoder.json"])
    prediction = json.loads((args.output_dir / "official-decoder.json").read_text())
    duration = expected_frames / info.samplerate
    beats, downbeats = np.array(prediction["beats_seconds"]), np.array(prediction["downbeats_seconds"])
    discarded = {"beats": int(np.sum((beats < 0) | (beats >= duration))),
                 "downbeats": int(np.sum((downbeats < 0) | (downbeats >= duration)))}
    beats = beats[(beats >= 0) & (beats < duration)]
    downbeats = downbeats[(downbeats >= 0) & (downbeats < duration)]
    np.savetxt(args.output_dir / "beats.csv", beats, fmt="%.9f", header="time_seconds", comments="")
    np.savetxt(args.output_dir / "downbeats.csv", downbeats, fmt="%.9f", header="time_seconds", comments="")
    result = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "unreviewed_independent_model_comparison", "scope": "beat/downbeat evidence only; no accepted tempo/meter map",
        "audio": {"path": str(args.audio), "sha256": feature_meta["audio_sha256"], "sample_rate": info.samplerate,
                  "channels": info.channels, "source_frames": info.frames, "analyzed_frames": expected_frames,
                  "duration_seconds": duration, "source_frame_offset": 0},
        "model": {"name": "Beat Transformer", "checkpoint": checkpoint_meta, "frame_rate": FPS,
                  "precision": "float32", "decoder": prediction["decoder"], "upstream": upstream,
                  "frame_time_offset_seconds": 0, "activation_semantics": "raw pre-sigmoid beat/downbeat logits"},
        "frontend": feature_meta, "feature_cache_path": str(features_path),
        "execution": {"device": str(device), "torch_version": torch.__version__, "python": sys.version.split()[0],
                      "platform": platform.platform(), "threads": args.threads, "runner_sha256": file_hash(__file__),
                      "cudnn_enabled": args.enable_cudnn,
                      "helpers_sha256": file_hash(Path(__file__).with_name("beat_transformer.py")),
                      "core_frames": args.core_frames, "context_frames_each_side": args.context_frames,
                      "chunk_spans_core_start_end_input_start_end": spans},
        "timing_seconds": {"frontend_and_model_load": ready-started, "inference": inferred-ready,
                           "official_decoding": prediction["elapsed_seconds"], "total_to_result": time.perf_counter()-started},
        "gpu_memory": memory, "chunk_verification": verification,
        "beats_seconds": beats.tolist(), "downbeats_seconds": downbeats.tolist(),
        "diagnostics": {"beat_count": len(beats), "downbeat_count": len(downbeats),
                        "source_support_filter": "retain 0 <= event < source duration; unfiltered official output in official-decoder.json",
                        "discarded_outside_source": discarded,
                        "beats_beyond_source": int(np.sum(beats >= duration)),
                        "downbeats_beyond_source": int(np.sum(downbeats >= duration)),
                        "official_decoder_constraints": {"min_bpm": 55, "max_bpm": 215, "beats_per_bar": [3, 4]},
                        "reference_alignment": "no annotation-derived adjustment", "accuracy_metrics": None},
    }
    if args.preview:
        from run_beat_this import render_clicks
        audio, rate = sf.read(args.audio, frames=expected_frames, dtype="float32", always_2d=True)
        # Official beat and downbeat DBNs can disagree. Retain both in JSON and
        # render an unaccented beat preview; do not silently coerce one grid.
        clicks, skipped = render_clicks(beats, [], rate, len(audio))
        mix = .7*audio + clicks[:, None]
        gain = min(1., .98/max(float(np.max(np.abs(mix))), 1e-12))
        sf.write(args.output_dir / "click.wav", clicks, rate, subtype="FLOAT")
        sf.write(args.output_dir / "preview.wav", mix*gain, rate, subtype="PCM_16")
        result["preview"] = {"origin_shift_seconds": 0, "sample_frames": len(audio),
                             "accent": "none; separate official downbeat grid retained", "skipped_clicks": skipped}
    (args.output_dir / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"result": str(args.output_dir / "result.json"), "beats": len(beats),
                      "downbeats": len(downbeats), "inference_seconds": inferred-ready, "gpu_memory": memory}), flush=True)


if __name__ == "__main__":
    main()
