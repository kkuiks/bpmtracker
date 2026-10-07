"""Fixed negative controls with oracle fits and preserved Original proposals."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import numpy as np

from experiments.metronome_reconstruction_v1.hinted import select_from_family
from .common import describe, read_json, write_json
from .support import MATCH, MISMATCH, UNKNOWN, classify, features, load_evidence, runs


def prepare(run, output):
    sources, labels = [], []
    for row in read_json(run / "negative-control-admission.json")["rows"]:
        ref = read_json(row["reference_path"])
        original = read_json(row["original_prediction_path"])
        period = ref["fitted_period_seconds"]
        clocks = [{"clock_id": "annotation_fit_oracle", "quarter_bpm": ref["pulse_bpm"],
                   "period_seconds": period, "phase_seconds": ref["fitted_first_annotation_seconds"] % period}]
        if original.get("period_seconds"):
            clocks.append({"clock_id": "saved_original", "quarter_bpm": original["quarter_bpm"],
                           "period_seconds": original["period_seconds"],
                           "phase_seconds": original["offset_seconds"] % original["period_seconds"]})
        sources.append({"id": row["id"], "role": row["role"], "evidence_path": row["evidence_path"], "clocks": clocks})
        labels.append({"id": row["id"], "support_seconds": [ref["support_seconds"]],
                       "reference_tier": "tier4_approximately_fixed_coarse_annotation"})
    for row in read_json(run / "oracle-admission.json")["rows"]:
        if not row["variant"].startswith("fixed"):
            continue
        ident = row["id"]
        oracle = read_json(run / "oracle-clocks" / f"{ident}.json")["clocks"][0]
        clocks = [{**oracle, "clock_id": "constructed_true_clock_oracle"}]
        original = read_json(run / "original/predictions/audio_only" / f"{ident}.json")
        if ident == "step0_existing_120_1_fixed_probe":
            family = read_json(run / "original/families" / f"{ident}.json")
            original = select_from_family(family, oracle["quarter_bpm"])
            name = "correct_unit_nominal_clock_diagnostic"
        else:
            name = "saved_original"
        clocks.append({"clock_id": name, "quarter_bpm": original["quarter_bpm"],
                       "period_seconds": original["period_seconds"],
                       "phase_seconds": original["offset_seconds"] % original["period_seconds"]})
        sources.append({"id": ident, "role": row["role"], "evidence_path": str(run / "original/evidence" / f"{ident}.npz"), "clocks": clocks})
        labels.append({"id": ident, "support_seconds": read_json(run / "evaluation-references" / f"{ident}.json")["support_seconds"],
                       "reference_tier": row["reference_tier"]})
    write_json(output / "oracle-inputs.json", {"rows": sources, "clock_support_hidden": True,
               "clocks_supplied_as_oracle_diagnostics": True, "reference_change_labels_not_supplied": True,
               "reserved_consumed": 0})
    write_json(output / "evaluation-labels.json", {"rows": labels})


def predict(run, output, model, protocol, names, acoustic_evidence=False):
    inputs = read_json(output / "oracle-inputs.json")["rows"]
    parameters = {name: read_json(run / name / "parameters.json")["parameters"] for name in names}
    receipt = []
    for index, row in enumerate(inputs, 1):
        ident, start = row["id"], time.perf_counter()
        acoustic_path = run / "acoustic-evidence" / f"{ident}.npz"
        evidence = load_evidence(acoustic_path if acoustic_evidence and acoustic_path.exists() else row["evidence_path"], model)
        directory = output / "predictions" / ident
        directory.mkdir(parents=True)
        for clock in row["clocks"]:
            for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
                values = features(evidence, clock, span, .1, model)
                arrays = {"times": values["times"]}
                for name, config in parameters.items():
                    states, alternate = classify(values, clock, config[str(span)])
                    arrays[name + "_states"] = states
                    arrays[name + "_alternate_nominal_evidence"] = alternate
                np.savez_compressed(directory / f"{clock['clock_id']}-span{span}.npz", **arrays)
        receipt.append({"id": ident, "seconds": time.perf_counter() - start, "role": row["role"]})
        if index % 25 == 0 or index == len(inputs):
            print(f"FIXED {index}/{len(inputs)}", flush=True)
        write_json(output / "source-receipt.json", {"rows": receipt, "evaluation_label_files_read": False,
                   "reference_change_locations_supplied": False, "completed": False})
    write_json(output / "source-receipt.json", {"rows": receipt, "evaluation_label_files_read": False,
               "reference_change_locations_supplied": False, "completed": True})


def evaluate(run, output, protocol, names):
    if not read_json(output / "source-receipt.json")["completed"]:
        raise ValueError("Negative-control predictions are incomplete")
    sources = read_json(output / "oracle-inputs.json")["rows"]
    labels = {r["id"]: r for r in read_json(output / "evaluation-labels.json")["rows"]}
    rows = []
    for source in sources:
        ident, label = source["id"], labels[source["id"]]
        for clock in source["clocks"]:
            for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
                with np.load(output / "predictions" / ident / f"{clock['clock_id']}-span{span}.npz") as data:
                    t = data["times"]
                    scored = np.zeros(len(t), dtype=bool)
                    for start, end in label["support_seconds"]:
                        scored |= (t >= start) & (t < end)
                    for name in names:
                        states, alternate = data[name + "_states"], data[name + "_alternate_nominal_evidence"]
                        mismatch = runs((states == MISMATCH) & scored, t, .1)
                        proposals = runs(alternate & scored, t, .1)
                        match = runs((states == MATCH) & scored, t, .1)
                        # A wrong hypothesis everywhere calls for replacement, not
                        # a claim of an internal tempo change. Keep both diagnostics.
                        transitions = [p for p in proposals if any(m["end_seconds"] <= p["start_seconds"] for m in match)]
                        rows.append({"id": ident, "role": source["role"], "reference_tier": label["reference_tier"],
                                     "clock_id": clock["clock_id"], "method": name, "span_quarters": span,
                                     "scored_points": int(scored.sum()),
                                     "coverage": {n: float(np.mean(states[scored] == value)) for n, value in (("MATCH", MATCH), ("MISMATCH", MISMATCH), ("UNKNOWN", UNKNOWN))},
                                     "mismatch_runs": mismatch, "alternate_nominal_rate_runs": proposals,
                                     "match_then_alternate_rate_proposals": transitions,
                                     "mismatch_duration_seconds": describe([r["duration_seconds"] for r in mismatch]),
                                     "actual_piecewise_decoder_run": False})
    groups = {}
    for role in ("development", "already_used_validation", "calibration", "diagnostic"):
        for name in names:
            for condition in ("annotation_fit_oracle", "saved_original", "constructed_true_clock_oracle", "correct_unit_nominal_clock_diagnostic"):
                for span in protocol["support_diagnostic"]["span_quarters_sweep"]:
                    chosen = [r for r in rows if (r["role"], r["method"], r["clock_id"], r["span_quarters"]) == (role, name, condition, span)]
                    if not chosen:
                        continue
                    groups[f"{role}:{name}:{condition}:{span}"] = {"input_denominator": len(chosen),
                        "macro_coverage": {state: float(np.mean([r["coverage"][state] for r in chosen])) for state in ("MATCH", "MISMATCH", "UNKNOWN")},
                        "inputs_with_mismatch": sum(bool(r["mismatch_runs"]) for r in chosen),
                        "inputs_with_alternate_nominal_evidence": sum(bool(r["alternate_nominal_rate_runs"]) for r in chosen),
                        "inputs_with_match_then_alternate_proposal": sum(bool(r["match_then_alternate_rate_proposals"]) for r in chosen),
                        "diagnostic_proposal_run_quarter_counts": {str(length): sum(any(p["duration_seconds"] / (60 / next(c["quarter_bpm"] for s in sources if s["id"] == r["id"] for c in s["clocks"] if c["clock_id"] == r["clock_id"])) >= length
                            for p in r["match_then_alternate_rate_proposals"]) for r in chosen) for length in (0, 4, 8, 16)}}
    write_json(output / "results.json", {"rows": rows, "summary": groups, "gtzan_denominator": 367,
               "reserved_consumed": 0, "no_product_segment_minimum_selected": True,
               "false_proposals_are_diagnostics_not_completed_variable_maps": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "predict", "evaluate"])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-name", default="negative-controls")
    parser.add_argument("--support-names", nargs="+", default=["support", "support-v2", "support-v3"])
    parser.add_argument("--acoustic-evidence", action="store_true")
    args = parser.parse_args()
    run, output = args.run.resolve(), args.run.resolve() / args.output_name
    if args.stage == "prepare":
        output.mkdir(exist_ok=False)
        prepare(run, output)
    else:
        model, protocol = read_json(run / "model-config.json"), read_json(run / "protocol.json")
        if args.stage == "predict":
            predict(run, output, model, protocol, args.support_names, args.acoustic_evidence)
        else:
            evaluate(run, output, protocol, args.support_names)


if __name__ == "__main__":
    main()
