"""Compare decoders against identical saved logits, without reference-based tuning."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from legacy_dbn import decode_dbn_from_logits
from run_beat_this import render_clicks, span_pulse_rate, validate_events
from audio_support import nonzero_support, supported_prediction


def diagnostics(beats, downbeats, duration):
    beats, downbeats = validate_events(beats), validate_events(downbeats)
    _, rates = span_pulse_rate(beats)
    db_positions = np.searchsorted(beats, downbeats)
    counts, occurrences = np.unique(np.diff(db_positions), return_counts=True)
    return {
        "beat_count": len(beats), "downbeat_count": len(downbeats),
        "events_beyond_audio": int(np.sum(beats >= duration)),
        "span_rate_p05_p50_p95": np.quantile(rates, [0.05, 0.5, 0.95]).tolist() if rates.size else [],
        "downbeat_spacing_in_predicted_beats": dict(zip(map(str, counts), map(int, occurrences))),
        "accuracy_metrics": None,
    }


def write_preview(directory, beats, downbeats, audio, sr):
    click, skipped = render_clicks(beats, downbeats, sr, len(audio))
    mix = audio * 0.7 + click[:, None]
    peak = float(np.max(np.abs(mix)))
    gain = min(1., .98 / peak) if peak else 1.
    sf.write(directory / "click.wav", click, sr, subtype="FLOAT")
    sf.write(directory / "preview.wav", mix * gain, sr, subtype="PCM_16")
    return {"source_gain": .7, "master_gain": gain, "origin_shift_seconds": 0, "skipped_clicks": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="directory with result.json and logits.npz")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=["legacy_default", "legacy_flexible", "legacy_high_prior"],
                        default=["legacy_default", "legacy_flexible", "legacy_high_prior"])
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--exclude-exterior-silence", action="store_true",
                        help="also compare proposals excluding exact exterior digital silence")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    baseline = json.loads((args.baseline / "result.json").read_text())
    if sha256(args.audio) != baseline["audio"]["sha256"]:
        parser.error("audio hash differs from inference input")
    logits = np.load(args.baseline / "logits.npz")
    beat, downbeat = logits["beat"], logits["downbeat"]
    if beat.ndim != 1 or beat.shape != downbeat.shape or not np.isfinite([beat, downbeat]).all():
        parser.error("expected finite equal one-dimensional logit arrays")
    sr = baseline["audio"]["sample_rate"]
    audio, actual_sr = sf.read(args.audio, frames=baseline["audio"]["analyzed_frames"], dtype="float32", always_2d=True)
    if sr != actual_sr:
        parser.error("sample rate mismatch")
    args.output_dir.mkdir(parents=True)
    # The narrow high-tempo run is an explicit prior-sensitivity control. Its
    # range must never be reported as an automatically selected interpretation.
    variants = [
        ("legacy_default", {}),
        ("legacy_flexible", {"transition_lambda": 10.}),
        ("legacy_high_prior", {"min_bpm": 160., "max_bpm": 240.}),
    ]
    report = {"audio": baseline["audio"], "input_logits_sha256": sha256(args.baseline / "logits.npz"),
              "decoder_sha256": sha256(Path(__file__).with_name("legacy_dbn.py")),
              "runner_sha256": sha256(__file__), "reference_used_for_decoding": False,
              "reference_alignment": "unverified", "variants": {}}
    report["variants"]["official_minimal"] = {
        "audio": baseline["audio"],
        "beats_seconds": baseline["beats_seconds"], "downbeats_seconds": baseline["downbeats_seconds"],
        "diagnostics": diagnostics(baseline["beats_seconds"], baseline["downbeats_seconds"], len(audio) / sr),
    }
    for name, parameters in variants:
        if name not in args.variants:
            continue
        print(f"Decoding {name}: {parameters}", flush=True)
        start = time.perf_counter()
        beats, downbeats, numbers = decode_dbn_from_logits(beat, downbeat, fps=float(logits["fps"]), **parameters)
        seconds = time.perf_counter() - start
        target = args.output_dir / name
        target.mkdir()
        preview = None if args.no_preview else write_preview(target, beats, downbeats, audio, sr)
        data = {"audio": baseline["audio"], "parameters_over_historical_defaults": parameters,
                "prior_sensitivity_control": name == "legacy_high_prior", "decoding_seconds": seconds,
                "beats_seconds": beats.tolist(), "downbeats_seconds": downbeats.tolist(),
                "beat_numbers": numbers.tolist(), "diagnostics": diagnostics(beats, downbeats, len(audio) / sr),
                "preview": preview}
        (target / "result.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
        report["variants"][name] = data
        print(f"{name}: {len(beats)} beats, {len(downbeats)} downbeats in {seconds:.3f}s", flush=True)
    if args.exclude_exterior_silence:
        support = nonzero_support(audio, sr)
        report["audio_support_module_sha256"] = sha256(Path(__file__).with_name("audio_support.py"))
        for name, original in list(report["variants"].items()):
            supported = supported_prediction(original, support, sr)
            beats, downbeats = supported["beats_seconds"], supported["downbeats_seconds"]
            supported["diagnostics"] = diagnostics(beats, downbeats, len(audio)/sr)
            target = args.output_dir / (name + "_supported")
            target.mkdir()
            supported["preview"] = None if args.no_preview else write_preview(target, beats, downbeats, audio, sr)
            (target / "result.json").write_text(json.dumps(supported, indent=2, allow_nan=False) + "\n")
            report["variants"][name + "_supported"] = supported
    (args.output_dir / "comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
