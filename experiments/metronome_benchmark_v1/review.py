"""Review a completed run's execution contracts without changing its results."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .inference import validate_source, write_json


def review(run, comparison=None):
    read = lambda name: json.loads((run / name).read_text())
    results = read("results.json")
    qualification = read("qualification.json")
    receipt = read("inference-receipt.json")
    inputs = read("source-inputs.json")["samples"]
    rows, summary = results["rows"], results["summary"]
    prepared = qualification["rows"]
    feature_run = results["protocol"]["dataset"] == "GTZAN"
    selected = [row for row in prepared if row.get("selected_for_inference", row["eligible"])]
    ids = {row["id"] for row in selected}
    try:
        validate_source(inputs)
        source_valid = True
    except ValueError:
        source_valid = False
    checks = {
        "all_catalog_rows_retained": len(rows) == len(prepared) == summary["catalog_count"]
            and {row["id"] for row in rows} == {row["id"] for row in prepared},
        "catalog_partition_reconciles": summary["catalog_count"] == summary["qualified_count"]
            + summary["excluded_count"] + summary["source_error_count"],
        "qualification_precedes_predictions": qualification["qualification_precedes_predictions"] is True,
        "no_per_recording_manual_judgment": qualification["manual_judgments"] == summary["manual_judgments"] == 0,
        "source_manifest_rejects_reference_fields": source_valid,
        "worker_inputs_match_selected_cohort": {row["id"] for row in inputs} == ids and len(inputs) == len(ids),
        "all_selected_inputs_processed": {row["id"] for row in receipt["samples"]} == ids
            and len(receipt["samples"]) == len(ids),
        "audio_preparation_did_not_read_references_or_hints": receipt["reference_files_read"] is False
            and receipt["hint_files_read"] is False,
        "unit_selection_after_audio_preparation": receipt["all_families_prepared_at_utc"]
            < receipt["unit_selection_completed_at_utc"],
        "scoring_conditions_complete": all(set(row.get("conditions", {})) == set(results["protocol"]["conditions"])
            for row in rows if row["id"] in ids),
        "failures_retained_in_denominators": all(
            condition.get("selected_denominator", condition.get("qualified_denominator")) == len(ids)
            and condition.get("returned_predictions", condition.get("returned_clocks"))
                + condition["failed_or_abstained"] == len(ids)
            for condition in summary["conditions"].values()),
        "at_least_one_source_prediction_returned": summary["conditions"]["audio_only"].get(
            "returned_predictions", summary["conditions"]["audio_only"].get("returned_clocks", 0)) > 0,
        "unsupported_producer_precision_unscored": (
            summary["producer_precision_scored"] is False
            if feature_run else summary["absolute_phase_qualified_count"] == 0 and summary["absolute_phase_accuracy"] is None)
            and all((data["metrics"]["producer_precision_scored"] is False if feature_run
                     else data["metrics"]["absolute_phase"]["scored"] is False)
                    for row in rows if row["id"] in ids for data in row["conditions"].values()),
        "report_artifacts_created": all((run / name).is_file() and (run / name).stat().st_size > 0
            for name in ["report.html", "results.csv", "summary.json"]),
        "summary_matches_full_results": read("summary.json") == summary,
    }
    if feature_run:
        split = read("split.json")
        checks["reserved_inputs_not_inferred"] = all(row["role"] != "reserved" for row in selected)
        checks["selection_matches_frozen_group_roles"] = set(split["selected_ids"]) == ids and all(
            split["parent_group_roles"][row["parent_group"]] == row["role"] for row in prepared if "parent_group" in row)
        checks["one_pilot_input_per_exact_feature_group"] = len({row["parent_group"] for row in selected}) == len(ids)
    if comparison is not None:
        previous = json.loads((comparison / "results.json").read_text())
        checks["summary_reproduced"] = previous["summary"] == summary
        checks["predictions_reproduced"] = all(
            json.loads((run / "predictions" / name / f"{ident}.json").read_text()) ==
            json.loads((comparison / "predictions" / name / f"{ident}.json").read_text())
            for ident in ids for name in results["protocol"]["conditions"])
    return {"reviewed_at_utc": datetime.now(timezone.utc).isoformat(), "run": str(run),
            "comparison": str(comparison) if comparison else None, "checks": checks,
            "execution_path_passed": all(checks.values()),
            "model_accuracy_is_not_a_workflow_pass_criterion": True,
            "precise_producer_clock_evaluation_ready": False,
            "source_errors_recorded": summary["source_error_count"],
            "selected_count": len(ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new review output; existing evidence is preserved")
    result = review(args.run.resolve(), args.comparison.resolve() if args.comparison else None)
    write_json(args.output, result)
    print(json.dumps(result, indent=2), flush=True)
    if not result["execution_path_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
