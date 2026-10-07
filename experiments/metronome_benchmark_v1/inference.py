"""Source-only inference worker for the unchanged fixed-metronome estimator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import time
from contextlib import nullcontext


def write_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(content, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_source(rows):
    audio_fields = {"id", "audio_path", "sample_rate", "sample_frames", "channels", "duration_seconds"}
    spect_fields = {"id", "spectrogram_path", "spectrogram_key", "spectrogram_frames",
                   "mel_bands", "fps", "duration_seconds"}
    seen = set()
    for row in rows:
        if set(row) not in (audio_fields, spect_fields) or row["id"] in seen:
            raise ValueError("Source manifest contains missing, duplicate or non-source fields")
        seen.add(row["id"])


def decorate(prediction, duration):
    if prediction.get("period_seconds"):
        from experiments.metronome_reconstruction_v1.grid import timestamps
        signature = prediction["time_signature"]
        prediction["quarter_clicks_seconds"] = timestamps(prediction["period_seconds"], prediction["offset_seconds"], duration).tolist()
        prediction["downbeats_seconds"] = timestamps(prediction["period_seconds"] * signature["numerator"] * 4 / signature["denominator"],
                                                     prediction["offset_seconds"], duration).tolist()
    return prediction


def prepare(args):
    for name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        os.environ[name] = "4"
    import numpy as np
    import soundfile as sf
    import torch
    from beat_this.inference import Audio2Frames, Spect2Frames
    from beat_this.model.postprocessor import Postprocessor
    from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
    from experiments.metronome_reconstruction_v1.infer import make_evidence

    config = json.loads(args.config.read_text())
    rows = json.loads(args.source.read_text())["samples"]
    validate_source(rows)
    if not args.checkpoint.is_file():
        raise FileNotFoundError("A local final0 checkpoint is required")
    torch.set_num_threads(config["torch_threads"])
    torch.set_num_interop_threads(1)
    feature_input = bool(rows) and "spectrogram_path" in rows[0]
    if any(("spectrogram_path" in row) != feature_input for row in rows):
        raise ValueError("A worker batch must use one source representation")
    tracker_type = Spect2Frames if feature_input else Audio2Frames
    tracker = tracker_type(str(args.checkpoint), device="cpu", float16=False)
    bundles = {}
    event_processor = Postprocessor(type="minimal", fps=config["fps"]) if feature_input else None
    receipt = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "samples": [],
               "reference_files_read": False, "hint_files_read": False,
               "source_representation": "published_spectrogram" if feature_input else "waveform",
               "environment": {name: importlib.metadata.version(name) for name in ["numpy", "scipy", "soundfile", "torch", "torchaudio", "beat-this"]}}
    write_json(args.output / "inference-receipt.json", receipt)
    for index, row in enumerate(rows, 1):
        started = time.perf_counter()
        ident = row["id"]
        print(f"INFER {index}/{len(rows)} {ident}", flush=True)
        try:
            if feature_input:
                if row["fps"] != config["fps"] or row["mel_bands"] != 128:
                    raise ValueError("Published features differ from the estimator's input contract")
                path = row["spectrogram_path"]
                if path not in bundles:
                    bundles[path] = np.load(path, allow_pickle=False)
                signal = bundles[path][row["spectrogram_key"]].astype(np.float32)
                if signal.shape != (row["spectrogram_frames"], row["mel_bands"]) or not np.isfinite(signal).all():
                    raise ValueError("Published features differ from their prepared source geometry")
                beat, downbeat = tracker(torch.from_numpy(signal))
            else:
                signal, rate = sf.read(row["audio_path"], dtype="float32", always_2d=True)
                if rate != row["sample_rate"] or signal.shape != (row["sample_frames"], row["channels"]):
                    raise ValueError("Decoded mixture geometry differs from source manifest")
                if not np.isfinite(signal).all():
                    raise ValueError("Nonfinite source audio")
                beat, downbeat = tracker(signal, rate)
            if not torch.isfinite(beat).all() or not torch.isfinite(downbeat).all():
                raise ValueError("Nonfinite sensor evidence")
            beat_array, down_array = beat.cpu().numpy(), downbeat.cpu().numpy()
            np.savez_compressed(args.output / "evidence" / f"{ident}.npz", beat_logits=beat_array,
                                downbeat_logits=down_array, fps=config["fps"], duration_seconds=row["duration_seconds"])
            evidence = make_evidence(beat_array, down_array, row["duration_seconds"], config)
            if args.trace:
                from .trace import CandidateTrace
                tracing = CandidateTrace(args.output / "traces", ident)
            else:
                tracing = nullcontext(None)
            with tracing as trace:
                family = prepare_audio_family(evidence, config)
                write_json(args.output / "families" / f"{ident}.json", family)
                prediction = decorate(select_from_family(family), row["duration_seconds"])
                if trace is not None:
                    trace.finish(family, prediction)
            if event_processor is not None:
                try:
                    beat_events, downbeat_events = event_processor(beat, downbeat)
                    events = {"status": "event_proposal", "quarter_clicks_seconds": beat_events.tolist(),
                              "downbeats_seconds": downbeat_events.tolist(),
                              "method": "official Beat This minimal postprocessor; variable event sequence"}
                except Exception as exc:
                    events = {"status": "inference_failed", "error": f"{type(exc).__name__}: {exc}"}
                write_json(args.output / "predictions" / "beat_this_events" / f"{ident}.json", events)
            status = prediction["status"]
            del signal, beat, downbeat, beat_array, down_array, evidence, family
        except Exception as exc:
            prediction = {"status": "inference_failed", "error": f"{type(exc).__name__}: {exc}"}
            status = "failed"
        write_json(args.output / "predictions" / "audio_only" / f"{ident}.json", prediction)
        item = {"id": ident, "status": status, "seconds": time.perf_counter() - started}
        receipt["samples"].append(item)
        write_json(args.output / "inference-receipt.json", receipt)
        print(json.dumps(item), flush=True)
    for bundle in bundles.values():
        bundle.close()
    receipt["all_families_prepared_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(args.output / "inference-receipt.json", receipt)


def select(args):
    from experiments.metronome_reconstruction_v1.hinted import select_from_family, validate_hint_row
    receipt = json.loads((args.output / "inference-receipt.json").read_text())
    if "all_families_prepared_at_utc" not in receipt:
        raise ValueError("Audio-family preparation has not completed")
    hints = json.loads(args.hints.read_text())["samples"]
    rows = json.loads(args.source.read_text())["samples"]
    validate_source(rows)
    if {row["id"] for row in hints} != {row["id"] for row in rows} or len(hints) != len(rows):
        raise ValueError("Hint and source identities differ")
    durations = {row["id"]: row["duration_seconds"] for row in rows}
    for row in hints:
        validate_hint_row(row)
        ident = row["id"]
        try:
            family = json.loads((args.output / "families" / f"{ident}.json").read_text())
            prediction = decorate(select_from_family(family, row["initial_quarter_bpm_tap"]), durations[ident])
        except Exception as exc:
            prediction = {"status": "inference_failed", "error": f"{type(exc).__name__}: {exc}"}
        write_json(args.output / "predictions" / "correct_unit_diagnostic" / f"{ident}.json", prediction)
    receipt["unit_selection_completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["unit_hints_are_reference_derived"] = True
    write_json(args.output / "inference-receipt.json", receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "select"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hints", type=Path)
    parser.add_argument("--trace", action="store_true", help="Record all tested clocks and source-only search stages")
    args = parser.parse_args()
    if args.stage == "prepare":
        (args.output / "evidence").mkdir(parents=True, exist_ok=True)
        prepare(args)
    else:
        if args.hints is None:
            parser.error("select requires --hints")
        select(args)


if __name__ == "__main__":
    main()
