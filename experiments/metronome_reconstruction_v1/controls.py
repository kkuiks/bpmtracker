"""Requested first-experiment controls. These do not establish music accuracy."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logit

from .grid import match_events, timestamps
from .infer import make_evidence, optimize, score_candidate


def synthetic(bpm, meter, offset, duration, config, *, jitter=0, missing=0,
              extras=False, gap=False, half=False, subdivisions=False, intro=0):
    rng = np.random.default_rng(20261005)
    period = 60 / bpm
    beats = timestamps(period, offset, duration)
    bars = timestamps(meter * period, offset, duration)
    beats = beats[beats >= intro]
    bars = bars[bars >= intro]
    if half:
        beats = beats[::2]
    if missing:
        beats = beats[rng.random(len(beats)) >= missing]
    if gap:
        beats = beats[(beats < duration * 0.35) | (beats > duration * 0.55)]
        bars = bars[(bars < duration * 0.35) | (bars > duration * 0.55)]
    beats = beats + rng.normal(0, jitter, len(beats))
    bars = bars + rng.normal(0, jitter, len(bars))
    t = np.arange(int(np.ceil(duration * config["fps"]))) / config["fps"]
    def curve(events):
        p = np.full(len(t), 0.01)
        for event in events:
            p = np.maximum(p, 0.98 * np.exp(-0.5 * ((t - event) / 0.018) ** 2))
        return p
    beat_curve, down_curve = curve(beats), curve(bars)
    if extras:
        beat_curve = np.maximum(beat_curve, 0.65 * curve(rng.uniform(0, duration, int(duration / 3))))
    if subdivisions:
        beat_curve = np.maximum(beat_curve, 0.35 * curve(timestamps(period, offset + period / 2, duration)))
    return make_evidence(logit(np.clip(beat_curve, 1e-6, 1 - 1e-6)),
                         logit(np.clip(down_curve, 1e-6, 1 - 1e-6)), duration, config)


def circular_error(prediction, expected, bar_period):
    return abs((prediction - expected + bar_period / 2) % bar_period - bar_period / 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    cases = [
        ("perfect_4_4", 120, 4, 0.237, 60, {}),
        ("perfect_3_4", 133 + 1 / 3, 3, 0.731, 90, {}),
        ("timing_jitter", 120, 4, 0.237, 90, {"jitter": 0.008}),
        ("missing_beats", 120, 4, 0.237, 90, {"missing": 0.2}),
        ("extra_beats", 120, 4, 0.237, 90, {"extras": True}),
        ("missing_region", 120, 4, 0.237, 90, {"gap": True}),
        ("subdivision_evidence", 120, 4, 0.237, 90, {"subdivisions": True}),
        ("intro_silence", 120, 4, 0.237, 90, {"intro": 8}),
        ("half_time_underdetermined", 120, 4, 0.237, 90, {"half": True}),
    ]
    report = {"purpose": "Synthetic evidence controls before any music fitting; not real-audio success", "cases": []}
    for name, bpm, meter, offset, duration, options in cases:
        start = time.perf_counter()
        evidence = synthetic(bpm, meter, offset, duration, config, **options)
        prediction = optimize(evidence, config)
        error = circular_error(prediction["offset_seconds"], offset, meter * 60 / bpm)
        if options.get("half"):
            passed = bool(prediction["confidence_flags"])
        else:
            passed = (abs(prediction["quarter_bpm"] - bpm) < 1e-8
                      and prediction["time_signature"]["numerator"] == meter and error < 0.015)
        row = {"name": name, "passed": bool(passed), "expected_bpm": bpm, "expected_meter": meter,
               "predicted_bpm": prediction["quarter_bpm"], "predicted_meter": prediction["time_signature"],
               "phase_error_seconds": error, "flags": prediction["confidence_flags"],
               "elapsed_seconds": time.perf_counter() - start}
        report["cases"].append(row)
        print(json.dumps(row), flush=True)
    evidence = synthetic(120, 4, 0.237, 300, config)
    correct = score_candidate(evidence, 120, 4, 0.237, config)
    wrong = score_candidate(evidence, 120.1, 4, 0.237, config)
    report["cases"].append({"name": "small_bpm_error_drift", "passed": correct["score"] > wrong["score"],
                            "correct_score": correct["score"], "wrong_score": wrong["score"]})
    pi, ri = match_events(np.array([0.99, 1.0, 1.01]), np.array([1.0]), 0.03)
    report["cases"].append({"name": "one_to_one_capacity", "passed": len(pi) == len(ri) == 1})
    report["passed"] = all(row["passed"] for row in report["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"controls_passed": report["passed"], "cases": len(report["cases"])}), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
