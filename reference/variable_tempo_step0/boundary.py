"""Oracle neighboring-clock switch on the unchanged continuous source timeline.

The event objective is independent of analysis-window edges. Exact objective
plateaus and sensitivity to one sensor frame remain explicit. Optional grid
continuity uses supplied oracle phases and is never called audio-only precision.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from .common import describe, read_json, write_json
from .support import MATCH, load_evidence, observable_channel, runs


def alignment_at(times, clock, sigma):
    period, phase = clock["period_seconds"], clock["phase_seconds"]
    residual = (times - phase + period / 2) % period - period / 2
    return np.exp(-.5 * (residual / sigma) ** 2)


def intervals(indices, events, duration):
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    return [[float(events[group[0] - 1]) if group[0] else 0.0,
             float(events[group[-1]]) if group[-1] < len(events) else duration] for group in groups]


def localize(evidence, left, right, sigma, bracket=None):
    events, weights = observable_channel(evidence, max(left["period_seconds"], right["period_seconds"]))
    if bracket is not None:
        keep = (events >= bracket[0]) & (events <= bracket[1])
        events, weights = events[keep], weights[keep]
    if len(events) < 4:
        return {"status": "UNKNOWN_insufficient_events", "audio_time_seconds": None}
    score_left, score_right = alignment_at(events, left, sigma), alignment_at(events, right, sigma)
    delta = weights * (score_left - score_right)
    prefix = np.r_[0.0, np.cumsum(delta)]
    best_index = int(np.argmax(prefix))
    best = float(prefix[best_index])
    total_right = float(weights @ score_right)
    best_single = max(float(weights @ score_left), total_right)
    switch_gain = total_right + best - best_single
    frame = 1 / evidence["fps"]
    sensitivity = max(float(np.max(abs(weights * (alignment_at(events + shift, left, sigma)
                                               - alignment_at(events + shift, right, sigma)) - delta))) for shift in (-frame, frame))
    optimal = np.flatnonzero(abs(prefix - best) <= 1e-8)
    near = np.flatnonzero(prefix >= best - sensitivity)
    optimum_intervals = intervals(optimal, events, evidence["duration"])
    sensitive_intervals = intervals(near, events, evidence["duration"])
    selected = max(optimum_intervals, key=lambda item: item[1] - item[0])
    midpoint = sum(selected) / 2
    left_preferences = int(np.sum(delta[:best_index] > 1e-8))
    right_preferences = int(np.sum(delta[best_index:] < -1e-8))
    supported = switch_gain > sensitivity and left_preferences >= 2 and right_preferences >= 2
    status = "supported_two_clock_switch" if supported else "UNKNOWN_no_robust_switch_advantage"
    result = {"status": status, "audio_time_seconds": midpoint if supported else None,
              "unqualified_objective_midpoint_seconds": midpoint,
              "optimal_intervals_seconds": optimum_intervals,
              "one_sensor_frame_sensitivity_intervals_seconds": sensitive_intervals,
              "score_gain_over_best_single_clock": switch_gain,
              "one_sensor_frame_score_sensitivity": sensitivity,
              "preferential_source_events_left_right": [left_preferences, right_preferences],
              "interval_is_not_a_calibrated_confidence_interval": True,
              "window_boundary_used": False, "source_derived_search_bracket": bracket}
    candidates = []
    if supported:
        for start, end in sensitive_intervals:
            first = math.ceil((start - left["phase_seconds"]) / left["period_seconds"])
            stop = math.floor((end - left["phase_seconds"]) / left["period_seconds"])
            for index in range(first, stop + 1):
                t = left["phase_seconds"] + index * left["period_seconds"]
                distance = abs((t - right["phase_seconds"] + right["period_seconds"] / 2)
                               % right["period_seconds"] - right["period_seconds"] / 2)
                candidates.append((distance, abs(t - midpoint), t))
    if candidates:
        distance, _, t = min(candidates)
        result["oracle_phase_continuity"] = {"time_seconds": t, "right_grid_residual_seconds": distance,
              "assumes_change_on_quarter_grid": True, "supplied_oracle_phases_used": True,
              "not_audio_only_boundary_precision": True}
    else:
        result["oracle_phase_continuity"] = None
    return result


def support_bracket(run, ident, left, right, support_name, span):
    clusters = []
    for clock in (left, right):
        with np.load(run / support_name / "predictions" / ident / f"{clock['clock_id']}-span{span}.npz") as data:
            times, states = data["times"], data["states"]
            blocks = runs(states == MATCH, times, .1)
            for block in blocks:
                keep = (times >= block["start_seconds"]) & (times < block["end_seconds"])
                block["evidence_strength"] = float(np.sum(data["alignment"][keep] * data["occupancy"][keep]) * .1)
                block["center"] = (block["start_seconds"] + block["end_seconds"]) / 2
            clusters.append(blocks)
    pairs = []
    for a in clusters[0]:
        for b in clusters[1]:
            if b["center"] <= a["center"]:
                continue
            # Integrated support rewards sustained evidence without a fixed
            # duration cutoff. The ordered anchors are inferred from source.
            score = a["evidence_strength"] * b["evidence_strength"] / max(b["center"] - a["center"], .1)
            pairs.append((score, a, b))
    if not pairs:
        return None, {"status": "no_ordered_source_supported_anchors", "left_match_runs": len(clusters[0]), "right_match_runs": len(clusters[1])}
    _, a, b = max(pairs, key=lambda item: item[0])
    bracket = [max(0, a["start_seconds"] - span * left["period_seconds"] / 2),
               b["end_seconds"] + span * right["period_seconds"] / 2]
    return bracket, {"left_anchor": a, "right_anchor": b, "pair_count": len(pairs),
                     "anchors_are_not_predicted_tempo_change_timestamps": True}


def predict(run, output, support_name=None, span=8, acoustic_evidence=False):
    model = read_json(run / "model-config.json")
    rows = []
    for source in read_json(run / "oracle-admission.json")["rows"]:
        ident = source["id"]
        clocks = read_json(run / "oracle-clocks" / f"{ident}.json")["clocks"]
        if len(clocks) < 2:
            continue
        evidence = load_evidence(run / ("acoustic-evidence" if acoustic_evidence else "original/evidence") / f"{ident}.npz", model)
        for left, right in zip(clocks, clocks[1:]):
            bracket, anchors = (None, None)
            if support_name:
                bracket, anchors = support_bracket(run, ident, left, right, support_name, span)
            result = (localize(evidence, left, right, model["residual_sigma_seconds"], bracket)
                      if not support_name or bracket is not None else {"status": "UNKNOWN_no_source_support_bracket", "audio_time_seconds": None})
            rows.append({"id": ident, "left_clock_id": left["clock_id"], "right_clock_id": right["clock_id"],
                         "result": result, "source_support_anchors": anchors,
                         "oracle_clock_condition": True, "true_transition_timestamp_supplied": False})
    write_json(output / "predictions.json", {"rows": rows, "reference_support_or_boundary_files_read": False,
               "method": "whole-source two-clock event explanation; no recursive segmentation"})


def evaluate(run, output):
    predictions = read_json(output / "predictions.json")["rows"]
    admission = {r["id"]: r for r in read_json(run / "oracle-admission.json")["rows"]}
    refs, rows = {}, []
    for row in predictions:
        ident = row["id"]
        if ident not in refs:
            refs[ident] = read_json(run / "evaluation-references" / f"{ident}.json")
        segments = refs[ident]["labeled_segments"]
        right = next(s for s in segments if s["clock_id"] == row["right_clock_id"])
        true_t, period = right["start_seconds"], 60 / right["quarter_bpm"]
        result = row["result"]
        estimate = result["audio_time_seconds"]
        error = estimate - true_t if estimate is not None else None
        phase = result.get("oracle_phase_continuity")
        rows.append({**row, "variant": admission[ident]["variant"], "role": admission[ident]["role"],
                     "reference_tier": admission[ident]["reference_tier"], "reference_time_seconds": true_t,
                     "signed_error_seconds": error, "absolute_error_seconds": abs(error) if error is not None else None,
                     "absolute_error_in_local_beats": abs(error) / period if error is not None else None,
                     "exact_optimum_contains_reference": any(a <= true_t <= b for a, b in result.get("optimal_intervals_seconds", [])),
                     "frame_sensitivity_contains_reference": any(a <= true_t <= b for a, b in result.get("one_sensor_frame_sensitivity_intervals_seconds", [])),
                     "phase_continuity_error_seconds": phase["time_seconds"] - true_t if phase else None,
                     "real_precision_is_practical_owner_map_agreement": admission[ident]["reference_tier"].startswith("tier2")})
    summary = {}
    for group, selected in (("primary_real", [r for r in rows if r["variant"] == "real_variable"]),
                            ("constructed", [r for r in rows if r["variant"] != "real_variable"]),
                            ("constructed_silent_change", [r for r in rows if r["variant"] == "silent_change"]),
                            ("constructed_octave_change", [r for r in rows if r["variant"] == "octave"])):
        returned = [r for r in selected if r["absolute_error_seconds"] is not None]
        summary[group] = {"boundary_denominator": len(selected), "returned_audio_boundaries": len(returned),
                          "missed_or_unknown": len(selected) - len(returned),
                          "absolute_seconds_error_returned": describe([r["absolute_error_seconds"] for r in returned]),
                          "absolute_local_beats_error_returned": describe([r["absolute_error_in_local_beats"] for r in returned]),
                          "exact_optimum_contains_reference": sum(r["exact_optimum_contains_reference"] for r in selected),
                          "frame_sensitivity_contains_reference": sum(r["frame_sensitivity_contains_reference"] for r in selected),
                          "oracle_phase_continuity_absolute_error": describe([abs(r["phase_continuity_error_seconds"]) for r in selected if r["phase_continuity_error_seconds"] is not None])}
    write_json(output / "results.json", {"rows": rows, "summary": summary,
               "known_rates_and_phases_are_oracle_information": True,
               "oracle_phase_continuity_not_claimed_as_audio_only_precision": True,
               "reference_timing_quality_limits_preserved": True})
    print(summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["predict", "evaluate"])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-name", default="boundary")
    parser.add_argument("--support-name")
    parser.add_argument("--span", type=int, choices=[4, 8, 16], default=8)
    parser.add_argument("--acoustic-evidence", action="store_true")
    args = parser.parse_args()
    run, output = args.run.resolve(), args.run.resolve() / args.output_name
    if args.stage == "predict":
        output.mkdir(exist_ok=False)
        write_json(output / "protocol.json", {"support_name": args.support_name, "span_quarters": args.span,
                   "acoustic_evidence": args.acoustic_evidence, "source_support_brackets_used": bool(args.support_name),
                   "reference_boundaries_supplied": False, "window_edges_not_change_timestamps": True,
                   "reason": "Whole-record two-clock objectives can be dominated by unrelated tempo regions. Bound the comparison using source-inferred clock support."})
        predict(run, output, args.support_name, args.span, args.acoustic_evidence)
    else:
        evaluate(run, output)


if __name__ == "__main__":
    main()
