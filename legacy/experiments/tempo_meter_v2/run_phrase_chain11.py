"""Render one source-only phrase-chain proposal after evidence is frozen.

This pilot uses an audio-detected 23q section, a 6q continuation, a repeated
2+6+6 section, an opening-motif return, and the prior 22q late section.
Owner maps are opened only by the separate eleven-song scorer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from .run_constant_grid11 import digest, read_bound, save

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"analysis_legacy"))
from music_map_contract import prepare_map, render_bars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--early-late-manifest", type=Path, required=True)
    parser.add_argument("--phrase-chain-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    previous = json.loads(args.early_late_manifest.read_text())
    evidence = json.loads(args.phrase_chain_evidence.read_text())
    if (previous.get("complete") is not True or len(previous.get("rows", [])) != 11 or
            previous.get("references_available_to_runner") is not False or
            evidence.get("source_only") is not True or evidence.get("reference_read") is not False or
            evidence["input_sha256"]["early_late_manifest"] != digest(args.early_late_manifest)):
        raise ValueError("complete source-only prediction and matching frozen evidence required")
    target = evidence["selected_track_id"]
    selected = next(row for row in previous["rows"] if row["id"] == target)
    result = deepcopy(json.loads(read_bound(selected["prediction"]).read_text()))
    if result["map"]["source"] != selected["source"]:
        raise ValueError("candidate source clock changed")
    early = list(evidence["early_short_starts"])
    late = list(evidence["late_short_starts"])
    pair_start, pair_end = evidence["unique_46_quarter_pair"]
    split = evidence["selected_split_quarter"]
    transition = evidence["motif_transfer_start_quarter"]
    if (not early or early[0] != 0 or any(b-a != 14 for a,b in zip(early,early[1:])) or
            not late or any(b-a != 22 for a,b in zip(late,late[1:])) or
            pair_end-pair_start != 46 or
            evidence["motif23_ranked"][0]["phase_modulo23"] != pair_start % 23 or
            not (early[-1]+2 < pair_start < pair_end < split < transition < late[0]) or
            any((stop-start) % 14 for start,stop in ((split,transition),(transition,late[0])))):
        raise ValueError("frozen phrase chain cannot form ordered whole-bar sections")
    if result["diagnostics"]["early_phrase_prior"]["early_exceptional_starts"] != early:
        raise ValueError("early short-bar evidence changed")
    if result["diagnostics"]["public_meter_prior_pilot"]["exceptional_bar_start_pulses"] != late:
        raise ValueError("late short-bar evidence changed")
    def event(q, numerator):
        return {"pulse": float(q), "numerator": numerator, "denominator": 4,
                "grouping": [1]*numerator, "bar_action": "continue"}
    events = [event(0, 2)]
    for index, start in enumerate(early):
        if index:
            events.append(event(start, 2))
        events.append(event(start+2, 4))
    events.append(event(pair_start, 6))
    for start in (pair_start, pair_start+23):
        events.append(event(start+18, 5))
        events.append(event(start+23, 6))
    for start in range(split, transition, 14):
        events.append(event(start, 2))
        events.append(event(start+2, 6))
    for start in range(transition, late[0], 14):
        events.append(event(start, 2))
        events.append(event(start+2, 4))
    for start in late:
        events.append(event(start, 2))
        events.append(event(start+2, 4))
    if any(b["pulse"] <= a["pulse"] for a,b in zip(events,events[1:])):
        raise ValueError("duplicate or descending meter declaration")
    result["map"]["meter_events"] = events
    bars = render_bars(prepare_map(result["map"]))
    if bars["status"] != "rendered":
        raise ValueError("source-only phrase-chain map cannot render")
    result["bar_starts_seconds"] = bars["bar_events_seconds"]
    result["diagnostics"]["phrase_chain"] = {
        "source_only": True, "reference_read": False,
        "evidence_sha256": digest(args.phrase_chain_evidence),
        "sections": {"first_23_quarters": pair_start,
                     "after_two_23_phrases": pair_end,
                     "six_to_two_six_six": split,
                     "opening_motif_return": transition,
                     "late_22_quarter_start": late[0]},
        "limitation": "small acoustic winner margins; developed on known eleven-song cohort"}
    output = args.output.resolve()
    output.mkdir(parents=True)
    snapshot = output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    binding = save(output/"predictions"/f"{target}.json", result)
    save(output/"prediction-manifest.json", {
        "schema_version": 1, "complete": True, "references_available_to_runner": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {"early_late_manifest": digest(args.early_late_manifest),
                         "phrase_chain_evidence": digest(args.phrase_chain_evidence)},
        "runner_sha256": digest(__file__), "target_id": target,
        "experimental_not_selected": True,
        "rows": [{"id": row["id"], "source": row["source"],
                  "prediction": binding if row["id"] == target else row["prediction"],
                  "selected_input": row["prediction"]} for row in previous["rows"]]})
    print(target, "meter changes", len(events)-1,
          "bars", len(result["bar_starts_seconds"]), flush=True)


if __name__ == "__main__":
    main()
