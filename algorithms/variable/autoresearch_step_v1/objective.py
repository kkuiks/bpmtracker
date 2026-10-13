"""Draft OUTPUT evaluator. It must never be imported by an inference worker.

The owner distinguishes acceptable alternatives from preferred readings.
The objective is an ordered pair, not an invented weighted compromise:
timely-change acceptable quality first, preferred quality second.
Fine numerical tolerances remain provisional pending real-song calibration.
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

VERSION = "reviewed_readings_draft_0.2"
DEFAULTS = {
    "sample_step_seconds": 0.05,
    "unnecessary_change_penalty_seconds": 8.0,
    "fixed_group_mean_decline_max": 0.0,
    "fixed_song_decline_max": 0.0,
    "runtime_ratio_max": 2.0,
    "comparison_epsilon": 1e-9,
    "half_bar_phase_tolerance_seconds": 0.07,
    "half_bar_relative_period_tolerance": 0.005,
    "change_matching_window_seconds": 4.0,
    "maximum_boundary_error_reference_beats": 1.0,
}


def load_native_api(repo_root: str | Path) -> dict[str, Any]:
    """Import the real project in the PC's project environment."""
    sys.path.insert(0, str(Path(repo_root).resolve()))
    metrics = importlib.import_module("experiments.beat_event_map_v1.native_metrics")
    geometry = importlib.import_module("experiments.continuous_beat_map_v1.map")
    return {
        "native_arrays": metrics.native_arrays,
        "validity": metrics.validity,
        "classify": metrics.classify,
        "validate": geometry.validate,
        "sections": geometry.sections,
        "primary_reading_names": [r["name"] for r in metrics.PRIMARY_READINGS],
    }


def contract_errors(prediction, expected_initial=None, expected_duration=None,
                    hold_meter=True, api=None):
    """Missing/malformed output is a failure, never a reason to drop a song."""
    errors = []
    if prediction.get("status") != "map":
        return ["no_map"]
    try:
        duration = float(prediction["duration_seconds"])
        if not math.isfinite(duration) or duration <= 0:
            errors.append("invalid_duration")
        if expected_duration is not None and abs(duration-float(expected_duration)) > 1e-7:
            errors.append("changed_source_duration")
        initial = prediction["initial"]
        for key in ["bpm", "bar_zero_source_seconds"]:
            if not math.isfinite(float(initial[key])):
                errors.append("nonfinite_initial_"+key)
        if float(initial["bpm"]) <= 0:
            errors.append("nonpositive_initial_bpm")
        for key in ["numerator", "denominator"]:
            val = float(initial[key])
            if not math.isfinite(val) or val <= 0 or val != int(val):
                errors.append("invalid_initial_"+key)
        if expected_initial is not None:
            for key in ["bpm", "numerator", "denominator", "bar_zero_source_seconds"]:
                if abs(float(initial[key])-float(expected_initial[key])) > 1e-9:
                    errors.append("changed_pinned_initial_"+key)
        for event in prediction["events"]:
            for key in ["time", "quarter", "bpm", "numerator", "denominator"]:
                if key in event and not math.isfinite(float(event[key])):
                    errors.append("nonfinite_event_"+key)
            if not 0 < float(event["time"]) < duration:
                errors.append("event_outside_source")
            if "bpm" in event and float(event["bpm"]) <= 0:
                errors.append("nonpositive_event_bpm")
            for key in ["numerator", "denominator"]:
                if key in event:
                    val = float(event[key])
                    if not math.isfinite(val) or val <= 0 or val != int(val):
                        errors.append("invalid_event_"+key)
            if hold_meter and any(key in event for key in ["numerator", "denominator"]):
                if (int(event.get("numerator", initial["numerator"])),
                    int(event.get("denominator", initial["denominator"]))) != (
                        initial["numerator"], initial["denominator"]):
                    errors.append("meter_changed_in_tempo_only_task")
        if errors:
            return sorted(set(errors))
        check = api["validate"](prediction)
        if not check["legal"] or not check["continuous_source_coverage"]:
            errors.append("native_contract_failed")
        errors.extend(str(item) for item in check["errors"])
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        errors.append("malformed_output:"+type(exc).__name__)
    return sorted(set(errors))


