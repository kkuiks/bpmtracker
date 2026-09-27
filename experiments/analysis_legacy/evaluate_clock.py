"""Known-clock synthetic evaluation, independent of any music reference file."""

import argparse
import json
from pathlib import Path

import numpy as np

from fit_clock import fit_clock, grid_events
from inspect_inputs import sha256


def synthetic_events(rates, lengths, origin, seed, jitter_seconds=.004, quantization_hz=50):
    """Generate exact consecutive pulses with changes on declared pulse indices."""
    if len(rates) != len(lengths) or min(rates) <= 0 or min(lengths) < 1:
        raise ValueError("rates/lengths must be positive and have matching lengths")
    intervals = np.repeat(60 / np.asarray(rates, dtype=float), lengths)
    truth = origin + np.r_[0, np.cumsum(intervals)]
    rng = np.random.default_rng(seed)
    observed = truth + rng.normal(0, jitter_seconds, len(truth))
    if quantization_hz:
        observed = np.rint(observed * quantization_hz) / quantization_hz
    return truth, observed, truth[np.cumsum(lengths)[:-1]]


def evaluate():
    cases = [
        ("constant_noninteger", [137.3], [360], .173),
        ("small_changes", [205., 210., 205., 210.], [240, 80, 64, 80], .091),
        ("different_rates", [97., 101.5, 92.3], [100, 48, 100], .319),
        ("short_section", [150., 156., 150.], [80, 12, 80], .231),
        ("half_level_retained", [102.5, 105.], [160, 80], .089),
    ]
    report = {"scope": "event-sequence fitter only; not acoustic-model or meter accuracy",
              "fitter_sha256": sha256(Path(__file__).with_name("fit_clock.py")),
              "evaluator_sha256": sha256(__file__), "cases": []}
    for index, (name, rates, lengths, origin) in enumerate(cases):
        truth, observed, changes = synthetic_events(rates, lengths, origin, 700 + index)
        proposal = fit_clock(observed)
        fitted_rates = [s["pulse_rate_per_minute"] for s in proposal["segments"]]
        fitted_changes = [s["start_seconds"] for s in proposal["segments"][1:]]
        matched = len(fitted_rates) == len(rates)
        grid = grid_events(proposal)
        errors = np.abs(grid - truth) if len(grid) == len(truth) else None
        report["cases"].append({"name": name, "truth_rates": rates, "fitted_rates": fitted_rates,
                                 "segment_count_matches": matched, "truth_changes_seconds": changes.tolist(),
                                 "fitted_changes_seconds": fitted_changes,
                                 "rate_errors": (np.asarray(fitted_rates) - rates).tolist() if matched else None,
                                 "change_errors_seconds": (np.asarray(fitted_changes) - changes).tolist() if matched else None,
                                 "grid_absolute_error_ms_p50_p95_max": (1000*np.quantile(errors, [.5,.95,1])).tolist() if errors is not None else None,
                                 "status": proposal["status"]})
    truth, observed, _ = synthetic_events([120.], [100], .1, 999, jitter_seconds=0)
    bad = fit_clock(np.delete(observed, 48))
    report["missing_event_control"] = {"status": bad["status"], "diagnostics": bad["diagnostics"]}
    return report


def evaluate_sweep(suite):
    cases = [("constant", [137.3], [360], None),
             ("small_changes", [205,210,205], [160,80,160], None),
             ("one_bar", [205,210,205], [160,4,160], None)]
    if suite == "stress":
        configurations = [(8,.01,50,.004,False)]
        cases.append(("larger_event_jitter", [137.3], [360], .020))
        runs, seed_start = 30, 3000
    elif suite == "sensitivity":
        configurations = [(minimum, penalty, 50,.004,False) for minimum,penalty in [(8,.01),(3,.003),(3,.001),(3,.0003)]]
        runs, seed_start = 12, 6000
    elif suite == "continuous":
        configurations = [(3,.001,50,.004,True), (3,.0001,200,.001,True)]
        runs, seed_start = 12, 8000
    else:
        raise ValueError("unknown sweep suite")
    report = {"scope": "synthetic parameter/precision sensitivity; not held-out recorded-music accuracy",
              "suite": suite, "seed_start": seed_start, "runs_per_case": runs,
              "fitter_sha256": sha256(Path(__file__).with_name("fit_clock.py")),
              "evaluator_sha256": sha256(__file__),
              "declared_tolerance": {"max_change_error_seconds": .5, "max_rate_error": 1.}, "configs": []}
    for minimum,penalty,fps,jitter,continuous in configurations:
        rows = []
        for name,rates,lengths,override_jitter in cases:
            records = []
            for seed in range(seed_start, seed_start+runs):
                truth,observed,changes = synthetic_events(rates,lengths,.1,seed,
                    jitter_seconds=jitter if override_jitter is None else override_jitter, quantization_hz=fps)
                fit = fit_clock(observed,min_events=minimum,split_penalty=penalty,continuous_selection=continuous)
                matched = len(fit["segments"]) == len(rates)
                predicted_changes = np.array([s["start_seconds"] for s in fit["segments"][1:]])
                change_error = float(np.max(abs(predicted_changes-changes))) if matched and len(changes) else 0. if matched else None
                rate_error = float(np.max(abs(np.array([s["pulse_rate_per_minute"] for s in fit["segments"]])-rates))) if matched else None
                records.append({"seed": seed, "segment_count": len(fit["segments"]), "matched_segment_count": matched,
                                "max_change_error_seconds": change_error, "max_rate_error": rate_error,
                                "grid_error_ms_p95": float(1000*np.quantile(abs(grid_events(fit)-truth),.95)),
                                "review_required": fit["status"] == "event_indexing_or_fit_requires_review",
                                "within_declared_tolerance": bool(matched and change_error<=.5 and rate_error<=1.)})
            rows.append({"name": name, "records": records, "matched_counts": sum(r["matched_segment_count"] for r in records),
                         "within_tolerance": sum(r["within_declared_tolerance"] for r in records),
                         "review_flags": sum(r["review_required"] for r in records),
                         "worst_grid_p95_ms": max(r["grid_error_ms_p95"] for r in records)})
            print(suite, minimum, penalty, fps, name, rows[-1]["matched_counts"], rows[-1]["within_tolerance"], flush=True)
        report["configs"].append({"min_events": minimum, "split_penalty": penalty, "fps": fps,
                                  "jitter_seconds": jitter, "continuous_selection": continuous, "cases": rows})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=["smoke", "stress", "sensitivity", "continuous"], default="smoke")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new")
    report = evaluate() if args.suite == "smoke" else evaluate_sweep(args.suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if args.suite == "smoke":
        print(json.dumps(report, indent=2))
    else:
        print(args.output)


if __name__ == "__main__":
    main()
