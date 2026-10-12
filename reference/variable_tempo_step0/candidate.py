"""Evaluate rate survival only after source-only Original predictions are saved."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from .common import nearest_rate, oracle_clock, read_json, reference_segments, stored_reference, write_json


def jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def target_reference(run, row, inventory):
    ident = row["id"]
    if ident == "babyslakh_Track00008":
        meta = inventory[ident]
        clock = meta["source_clock"]
        states = clock["tempos"]
        segments = [{"start_seconds": e["source_seconds"],
                     "end_seconds": states[i + 1]["source_seconds"] if i + 1 < len(states) else meta["duration_seconds"],
                     "duration_seconds": (states[i + 1]["source_seconds"] if i + 1 < len(states) else meta["duration_seconds"]) - e["source_seconds"],
                     "quarter_bpm": 60_000_000 / e["value"]} for i, e in enumerate(states)]
        return segments, None
    ref = read_json(row["reference_path"])
    support = row["support_seconds"]
    if "tempo_events" in ref:
        segments = reference_segments(ref, support)
    else:
        segments = [{"start_seconds": start, "end_seconds": end, "duration_seconds": end - start,
                     "quarter_bpm": ref["quarter_bpm"]} for start, end in support]
    stored = stored_reference(ref, support)
    clocks = []
    labeled = []
    for index, segment in enumerate(segments):
        known = oracle_clock(segment, stored["quarter_times_seconds"], stored["downbeat_times_seconds"],
                             8 if ident == "legacy_circle" else 4)
        clock_id = f"clock_{index}"
        if known:
            clocks.append({"clock_id": clock_id, **known})
        labeled.append({**segment, "clock_id": clock_id if known else None})
    expected_unknown = ref.get("expected_unknown_intervals", [])
    return segments, {"id": ident, "clocks": clocks, "labeled_segments": labeled,
                      "stored_quarter_events": stored["quarter_times_seconds"],
                      "stored_downbeat_events": stored["downbeat_times_seconds"],
                      "reference_tier": row["reference_tier"], "support_seconds": support,
                      "expected_unknown_intervals": expected_unknown,
                      "quarter_field": stored["quarter_field"], "additional_offset_applied_seconds": 0}


def stages(root, ident):
    events = list(jsonl(root / "traces" / f"{ident}.events.jsonl.gz"))
    retained_ids = {value for e in events if e["event"] == "block_finished" and str(e["block"]).startswith("layer_")
                    for value in e["retained_score_ids"] if value is not None}
    groups = {name: {} for name in ("broad_bpm_list", "base_scored", "final_family_scored", "retained")}
    for e in events:
        if e["event"] == "broad_bpm_candidates":
            for fraction in e["bpm_fractions"]:
                groups["broad_bpm_list"][fraction["numerator"] / fraction["denominator"]] = None
    counts = Counter()
    for record in jsonl(root / "traces" / f"{ident}.scores.jsonl.gz"):
        row = record["candidate"]
        names = ["base_scored"] if record["block"] == "base_search" else ["final_family_scored"]
        if record["score_id"] in retained_ids:
            names.append("retained")
        for name in names:
            rate = row["quarter_bpm"]
            counts[name] += 1
            old = groups[name].get(rate)
            if old is None or row["score"] > old["score"]:
                groups[name][rate] = row
    return groups, dict(counts)


def rate_diagnostic(group, reference):
    nominal = float(nearest_rate(reference))
    ranked = sorted((row for row in group.values() if row is not None), key=lambda x: x["score"], reverse=True)
    matching = next((rate for rate in group if abs(rate - nominal) <= 1e-9), None)
    nearest = min(group, key=lambda rate: abs(rate - reference)) if group else None
    candidate = group.get(matching) if matching is not None else None
    rank = next((i for i, row in enumerate(ranked, 1) if abs(row["quarter_bpm"] - nominal) <= 1e-9), None)
    return {"nominal_present": matching is not None, "unique_rate_count": len(group),
            "nearest_rate": nearest, "nearest_absolute_bpm_error": abs(nearest - reference) if nearest is not None else None,
            "nominal_rate_rank": rank, "nominal_best_score": candidate["score"] if candidate else None,
            "leader_minus_nominal_score": ranked[0]["score"] - candidate["score"] if ranked and candidate else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    output = run / "candidate-recovery"
    output.mkdir(exist_ok=False)
    original = run / "original"
    receipt = read_json(original / "inference-receipt.json")
    if "all_families_prepared_at_utc" not in receipt or receipt["reference_files_read"] or receipt["hint_files_read"]:
        raise ValueError("Source-only prediction stage has not finished")
    admission = read_json(run / "admission.json")["rows"]
    inventory = {row["id"]: row for row in read_json(run / "inventory/reference-inventory.json")["rows"]}
    results = []
    oracle_rows = []
    for row in admission:
        ident = row["id"]
        segments, evaluated = target_reference(run, row, inventory)
        if evaluated and row["variant"] != "secondary_rate_only":
            write_json(run / "evaluation-references" / f"{ident}.json", evaluated)
            oracle = {"id": ident, "condition": "ORACLE_SUPPORT_DIAGNOSTIC",
                      "clocks": evaluated["clocks"], "support_and_boundary_hidden": True}
            write_json(run / "oracle-clocks" / f"{ident}.json", oracle)
            oracle_rows.append({"id": ident, "reference_tier": row["reference_tier"], "role": row["role"], "variant": row["variant"]})
        prediction = read_json(original / "predictions/audio_only" / f"{ident}.json")
        try:
            groups, counts = stages(original, ident)
            error = None
        except (OSError, KeyError, ValueError) as exc:
            groups, counts = {key: {} for key in ("broad_bpm_list", "base_scored", "final_family_scored", "retained")}, {}
            error = f"{type(exc).__name__}: {exc}"
        for index, segment in enumerate(segments):
            bpm = segment["quarter_bpm"]
            nominal = float(nearest_rate(bpm))
            relation = prediction.get("quarter_bpm", 0) / bpm if prediction.get("quarter_bpm") else None
            result = {"id": ident, "segment_index": index, "variant": row["variant"], "role": row["role"],
                      "reference_tier": row["reference_tier"], **segment,
                      "nominal_target_bpm": nominal, "representational_error_bpm": nominal - bpm,
                      "representational_drift_ms_over_segment": segment["duration_seconds"] * (bpm / nominal - 1) * 1000,
                      "stage_diagnostics": {name: rate_diagnostic(group, bpm) for name, group in groups.items()},
                      "score_call_counts": counts, "whole_input_top1_bpm": prediction.get("quarter_bpm"),
                      "selected_nominal_match": prediction.get("quarter_bpm") is not None and abs(prediction["quarter_bpm"] - nominal) <= 1e-9,
                      "top1_reference_rate_ratio": relation, "trace_error": error,
                      "clock_phase_recovery_claimed": False}
            if result["stage_diagnostics"]["base_scored"]["nominal_present"] and not result["stage_diagnostics"]["final_family_scored"]["nominal_present"]:
                result["loss_stage"] = "single_base_family_narrowing"
            elif not result["stage_diagnostics"]["base_scored"]["nominal_present"]:
                result["loss_stage"] = "broad_proposal_or_phase_search"
            elif not result["stage_diagnostics"]["retained"]["nominal_present"]:
                result["loss_stage"] = "top_candidate_retention"
            else:
                result["loss_stage"] = None
            results.append(result)
    groups = {"all": results, "primary_real": [r for r in results if r["variant"] == "real_variable"],
              "constructed_variable": [r for r in results if r["variant"] in {"step", "return", "large", "octave", "small", "short_bar", "silent_change"}],
              "secondary_rate_only": [r for r in results if r["variant"] == "secondary_rate_only"]}
    summary = {}
    for name, rows in groups.items():
        summary[name] = {"segment_denominator": len(rows), "stage_nominal_recovery": {
            stage: sum(row["stage_diagnostics"][stage]["nominal_present"] for row in rows)
            for stage in ("broad_bpm_list", "base_scored", "final_family_scored", "retained")},
            "selected_nominal_matches": sum(row["selected_nominal_match"] for row in rows),
            "loss_stages": dict(Counter(row["loss_stage"] for row in rows if row["loss_stage"]))}
    write_json(output / "results.json", {"rows": results, "summary": summary, "reference_opened_after_predictions": True})
    write_json(run / "oracle-admission.json", {"rows": oracle_rows, "oracle_results_are_not_automatic_variable_accuracy": True})
    lines = ["# Original whole-input Candidate Recovery", "", "Rate recovery only; phase and support are not certified.", "",
             "| ID | Segment | Ref BPM | Nominal | Broad | Base | Final family | Retained | Top-1 | Loss |", "| --- | ---: | ---: | ---: | --- | --- | --- | --- | ---: | --- |"]
    for row in results:
        if row["variant"].startswith("fixed"):
            continue
        states = [str(row["stage_diagnostics"][stage]["nominal_present"]) for stage in ("broad_bpm_list", "base_scored", "final_family_scored", "retained")]
        lines.append(f"| {row['id']} | {row['segment_index']} | {row['quarter_bpm']:.6g} | {row['nominal_target_bpm']:.6g} | {' | '.join(states)} | {row['whole_input_top1_bpm']} | {row['loss_stage']} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