def reference_bar_anchor(state, reference):
    bars = np.asarray(reference["bars"], float)
    local = bars[(bars >= state["start"]-1e-7) & (bars < state["end"]-1e-7)]
    if len(local):
        return float(local[0])
    return float(bars[np.argmin(abs(bars-state["start"]))]) if len(bars) else state["start"]


def constant_fields(section, times):
    return {k: np.full(len(times), section[k], float) for k in
            ["bpm", "phase", "numerator", "denominator"]}


def quality_masks(fields, times, reference, api, cfg):
    """R1: physical equivalence; R2: half clicks allowed; R3: reviewed split.

The NEW bar alternative is limited to reference 4/4 -> prediction 2/4 with
the SAME ordinary pulse, correctly aligned half-bars. Unreviewed grouping
ratios, doubled bars, arbitrary bar phases, and signatures are not admitted.
"""
    pulse, bar, _, _, support = api["validity"](fields, times, reference)
    preferred_index = api["primary_reading_names"].index("NOTATED_DENOMINATOR")
    preferred_pulse = pulse[preferred_index]
    split = np.zeros(len(times), bool)
    for state in reference["states"]:
        if (state["numerator"], state["denominator"]) != (4, 4):
            continue
        use = support & (times >= state["start"]) & (times < state["end"]) \
            & (fields["numerator"] == 2) & (fields["denominator"] == 4) \
            & preferred_pulse
        if not use.any():
            continue
        period = 60/fields["bpm"][use]*2
        target = 60/state["bpm"]*2
        anchor = reference_bar_anchor(state, reference)
        ticks = fields["phase"][use]+np.rint((times[use]-fields["phase"][use])/period)*period
        error = abs((ticks-anchor+target/2) % target-target/2)
        split[use] = (abs(period/target-1) <= cfg["half_bar_relative_period_tolerance"]+1e-12) \
            & (error <= cfg["half_bar_phase_tolerance_seconds"]+1e-12)
    rows = np.concatenate([pulse & bar, pulse & split], axis=0)
    preferred = preferred_pulse & bar
    legacy = pulse & bar
    return rows, preferred, legacy, support


def coherent_fraction(rows):
    return float(rows.mean(axis=1).max()) if rows.shape[1] else 0.0


