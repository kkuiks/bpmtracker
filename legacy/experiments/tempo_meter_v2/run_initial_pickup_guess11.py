"""Negative control: infer a 2/4 pickup from a one-quarter bar anchor.

This source-only rule is intentionally applied to every qualifying song,
without identifying Sleeping With Sirens or opening references. It tests
whether a blanket notation guess can satisfy the strict false-positive gate.
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
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    base = json.loads(args.base_manifest.read_text())
    if (base.get("complete") is not True or len(base.get("rows", [])) != 11 or
            base.get("references_available_to_runner") is not False):
        raise ValueError("complete source-only eleven-song control required")
    outputs = []
    changed = []
    args.output.mkdir(parents=True)
    snapshot = args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    for row in base["rows"]:
        source = json.loads(read_bound(row["prediction"]).read_text())
        if source["map"]["source"] != row["source"]:
            raise ValueError("prediction source clock changed")
        meter = source["map"]["meter_events"]
        qualified = (source["map"]["bar_anchor_pulse"] == 1.0 and
                     len(meter) == 1 and meter[0]["pulse"] == 0.0 and
                     (meter[0]["numerator"], meter[0]["denominator"]) == (4, 4))
        if qualified:
            result = deepcopy(source)
            result["map"]["meter_events"] = [
                {"pulse": 0.0, "numerator": 2, "denominator": 4,
                 "grouping": [1, 1], "bar_action": "continue"},
                {"pulse": 1.0, "numerator": 4, "denominator": 4,
                 "grouping": [1, 1, 1, 1], "bar_action": "continue"}]
            bars = render_bars(prepare_map(result["map"]))
            if bars["status"] != "rendered":
                raise ValueError("pickup control cannot render")
            result["bar_starts_seconds"] = bars["bar_events_seconds"]
            result["diagnostics"]["initial_pickup_guess_control"] = {
                "source_only": True, "reference_read": False,
                "selection_rule": "one-quarter anchor with a single 4/4 declaration"}
            binding = save(args.output/"predictions"/f"{row['id']}.json", result)
            changed.append(row["id"])
        else:
            binding = row["prediction"]
        outputs.append({"id": row["id"], "source": row["source"],
                        "prediction": binding, "selected_input": row["prediction"]})
    if not changed:
        raise ValueError("no initial one-quarter bars were found")
    save(args.output/"prediction-manifest.json", {
        "schema_version": 1, "complete": True, "references_available_to_runner": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {"base_manifest": digest(args.base_manifest)},
        "runner_sha256": digest(__file__),
        "negative_control_not_selected": True,
        "changed_by_source_rule": changed,
        "rows": outputs})
    print("source-only one-quarter pickup guess", changed, flush=True)


if __name__ == "__main__":
    main()
