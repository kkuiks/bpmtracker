"""Extend the late-phrase proposal with an audio-triggered early 14q grammar.

The public notation prior is applied to a frozen 28-candidate acoustic ranking.
Owner maps are not read. This is a known-development exploratory route.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np

from .run_constant_grid11 import digest, read_bound, save

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"analysis_legacy"))
from music_map_contract import prepare_map, render_bars


def select_early_template(evidence: dict, audit: dict) -> tuple[dict, list[int], dict]:
    if (evidence.get("source_only") is not True or evidence.get("reference_read") is not False or
            audit.get("annotation_only") is not True or audit.get("source_audio_acquired") is not False):
        raise ValueError("frozen source-only and annotation-only evidence required")
    starts = evidence["all_eleven_strong_14_runs"][evidence["selected_track_id"]]
    if not starts or starts[0][0] != 0 or not evidence["regions"]:
        raise ValueError("no audio-triggered opening 14-quarter phrase")
    region = evidence["regions"][0]
    if region["pulse_interval"][0] != 0 or len(region["candidates"]) != 28:
        raise ValueError("opening 28-candidate pool required")
    counts = audit["context_distinct_track_counts"]
    count2, count6 = int(counts["2/4"]), int(counts["6/4"])
    probabilities = {2: (count2+1)/(count2+count6+2),
                     6: (count6+1)/(count2+count6+2)}
    candidates = region["candidates"]
    z = np.asarray(region["standardized_columns"], dtype=float)
    if z.shape != (28, 3):
        raise ValueError("three source-only acoustic views required")
    combined = z.sum(axis=1) + np.asarray([
        math.log(probabilities[int(row["exceptional_bar_quarters"])])
        for row in candidates])
    order = np.argsort(-combined)
    chosen = candidates[int(order[0])]
    n = int(chosen["exceptional_bar_quarters"])
    phase = int(chosen["phase_modulo14"])
    if n != 2:
        raise ValueError("selected early grammar is not a short 2/4 insertion")
    lo, hi = region["pulse_interval"]
    exceptional_starts = [q for q in range(lo, hi) if q % 14 == phase and q+n < hi]
    if len(exceptional_starts) < 3 or exceptional_starts[0] != 0:
        raise ValueError("opening phrase lacks three source-supported cycles")
    details = {"selected_index": int(order[0]), "candidate": chosen,
               "combined_score": float(combined[order[0]]),
               "runner_up_score": float(combined[order[1]]),
               "public_prior": {str(k): v for k, v in probabilities.items()},
               "acoustic_score": float(z[order[0]].sum()),
               "phrase_region": [lo, hi]}
    return chosen, exceptional_starts, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--late-manifest", type=Path, required=True)
    parser.add_argument("--fourteen-evidence", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--public-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    late = json.loads(args.late_manifest.read_text())
    evidence = json.loads(args.fourteen_evidence.read_text())
    audit = json.loads(args.public_audit.read_text())
    if (late.get("complete") is not True or len(late.get("rows", [])) != 11 or
            late.get("references_available_to_runner") is not False):
        raise ValueError("frozen source-only eleven-song late proposal required")
    target = evidence["selected_track_id"]
    if late["target_id"] != target:
        raise ValueError("early and late source triggers select different tracks")
    chosen, early_starts, details = select_early_template(evidence, audit)
    selected = next(row for row in late["rows"] if row["id"] == target)
    original = read_bound(selected["prediction"])
    result = deepcopy(json.loads(original.read_text()))
    if digest(args.grid) != evidence["input_sha256"]["grid"]:
        raise ValueError("frozen 14-quarter grid binding changed")
    grid = json.loads(args.grid.read_text())
    if (result["map"]["source"] != selected["source"] or
            result["map"]["source"]["sha256"] !=
            grid["map"]["source"]["sha256"] or
            result["beat_times_seconds"] != grid["beat_times_seconds"]):
        raise ValueError("candidate source clock changed")
    late_diag = result["diagnostics"]["public_meter_prior_pilot"]
    if late_diag["selected_grammar"]["exceptional_bar_quarters"] != 2:
        raise ValueError("late grammar differs from expected 2/4 insertion")
    late_starts = list(late_diag["exceptional_bar_start_pulses"])
    if not late_starts or early_starts[-1]+2 >= late_starts[0]:
        raise ValueError("early and late meter cycles overlap")
    def event(q, numerator):
        return {"pulse": float(q), "numerator": numerator, "denominator": 4,
                "grouping": [1]*numerator, "bar_action": "continue"}
    events = [event(0, 2)]
    for index, start in enumerate(early_starts):
        if index:
            events.append(event(start, 2))
        events.append(event(start+2, 4))
    for start in late_starts:
        events.append(event(start, 2))
        events.append(event(start+2, 4))
    result["map"]["meter_events"] = events
    bars = render_bars(prepare_map(result["map"]))
    if bars["status"] != "rendered":
        raise ValueError("early+late candidate cannot render")
    result["bar_starts_seconds"] = bars["bar_events_seconds"]
    result["diagnostics"]["early_phrase_prior"] = {
        "source_only": True, "reference_read": False,
        "early_exceptional_starts": early_starts, "late_exceptional_starts": late_starts,
        "selection": details,
        "limitation": "same known-development public prior; no calibration or unseen-song claim"}
    output = args.output.resolve()
    output.mkdir(parents=True)
    snapshot = output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    binding = save(output/"predictions"/f"{target}.json", result)
    save(output/"prediction-manifest.json", {
        "schema_version": 1, "complete": True, "references_available_to_runner": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {"late_manifest": digest(args.late_manifest),
                         "fourteen_evidence": digest(args.fourteen_evidence),
                         "grid": digest(args.grid),
                         "public_audit": digest(args.public_audit)},
        "runner_sha256": digest(__file__), "target_id": target,
        "experimental_not_selected": True,
        "rows": [{"id": row["id"], "source": row["source"],
                  "prediction": binding if row["id"] == target else row["prediction"],
                  "selected_input": row["prediction"]} for row in late["rows"]]})
    print(target, "early 14q", chosen["exceptional_bar_quarters"],
          chosen["phase_modulo14"], "cycles", early_starts,
          "late cycles", len(late_starts), flush=True)


if __name__ == "__main__":
    main()