def reviewed_changes(prediction, reference, times, api, cfg):
    """One-to-one musical matching and explicit mislocalized changes.

The 1-reference-beat timing limit is a PROVISIONAL numeric interpretation.
The owner rejected the four-beat R5 error; finer errors need real-song review.
"""
    boundaries = []
    for index, (left, right) in enumerate(zip(reference["states"], reference["states"][1:]), 1):
        if abs(left["end"]-right["start"]) > 1e-7 or abs(left["bpm"]-right["bpm"]) <= 1e-8:
            continue
        after = times[(times >= right["start"]) & (times < right["end"])]
        old_reference = {**left, "phase": reference_bar_anchor(left, reference)}
        rows, _, _, _ = quality_masks(constant_fields(old_reference, after), after,
                                      reference, api, cfg)
        required = coherent_fraction(rows) < 1-cfg["comparison_epsilon"]
        boundaries.append({"state_index": index, "time": right["start"],
            "reference_beat_seconds": 60/left["bpm"]*4/left["denominator"],
            "required_to_preserve_acceptable_map": required,
            "localized_success": not required, "matched_event_index": None,
            "error_seconds": None, "error_reference_beats": None})
    segments = api["sections"](prediction)
    changes, edges = [], []
    def acceptable(section, where):
        point = np.asarray([where], float)
        rows, _, _, support = quality_masks(constant_fields(section, point), point,
                                            reference, api, cfg)
        return bool(support[0] and rows[:, 0].any())
    for event_index, event in enumerate(prediction["events"]):
        time = event["time"]
        record = {**event, "event_index": event_index}
        if not any(a <= time < b for a, b in reference["support"]):
            record["classification"] = "OUTSIDE_APPROVED_SCOPE"
            changes.append(record)
            continue
        before = next(s for s in reversed(segments) if s["start"] < time-1e-8)
        after = next(s for s in segments if s["start"] >= time-1e-8)
        record["classification"] = "UNMATCHED"
        record["old_valid_before"] = acceptable(before, time-1e-4)
        record["old_still_valid_after"] = acceptable(before, time+1e-4)
        record["new_valid_after"] = acceptable(after, time+1e-4)
        for boundary_index, boundary in enumerate(boundaries):
            b = boundary["time"]
            if "bpm" in event and boundary["required_to_preserve_acceptable_map"] \
                    and abs(time-b) <= cfg["change_matching_window_seconds"] \
                    and acceptable(before, b-1e-5) and acceptable(after, b+1e-5):
                edges.append((abs(time-b), event_index, boundary_index, time-b))
        changes.append(record)
    assigned_events, assigned_boundaries = set(), set()
    for _, event_index, boundary_index, error in sorted(edges):
        if event_index in assigned_events or boundary_index in assigned_boundaries:
            continue
        assigned_events.add(event_index); assigned_boundaries.add(boundary_index)
        boundary = boundaries[boundary_index]
        beats = abs(error)/boundary["reference_beat_seconds"]
        localized = beats <= cfg["maximum_boundary_error_reference_beats"]+1e-9
        boundary.update(localized_success=localized, matched_event_index=event_index,
                        error_seconds=error, error_reference_beats=beats)
        changes[event_index].update(classification="MUSICAL_CHANGE" if localized
            else "MISLOCALIZED_CHANGE", matched_reference_time=boundary["time"],
            error_seconds=error, error_reference_beats=beats)
    for record in changes:
        if record["classification"] != "UNMATCHED":
            continue
        record["classification"] = "UNNECESSARY_CHANGE" if record["old_still_valid_after"] \
            or record["old_valid_before"] and record["new_valid_after"] else \
            "RECOVERY" if record["new_valid_after"] else "UNSUPPORTED_CHANGE"
    return changes, boundaries


