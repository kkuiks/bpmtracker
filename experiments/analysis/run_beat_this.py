"""Run an unmodified Beat This model and its official minimal decoder.

Input must be an already decoded WAV. Outputs are experimental evidence, not
an accepted tempo/meter map. Checkpoints must already exist locally.
"""

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import platform
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf
import torch

from beat_this.inference import Audio2Frames
from beat_this.model.postprocessor import Postprocessor
from inspect_inputs import sha256


def positive_integer(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def validate_events(times):
    times = np.asarray(times, dtype=np.float64)
    if times.ndim != 1 or not np.isfinite(times).all():
        raise ValueError("events must be a finite one-dimensional array")
    if (times < 0).any() or (np.diff(times) <= 0).any():
        raise ValueError("events must be nonnegative and strictly increasing")
    return times


def render_clicks(beats, downbeats, sample_rate, frame_count):
    """Render at absolute sample positions without shifting the source audio."""
    beats, downbeats = validate_events(beats), validate_events(downbeats)
    clicks = np.zeros(frame_count, dtype=np.float32)
    downbeat_frames = set(np.rint(downbeats * sample_rate).astype(np.int64))
    pulse_time = np.arange(max(1, round(sample_rate * 0.025))) / sample_rate
    envelope = np.exp(-pulse_time * 220)
    regular = (0.18 * envelope * np.cos(2 * np.pi * 1500 * pulse_time)).astype(np.float32)
    accent = (0.30 * envelope * np.cos(2 * np.pi * 2200 * pulse_time)).astype(np.float32)
    skipped = 0
    for frame in np.rint(beats * sample_rate).astype(np.int64):
        if frame >= frame_count:
            skipped += 1
            continue
        pulse = accent if frame in downbeat_frames else regular
        length = min(len(pulse), frame_count - frame)
        clicks[frame:frame + length] += pulse[:length]
    return clicks, skipped


def span_pulse_rate(beats, intervals=16):
    """A diagnostic moving span rate; does not segment or correct predictions."""
    beats = validate_events(beats)
    if len(beats) <= intervals:
        return np.array([]), np.array([])
    return (beats[intervals:] + beats[:-intervals]) / 2, 60 * intervals / (beats[intervals:] - beats[:-intervals])


def sync(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def installed_versions():
    return dict(sorted((dist.metadata["Name"], dist.version) for dist in metadata.distributions()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--threads", type=positive_integer, default=4)
    parser.add_argument("--max-seconds", type=float, help="optional prefix for a smoke test")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        parser.error("checkpoint must exist locally; this runner never downloads weights")
    if args.output_dir.exists():
        parser.error("output directory must be new")
    if args.max_seconds is not None and (not np.isfinite(args.max_seconds) or args.max_seconds <= 0):
        parser.error("--max-seconds must be finite and positive")
    info = sf.info(args.audio)
    if not info.format.startswith("WAV"):
        parser.error("use a canonical decoded WAV, not a compressed original")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA is unavailable; verify device access or explicitly select --device cpu")
    device = torch.device(args.device)
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    frames = info.frames if args.max_seconds is None else min(info.frames, round(args.max_seconds * info.samplerate))
    if frames <= 0:
        parser.error("input must contain audio frames")
    audio, sample_rate = sf.read(args.audio, frames=frames, dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        parser.error("audio contains non-finite samples")
    duration = len(audio) / sample_rate
    args.output_dir.mkdir(parents=True)
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    print(f"Loading checkpoint on {device}; {duration:.3f} seconds of audio", flush=True)
    model = Audio2Frames(checkpoint_path=str(args.checkpoint.resolve()), device=str(device), float16=False)
    sync(device)
    loaded = time.perf_counter()
    print("Running official frame inference", flush=True)
    beat_logits, downbeat_logits = model(audio, sample_rate)
    sync(device)
    inferred = time.perf_counter()
    beats, downbeats = Postprocessor(type="minimal", fps=50)(beat_logits, downbeat_logits)
    sync(device)
    decoded = time.perf_counter()
    beats, downbeats = validate_events(beats), validate_events(downbeats)
    memory = None
    if device.type == "cuda":
        memory = {
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
            "total_device_bytes": torch.cuda.get_device_properties(device).total_memory,
        }
    np.savez_compressed(args.output_dir / "logits.npz", beat=beat_logits.detach().cpu().numpy(), downbeat=downbeat_logits.detach().cpu().numpy(), fps=np.array(50))
    np.savetxt(args.output_dir / "beats.csv", beats, fmt="%.9f", header="time_seconds", comments="")
    np.savetxt(args.output_dir / "downbeats.csv", downbeats, fmt="%.9f", header="time_seconds", comments="")
    clicks, skipped_clicks = render_clicks(beats, downbeats, sample_rate, len(audio))
    mix = audio * 0.70 + clicks[:, None]
    mix_peak = float(np.max(np.abs(mix)))
    mix_gain = min(1.0, 0.98 / mix_peak) if mix_peak else 1.0
    sf.write(args.output_dir / "click.wav", clicks, sample_rate, subtype="FLOAT")
    sf.write(args.output_dir / "preview.wav", mix * mix_gain, sample_rate, subtype="PCM_16")
    intervals = np.diff(beats)
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "unreviewed_official_baseline",
        "scope": "beat/downbeat predictions only; no accepted tempo or meter map",
        "audio": {"filename": args.audio.name, "sha256": sha256(args.audio), "sample_rate": sample_rate, "channels": audio.shape[1], "source_frames": info.frames, "analyzed_frames": len(audio), "duration_seconds": duration, "source_frame_offset": 0},
        "model": {"checkpoint_sha256": sha256(args.checkpoint), "checkpoint_filename": args.checkpoint.name, "package_version": metadata.version("beat-this"), "frame_rate": 50, "precision": "float32", "decoder": "official_minimal", "custom_postprocessing": False},
        "execution": {"device": str(device), "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else platform.processor(), "cuda_runtime": torch.version.cuda, "threads": args.threads, "python": sys.version.split()[0], "platform": platform.platform(), "versions": installed_versions(), "runner_sha256": sha256(__file__)},
        "timing_seconds": {"model_load": loaded - started, "inference": inferred - loaded, "decoding": decoded - inferred},
        "inference_realtime_factor": (inferred - loaded) / duration,
        "gpu_memory": memory,
        "beats_seconds": beats.tolist(),
        "downbeats_seconds": downbeats.tolist(),
        "diagnostics": {"beat_count": len(beats), "downbeat_count": len(downbeats), "interval_seconds_p05_p50_p95": np.quantile(intervals, [0.05, 0.5, 0.95]).tolist() if len(intervals) else [], "events_beyond_audio": int(np.sum(beats >= duration)), "reference_alignment": "unverified", "accuracy_metrics": None},
        "preview": {"source_gain": 0.70, "mix_master_gain": mix_gain, "skipped_out_of_range_clicks": skipped_clicks, "origin_shift_seconds": 0},
    }
    (args.output_dir / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{len(beats)} beats, {len(downbeats)} downbeats; inference {inferred - loaded:.3f}s", flush=True)
    print(args.output_dir / "result.json", flush=True)


if __name__ == "__main__":
    main()
