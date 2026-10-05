"""Fit every source-only input before any reference evaluation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .grid import timestamps
from .infer import make_evidence, optimize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    config = json.loads(args.config.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    shutil.copytree(source, args.output / "source-snapshot", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(args.config, args.output / "config.json")
    shutil.copyfile(args.manifest, args.output / "inference-manifest.json")
    (args.output / "predictions").mkdir()
    (args.output / "tempo-maps").mkdir()
    receipt = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
               "configuration_frozen_before_reference_evaluation": True,
               "reference_files_read_by_inference": False, "valid_denominator": len(manifest["samples"]),
               "samples": []}
    for index, row in enumerate(manifest["samples"], 1):
        print(f"FIT {index}/{len(manifest['samples'])} {row['id']}", flush=True)
        start = time.perf_counter()
        try:
            with np.load(args.evidence / (row["id"] + ".npz")) as arrays:
                evidence = make_evidence(arrays["beat_logits"], arrays["downbeat_logits"],
                                         float(arrays["duration_seconds"]), config)
            prediction = optimize(evidence, config)
            prediction["fit_elapsed_seconds"] = time.perf_counter() - start
            prediction["id"] = row["id"]
            (args.output / "predictions" / (row["id"] + ".json")).write_text(
                json.dumps(prediction, indent=2, allow_nan=False) + "\n"
            )
            period = prediction["period_seconds"]
            meter = prediction["time_signature"]["numerator"]
            offset = prediction["offset_seconds"]
            tempo_map = {k: prediction[k] for k in ("id", "status", "quarter_bpm", "bpm_fraction",
                         "period_seconds", "time_signature", "offset_seconds", "offset_convention",
                         "input_duration_seconds", "confidence_flags")}
            tempo_map["quarter_clicks_seconds"] = timestamps(period, offset, evidence["duration"]).tolist()
            tempo_map["downbeats_seconds"] = timestamps(period * meter, offset, evidence["duration"]).tolist()
            (args.output / "tempo-maps" / (row["id"] + ".json")).write_text(
                json.dumps(tempo_map, indent=2, allow_nan=False) + "\n"
            )
            item = {"id": row["id"], "status": "completed", "seconds": prediction["fit_elapsed_seconds"],
                    "quarter_bpm": prediction["quarter_bpm"], "meter": prediction["time_signature"],
                    "offset_seconds": offset, "flags": prediction["confidence_flags"]}
        except Exception as exc:
            item = {"id": row["id"], "status": "failed", "seconds": time.perf_counter() - start,
                    "error": repr(exc)}
        receipt["samples"].append(item)
        (args.output / "inference-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(item), flush=True)
    receipt["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    (args.output / "inference-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
