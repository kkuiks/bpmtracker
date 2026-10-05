"""Run source-only variable-bar decoding over the frozen constant quarter grids."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from .bar_sequence import decode_bar_sequence
from .run_constant_grid11 import digest, read_bound, save

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/runs/tempo-meter-v2/primary11-constant-grid-20260927-v1/prediction-manifest.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("prediction output must be new")
    base_manifest = json.loads(BASE.read_text())
    if not base_manifest["complete"] or len(base_manifest["rows"]) != 11:
        raise ValueError("constant-grid source-only inputs are incomplete")
    ledger = {"schema_version": 1, "complete": False,
              "input_manifest_sha256": {"constant_grid": digest(BASE)},
              "implementation_sha256": {name: digest(Path(__file__).with_name(name))
                                        for name in ("bar_sequence.py", "run_bar_sequence11.py")},
              "references_available_to_runner": False,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "rows": []}
    for row in base_manifest["rows"]:
        base = json.loads(read_bound(row["prediction"]).read_text())
        with np.load(read_bound(row["logits"])) as arrays:
            downbeat = arrays["downbeat"]
            fps = float(arrays["fps"])
        official = json.loads(read_bound(row["official"]).read_text())
        observations = (official["methods"]["official"]["prediction"]
                        if "methods" in official else official)
        result = decode_bar_sequence(base, downbeat, fps,
                                     observations["downbeats_seconds"])
        prediction = save(output / "predictions" / (row["id"] + ".json"), result)
        ledger["rows"].append({"id": row["id"], "source": row["source"],
                               "base_prediction": row["prediction"],
                               "logits": row["logits"], "official": row["official"],
                               "prediction": prediction})
        print(row["id"], "meter_changes",
              result["diagnostics"]["bar_sequence"]["selected_meter_changes"], flush=True)
        save(output / "prediction-manifest.json", ledger)
    ledger["complete"] = len(ledger["rows"]) == 11
    ledger["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "prediction-manifest.json", ledger)


if __name__ == "__main__":
    main()