def score_one(prediction, reference, *, api, expected_initial=None,
              expected_duration=None, hold_meter=True, config=None):
    cfg = {**DEFAULTS, **(config or {})}
    errors = contract_errors(prediction, expected_initial, expected_duration,
                             hold_meter, api)
    zero = {"version": VERSION, "contract_ok": False, "errors": errors,
            "joint_fraction": 0.0, "stable_joint_fraction": 0.0,
            "preferred_fraction": 0.0, "stable_preferred_fraction": 0.0,
            "post_change_score": 0.0, "post_change_preferred_score": 0.0,
            "post_change_coverage": 0.0, "post_change_regions": [],
            "calibration_acceptable": False,
            "bad_tempo_changes": None, "native_changes": []}
    if errors:
        return zero
    step = cfg["sample_step_seconds"]
    times = np.arange(step/2, max(b for _, b in reference["support"]), step)
    fields = api["native_arrays"](prediction, times)
    rows, preferred, legacy_rows, support = quality_masks(fields, times, reference, api, cfg)
    if not support.any():
        return {**zero, "errors": ["no_approved_evaluation_samples"]}
    joint = np.zeros(len(times), bool)
    legacy = np.zeros(len(times), bool)
    region_records = []
    for index, state in enumerate(reference["states"]):
        use = support & (times >= state["start"]) & (times < state["end"])
        if not use.any():
            # A region with no grid sample is not silently removed.
            return {**zero, "errors": ["reference_region_shorter_than_grid_step"]}
        counts = rows[:, use].sum(axis=1)
        choice = int(np.argmax(counts))
        joint[use] = rows[choice, use]
        old_choice = int(np.argmax(legacy_rows[:, use].sum(axis=1)))
        legacy[use] = legacy_rows[old_choice, use]
        previous = reference["states"][index-1] if index else None
        post = previous is not None and abs(previous["end"]-state["start"]) < 1e-7 \
            and abs(previous["bpm"]-state["bpm"]) > 1e-8
        region_records.append({"index": index, "start": state["start"],
                               "end": state["end"], "reading_index": choice,
                               "post_change_region": post})
    changes, boundaries = reviewed_changes(prediction, reference, times, api, cfg)
    penalty = np.zeros(len(times), bool)
    for event in changes:
        if event["classification"] == "UNNECESSARY_CHANGE":
            penalty |= (times >= event["time"]) & (
                times < event["time"]+cfg["unnecessary_change_penalty_seconds"])
    stable = joint & ~penalty
    stable_preferred = preferred & ~penalty
    for row in region_records:
        use = support & (times >= row["start"]) & (times < row["end"])
        row["joint_fraction"] = float(joint[use].mean())
        row["stable_joint_fraction"] = float(stable[use].mean())
        row["preferred_fraction"] = float(preferred[use].mean())
        row["stable_preferred_fraction"] = float(stable_preferred[use].mean())
        boundary = next((b for b in boundaries if b["state_index"] == row["index"]), None)
        row["localized_change_success"] = boundary["localized_success"] if boundary else True
        row["successful_joint_quality"] = row["stable_joint_fraction"] \
            if row["localized_change_success"] else 0.0
        row["successful_preferred_quality"] = row["stable_preferred_fraction"] \
            if row["localized_change_success"] else 0.0
    post_rows = [row for row in region_records if row["post_change_region"]]
    bad = sum("bpm" in e and e["classification"] in
              ["UNNECESSARY_CHANGE", "UNSUPPORTED_CHANGE", "MISLOCALIZED_CHANGE"] for e in changes)
    calibration_acceptable = float(joint[support].mean()) >= 1-cfg["comparison_epsilon"] \
        and all(b["localized_success"] for b in boundaries) \
        and not any(e["classification"] in ["UNNECESSARY_CHANGE", "UNSUPPORTED_CHANGE",
            "MISLOCALIZED_CHANGE"] for e in changes)
    return {"version": VERSION, "contract_ok": True, "errors": [],
            "joint_fraction": float(joint[support].mean()),
            "stable_joint_fraction": float(stable[support].mean()),
            "preferred_fraction": float(preferred[support].mean()),
            "stable_preferred_fraction": float(stable_preferred[support].mean()),
            "legacy_strict_bar_joint_fraction": float(legacy[support].mean()),
            "calibration_acceptable": calibration_acceptable,
            "calibration_acceptance_is_not_product_threshold": True,
            "post_change_score": float(np.mean([r["successful_joint_quality"]
                for r in post_rows])) if post_rows else None,
            "post_change_preferred_score": float(np.mean([r["successful_preferred_quality"]
                for r in post_rows])) if post_rows else None,
            "post_change_coverage": float(np.mean([r["stable_joint_fraction"]
                for r in post_rows])) if post_rows else None,
            "post_change_regions": post_rows, "all_regions": region_records,
            "bad_tempo_changes": bad, "native_changes": changes,
            "reference_tempo_boundaries": boundaries}


