"""Select conservative human-readable quarter BPM on a frozen source-only run.

This is an experimental post-processing route. It reads the prediction manifest
and hash-bound predictions, but no owner map, score, or reference labels.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from .plausible_bpm import snap_prediction
from .run_constant_grid11 import digest, read_bound, save


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new source-only output required")
    manifest = json.loads(args.candidate_manifest.read_text())
    if (manifest.get("complete") is not True or
            manifest.get("references_available_to_runner") is not False or
            len(manifest.get("rows", [])) != 11 or
            len({row["id"] for row in manifest["rows"]}) != 11):
        raise ValueError("complete frozen eleven-song prediction manifest required")
    output = args.output.resolve()
    rows = []
    for item in manifest["rows"]:
        original = json.loads(read_bound(item["prediction"]).read_text())
        if original["map"]["source"] != item["source"]:
            raise ValueError(f"source clock mismatch: {item['id']}")
        result, decision = snap_prediction(original)
        binding = (save(output / "predictions" / (item["id"] + ".json"), result)
                   if decision["accepted"] else item["prediction"])
        rows.append({
            "id": item["id"],
            "source": item["source"],
            "prediction": binding,
            "selected_input": item["prediction"],
            "decision": decision,
        })
        print(item["id"], decision["reason"],
              f'{decision["observed_maximum_event_shift_seconds"]*1000:.3f}ms',
              flush=True)
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    for filename in ("run_plausible_bpm11.py", "plausible_bpm.py"):
        shutil.copy2(Path(__file__).with_name(filename), snapshot / filename)
    save(output / "prediction-manifest.json", {
        "schema_version": 1,
        "complete": True,
        "references_available_to_runner": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_manifest_sha256": digest(args.candidate_manifest),
        "runner_sha256": digest(__file__),
        "policy_sha256": digest(Path(__file__).with_name("plausible_bpm.py")),
        "experimental_selected_output": True,
        "rows": rows,
    })
    print("snapped", sum(row["decision"]["accepted"] for row in rows),
          "of", len(rows))


if __name__ == "__main__":
    main()
