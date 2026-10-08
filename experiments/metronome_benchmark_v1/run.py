"""Qualify a prepared BabySlakh batch, predict clocks, and generate a report."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .inference import write_json
from .metrics import aggregate, score
from .references import qualify_dataset
from .report import render


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
MODEL = ROOT / "experiments/metronome_reconstruction_v1"


def prepare_run(args):
    protocol = json.loads(args.protocol.read_text())
    if protocol["absolute_audio_origin_verified"]:
        raise ValueError("This adapter does not establish an independent absolute audio origin")
    rows, references = qualify_dataset(args.data_root.resolve(), protocol)
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.protocol, args.output / "protocol.json")
    shutil.copyfile(args.config, args.output / "model-config.json")
    for row in rows:
        row["role"] = "development_pilot"
    write_json(args.output / "qualification.json", {"schema_version": 1, "rows": rows,
        "qualification_precedes_predictions": True, "manual_judgments": 0})
    fields = ["id", "audio_path", "sample_rate", "sample_frames", "channels", "duration_seconds"]
    source = [{key: row[key] for key in fields} for row in rows if row["eligible"]]
    write_json(args.output / "source-inputs.json", {"schema_version": 1, "samples": source})
    hints = [{"id": row["id"], "initial_quarter_bpm_tap": references[row["id"]]["quarter_bpm"],
              "scope": "initial_section", "origin": "encoded-source-midi-unit-diagnostic"}
             for row in rows if row["eligible"]]
    write_json(args.output / "unit-hints.json", {"schema_version": 1, "samples": hints})
    for ident, reference in references.items():
        write_json(args.output / "references" / f"{ident}.json", reference)
    (args.output / "source-snapshot").mkdir()
    snapshots = {}
    for path in [MODEL / "infer.py", MODEL / "hinted.py", MODEL / "grid.py", args.config]:
        shutil.copyfile(path, args.output / "source-snapshot" / path.name)
        snapshots[str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / "benchmark-snapshot").mkdir()
    for path in PACKAGE.glob("*.py"):
        shutil.copyfile(path, args.output / "benchmark-snapshot" / path.name)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=True).stdout.strip()
    write_json(args.output / "run.json", {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit, "data_root": str(args.data_root.resolve()),
        "model_config_source": str(args.config.resolve()), "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_bytes": args.checkpoint.stat().st_size,
        "frozen_model_sources": snapshots,
        "reference_dependencies": {name: importlib.metadata.version(name) for name in ["mido", "PyYAML"]},
        "parent_group_roles": {row["parent_group"]: "development_pilot" for row in rows if "parent_group" in row},
        "dataset_role": "development_pilot", "reference_unit_hints_are_diagnostic": True,
        "new_training": False, "model_parameters_changed": False})
    print(f"QUALIFY {len(rows)} total; {len(source)} partial-qualified; {dict(Counter(row['status'] for row in rows))}", flush=True)
    return rows, references, protocol


def execute_predictions(args):
    environment = os.environ.copy()
    for name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        environment[name] = "4"
    common = [sys.executable, "-m", "experiments.metronome_benchmark_v1.inference"]
    options = ["--source", str(args.output / "source-inputs.json"), "--config", str(args.config),
               "--checkpoint", str(args.checkpoint), "--output", str(args.output)]
    subprocess.run(common + ["prepare"] + options, cwd=ROOT, env=environment, check=True)
    subprocess.run(common + ["select"] + options + ["--hints", str(args.output / "unit-hints.json")],
                   cwd=ROOT, env=environment, check=True)


def build_results(output, rows, references, protocol):
    for row in rows:
        if not row["eligible"]:
            continue
        row["conditions"] = {}
        for name in protocol["conditions"]:
            path = output / "predictions" / name / f"{row['id']}.json"
            prediction = json.loads(path.read_text()) if path.is_file() else {"status": "inference_failed", "error": "missing_prediction"}
            row["conditions"][name] = {"prediction": prediction,
                "metrics": score(prediction, references[row["id"]], row["duration_seconds"], protocol)}
        row["reference_bpm_encoded"] = references[row["id"]]["quarter_bpm"]
        row["reference_meter_encoded"] = references[row["id"]]["time_signature"]
    summary = aggregate(rows, protocol["conditions"], protocol)
    results = {"schema_version": 1, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
               "protocol": protocol, "summary": summary, "rows": rows}
    write_json(output / "results.json", results)
    write_json(output / "summary.json", summary)
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["id", "status", "reasons", "parent_group", "condition", "reference_bpm_encoded",
                  "predicted_bpm", "bpm_relative_error_percent", "nominal_vocabulary_match",
                  "encoded_meter_match", "rate_implied_drift_ms", "absolute_phase_scored"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if not row["eligible"]:
                writer.writerow({"id": row["id"], "status": row["status"], "reasons": ";".join(row["reasons"]),
                                 "parent_group": row.get("parent_group", "")})
            else:
                for name, data in row["conditions"].items():
                    metrics = data["metrics"]
                    writer.writerow({"id": row["id"], "status": row["status"], "parent_group": row["parent_group"],
                        "condition": name, "reference_bpm_encoded": row["reference_bpm_encoded"],
                        "predicted_bpm": data["prediction"].get("quarter_bpm"),
                        "bpm_relative_error_percent": metrics.get("bpm_relative_error_percent"),
                        "nominal_vocabulary_match": metrics.get("nominal_vocabulary_match"),
                        "encoded_meter_match": metrics.get("encoded_meter_match"),
                        "rate_implied_drift_ms": metrics.get("bpm_implied_drift_ms_over_input"),
                        "absolute_phase_scored": False})
    (output / "report.html").write_text(render(results), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "protocol.json")
    parser.add_argument("--config", type=Path, default=MODEL / "config-tap-v2.json")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "data/models/final0.ckpt")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Continue an incomplete run with identical frozen inputs")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.resume:
        if (args.output / "results.json").exists():
            raise ValueError("Completed runs are immutable; use a new output directory")
        run = json.loads((args.output / "run.json").read_text())
        if str(args.data_root.resolve()) != run["data_root"]:
            raise ValueError("Resume data root differs from the prepared run")
        if args.config.read_bytes() != (args.output / "model-config.json").read_bytes():
            raise ValueError("Resume configuration differs from the prepared run")
        for name in ["infer.py", "hinted.py", "grid.py"]:
            if (MODEL / name).read_bytes() != (args.output / "source-snapshot" / name).read_bytes():
                raise ValueError("The estimator changed after preparation")
        protocol = json.loads((args.output / "protocol.json").read_text())
        rows = json.loads((args.output / "qualification.json").read_text())["rows"]
        references = {row["id"]: json.loads((args.output / "references" / f"{row['id']}.json").read_text())
                      for row in rows if row["eligible"]}
    else:
        rows, references, protocol = prepare_run(args)
    if args.prepare_only:
        return
    execute_predictions(args)
    build_results(args.output, rows, references, protocol)


if __name__ == "__main__":
    main()