def compare_cohort(candidate_rows, baseline_rows, constant_rows, primary_ids,
                   fixed_groups, *, config=None, candidate_seconds=None,
                   baseline_seconds=None):
    """Feasibility first, then lexicographic acceptable/preferred quality.

Inputs are dicts id -> score_one record. Failed outputs must be present as
zero-valued records. All groups and ids are frozen BEFORE candidate inference.
"""
    cfg = {**DEFAULTS, **(config or {})}
    eps = cfg["comparison_epsilon"]
    ids = set(primary_ids).union(*(set(v) for v in fixed_groups.values()))
    violations = []
    for name, rows in [("candidate", candidate_rows), ("baseline", baseline_rows),
                       ("constant", constant_rows)]:
        missing = sorted(ids-set(rows))
        if missing:
            violations.append(name+"_missing_ids:"+",".join(missing))
    if violations:
        return {"eligible": False, "violations": violations, "objective": None}
    if not primary_ids:
        return {"eligible": False, "violations": ["no_primary_variable_songs"],
                "objective": None}
    for ident in sorted(ids):
        if not candidate_rows[ident]["contract_ok"]:
            violations.append("candidate_contract:"+ident)
        for name, rows in [("baseline", baseline_rows), ("constant", constant_rows)]:
            if not rows[ident]["contract_ok"]:
                violations.append(name+"_contract:"+ident)
    fixed_report = {}
    for group, members in fixed_groups.items():
        if not members:
            violations.append("empty_fixed_group:"+group)
            continue
        diffs = [candidate_rows[i]["stable_joint_fraction"]-
                 baseline_rows[i]["stable_joint_fraction"] for i in members]
        preference_diffs = [candidate_rows[i]["stable_preferred_fraction"]-
                           baseline_rows[i]["stable_preferred_fraction"] for i in members]
        bad_c = sum(candidate_rows[i]["bad_tempo_changes"] or 0 for i in members)
        bad_b = sum(baseline_rows[i]["bad_tempo_changes"] or 0 for i in members)
        fixed_report[group] = {"mean_delta": float(np.mean(diffs)),
            "worst_song_delta": min(diffs), "candidate_bad_changes": bad_c,
            "baseline_bad_changes": bad_b,
            "preferred_mean_delta": float(np.mean(preference_diffs)),
            "preferred_worst_song_delta": min(preference_diffs)}
        if np.mean(diffs) < -cfg["fixed_group_mean_decline_max"]-eps:
            violations.append("fixed_group_decline:"+group)
        if min(diffs) < -cfg["fixed_song_decline_max"]-eps:
            violations.append("fixed_song_decline:"+group)
        if np.mean(preference_diffs) < -cfg["fixed_group_mean_decline_max"]-eps \
                or min(preference_diffs) < -cfg["fixed_song_decline_max"]-eps:
            violations.append("fixed_preference_decline:"+group)
        if bad_c > bad_b:
            violations.append("fixed_bad_changes_increased:"+group)
    if any(rows[i]["post_change_score"] is None for rows in
           [candidate_rows, baseline_rows, constant_rows] for i in primary_ids):
        return {"eligible": False, "violations": violations+["missing_post_change_score"],
                "objective": None, "fixed_groups": fixed_report}
    values = [candidate_rows[i]["post_change_score"] for i in primary_ids]
    baseline = [baseline_rows[i]["post_change_score"] for i in primary_ids]
    constant = [constant_rows[i]["post_change_score"] for i in primary_ids]
    preferences = [candidate_rows[i]["post_change_preferred_score"] for i in primary_ids]
    baseline_preferences = [baseline_rows[i]["post_change_preferred_score"] for i in primary_ids]
    constant_preferences = [constant_rows[i]["post_change_preferred_score"] for i in primary_ids]
    diffs = np.asarray(values)-np.asarray(baseline)
    if candidate_seconds is None or baseline_seconds is None or baseline_seconds <= 0:
        violations.append("runtime_not_measured")
        ratio = None
    else:
        ratio = candidate_seconds/baseline_seconds
        if ratio > cfg["runtime_ratio_max"]+eps:
            violations.append("runtime_budget_exceeded")
    objective = float(np.mean(values))
    preferred_objective = float(np.mean(preferences))
    baseline_objective = float(np.mean(baseline))
    baseline_preferred_objective = float(np.mean(baseline_preferences))
    constant_objective = float(np.mean(constant))
    constant_preferred_objective = float(np.mean(constant_preferences))
    def better(a, p, b, q):
        return a > b+eps or abs(a-b) <= eps and p > q+eps
    return {"eligible": not violations, "violations": violations,
            "objective": objective, "baseline_objective": float(np.mean(baseline)),
            "constant_objective": float(np.mean(constant)),
            "rank_objective": [objective, preferred_objective],
            "preferred_objective": preferred_objective,
            "baseline_preferred_objective": baseline_preferred_objective,
            "constant_preferred_objective": constant_preferred_objective,
            "gain_over_baseline": float(np.mean(diffs)),
            "gain_over_constant": objective-float(np.mean(constant)),
            "improved_songs": int((diffs > eps).sum()),
            "regressed_songs": int((diffs < -eps).sum()),
            "median_song_delta": float(np.median(diffs)),
            "development_gain": not violations and better(objective, preferred_objective,
                baseline_objective, baseline_preferred_objective) and better(objective,
                preferred_objective, constant_objective, constant_preferred_objective),
            "runtime_ratio": ratio, "fixed_groups": fixed_report,
            "generalization_verified": False}
