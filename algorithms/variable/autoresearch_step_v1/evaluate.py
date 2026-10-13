"""Separate evaluator for the three preparation comparators and sensitivity."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from .common import CONSTANT, HELD, HISTORICAL, ROOT, digest, guard, read, stamp, write
from .objective import DEFAULTS, load_native_api, score_one
from .sensitivity_api import with_tolerances

METHODS = (HISTORICAL, HELD, CONSTANT)


def score_output(prediction, item, reference, api, config=None, *, historical=False):
    result = score_one(prediction, reference, api=api, expected_initial=item["pinned_initial"],
                       expected_duration=item["source"]["duration_seconds"],
                       hold_meter=not historical, config=config)
    if not result["contract_ok"]:
        # The frozen reference regions still define the failed output's denominator.
        post = [{"index": i, "start": right["start"], "end": right["end"],
                 "post_change_region": True, "joint_fraction": 0.0,
                 "stable_joint_fraction": 0.0, "preferred_fraction": 0.0,
                 "stable_preferred_fraction": 0.0, "localized_change_success": False,
                 "successful_joint_quality": 0.0, "successful_preferred_quality": 0.0}
                for i, (left, right) in enumerate(zip(reference["states"], reference["states"][1:]), 1)
                if abs(left["end"] - right["start"]) < 1e-7 and abs(left["bpm"] - right["bpm"]) > 1e-8]
        result["post_change_regions"] = post
    return result


def summary(rows):
    result = []
    for method in METHODS:
        for role in ("primary_known_development", "fixed_complete_pilot"):
            chosen = [r for r in rows if r["method"] == method and r["role"] == role]
            if not chosen:
                continue
            fixed = role == "fixed_complete_pilot"
            value = {"method": method, "group": role, "songs": len(chosen),
                "song_equal_mean_time_weighted_acceptable": float(np.mean([r["stable_joint_fraction"] for r in chosen])),
                "song_equal_mean_time_weighted_preferred": float(np.mean([r["stable_preferred_fraction"] for r in chosen])),
                "contract_failures": sum(not r["contract_ok"] for r in chosen),
                "reference_transition_denominator": sum(r["tempo_transitions"] for r in chosen),
                "localized_required_transitions": sum(sum(b["localized_success"] and b["required_to_preserve_acceptable_map"]
                    for b in r.get("reference_tempo_boundaries", [])) for r in chosen),
                "unnecessary_changes": sum(sum(e["classification"] == "UNNECESSARY_CHANGE" for e in r["native_changes"]) for r in chosen),
                "bad_tempo_changes": sum(r["bad_tempo_changes"] or 0 for r in chosen),
                "failed_bad_change_count_unknown": any(r["bad_tempo_changes"] is None for r in chosen)}
            if not fixed:
                value.update(V_acceptable_success=float(np.mean([r["post_change_score"] or 0 for r in chosen])),
                             W_preferred_success=float(np.mean([r["post_change_preferred_score"] or 0 for r in chosen])),
                             raw_post_change_coverage_diagnostic=float(np.mean([r["post_change_coverage"] or 0 for r in chosen])))
            result.append(value)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    guard(run)
    guard(run, evaluation=True)
    index = read(run / "evaluation-index.json")["rows"]
    api = load_native_api(ROOT)
    predictions, references = {}, {}
    rows, default_api_checks = [], []
    start = time.perf_counter()
    for item in index:
        key = item["key"]
        reference = read(item["reference_path"])
        references[key] = reference
        for method in METHODS:
            path = run / "predictions" / method / (key + ".json")
            try:
                prediction = read(path)
            except (OSError, ValueError) as exc:
                prediction = {"status": "missing_or_malformed_output", "error": str(exc)}
            predictions[key, method] = prediction
            scored = score_output(prediction, item, reference, api, historical=method == HISTORICAL)
            row = {"key": key, "original_id": item["original_id"], "title": item["title"],
                   "role": item["role"], "method": method, "tempo_transitions": item["tempo_transitions"], **scored}
            rows.append(row)
            if scored["contract_ok"]:
                times = np.arange(0.025, max(b for _, b in reference["support"]), 0.05)
                fields = api["native_arrays"](prediction, times)
                alternate_api = with_tolerances(api, 0.07, 0.005)
                default_api_checks.append({"key": key, "method": method,
                    "identical": all(np.array_equal(a, b) for a, b in zip(
                        api["validity"](fields, times, reference),
                        alternate_api["validity"](fields, times, reference)))})
    if not all(r["identical"] for r in default_api_checks):
        raise RuntimeError("Sensitivity API disagrees with preserved default evaluator")
    write(run / "metrics.json", {"at_utc": stamp(), "objective_version": "reviewed_readings_draft_0.2",
        "rows": rows, "summary": summary(rows), "evaluator_wall_seconds": time.perf_counter() - start,
        "historical_is_rescored_preserved_output_not_a_new_same_condition_baseline": True,
        "numerical_thresholds_owner_approved": False})
    variants = [
        ("boundary_0.5_beats", {"maximum_boundary_error_reference_beats": 0.5}, None),
        ("boundary_1_beat", {"maximum_boundary_error_reference_beats": 1.0}, None),
        ("boundary_2_beats", {"maximum_boundary_error_reference_beats": 2.0}, None),
        ("penalty_4_seconds", {"unnecessary_change_penalty_seconds": 4.0}, None),
        ("penalty_16_seconds", {"unnecessary_change_penalty_seconds": 16.0}, None),
        ("phase_35ms", {"half_bar_phase_tolerance_seconds": 0.035}, (0.035, 0.005)),
        ("phase_100ms", {"half_bar_phase_tolerance_seconds": 0.100}, (0.100, 0.005)),
        ("rate_0.25_percent", {"half_bar_relative_period_tolerance": 0.0025}, (0.070, 0.0025)),
        ("rate_1_percent", {"half_bar_relative_period_tolerance": 0.010}, (0.070, 0.010)),
    ]
    sensitivity = []
    for name, cfg, tolerance in variants:
        current_api = with_tolerances(api, *tolerance) if tolerance else api
        values = []
        for item in index:
            for method in METHODS:
                scored = score_output(predictions[item["key"], method], item, references[item["key"]],
                                      current_api, cfg, historical=method == HISTORICAL)
                values.append({"key": item["key"], "original_id": item["original_id"],
                               "title": item["title"], "role": item["role"], "method": method,
                               "tempo_transitions": item["tempo_transitions"], **scored})
        sensitivity.append({"name": name, "configuration": cfg,
                            "phase_rate_tolerance_override": tolerance,
                            "rows": values, "summary": summary(values)})
    write(run / "sensitivity.json", {"variants": sensitivity,
        "not_used_to_choose_a_favorable_algorithm_score": True,
        "default_API_identity_checks": default_api_checks,
        "owner_numeric_approval_pending": True})
    initial_rows = []
    for item in index:
        ref = references[item["key"]]
        constant = next(r for r in rows if r["key"] == item["key"] and r["method"] == CONSTANT)
        first = next((r for r in constant.get("all_regions", []) if r["index"] == 0), None)
        initial_rows.append({"key": item["key"], "title": item["title"],
            "original_id": item["original_id"], "pinned_initial": item["pinned_initial"],
            "reference_initial_evaluator_only": ref["states"][0], "initial_region": first,
            "preferred_initial_is_limited": first is None or first["preferred_fraction"] < 1 - 1e-9,
            "reference_initial_not_substituted_into_inference": True,
            "approved_support": ref["support"], "full_audio_seconds": item["source"]["duration_seconds"]})
    write(run / "initial-diagnostics.json", {"rows": initial_rows})
    worker_rows = [read(p) for p in sorted((run / "worker-audit").glob("*.json"))]
    runtime = {method: sum(w["stage_timings"].get(method, {}).get("fit_wall_seconds", 0) for w in worker_rows)
               for method in (HELD, CONSTANT)}
    write(run / "runtime.json", {"rows": worker_rows, "fit_wall_seconds_sum": runtime,
        "observations_and_source_candidates_reused": True,
        "load_wall_seconds_sum": sum(w["stage_timings"].get("load_frozen_observations_and_candidates_seconds", 0) for w in worker_rows),
        "neural_PCM_and_candidate_preparation_PC_runtime_unmeasured": True,
        "historical_PC_runtime_measured": False,
        "historical_comparator_is_not_reexecuted": True,
        "proposed_ratio_limit": 2.0, "ratio_limit_owner_approved": False,
        "not_a_candidate_selection": True})
    protected = read(run / "protected-inputs.json")["files"]
    changed = [path for path, sha in protected.items() if not Path(path).is_file() or digest(path) != sha]
    forbidden = [p for r in worker_rows for p in r["forbidden_reads"]]
    checks = {"all_selected_songs_in_each_denominator": len(rows) == 3 * len(index),
              "source_worker_audits_complete": len(worker_rows) == len(index),
              "no_forbidden_source_reads": not forbidden,
              "originals_and_frozen_inputs_preserved": not changed,
              "held_and_constant_contracts_pass": all(r["contract_ok"] for r in rows if r["method"] != HISTORICAL),
              "sensitivity_default_matches_native": all(r["identical"] for r in default_api_checks)}
    write(run / "audit.json", {"at_utc": stamp(), "checks": checks, "all_pass": all(checks.values()),
        "changed_protected_paths": changed, "forbidden_source_reads": forbidden,
        "source_worker_errors": [r["error"] for r in worker_rows if r["error"]],
        "source_input_role_and_reference_fields": [], "optimizer_iterations": 0,
        "Windows_listening_validation_run": False})
    guard(run)
    guard(run, evaluation=True)
    for value in summary(rows):
        print(value, flush=True)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
