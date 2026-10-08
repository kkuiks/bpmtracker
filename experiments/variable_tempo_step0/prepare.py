"""Freeze admission and source-only inputs before running Original."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from tools.project_storage import resolve_path
import shutil
import subprocess

from .common import PACKAGE, ROOT, SAMPLES, digest, read_json, source_row, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--owner-request", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    if (run / "protocol.json").exists():
        raise ValueError("The protocol/admission freeze must be new")
    inventory = read_json(run / "inventory/reference-inventory.json")
    protocol = read_json(PACKAGE / "protocol.json")
    corpus = run / "corpus"
    sources = read_json(corpus / "source-inputs.json")["samples"]
    admitted = read_json(corpus / "admission.json")["rows"]
    rows = {row["id"]: row for row in inventory["rows"]}
    for ident in protocol["primary_real_ids"] + protocol["secondary_rate_only_ids"]:
        row = rows[ident]
        if ident in protocol["primary_real_ids"] and row["meters"] != [{"numerator": 4, "denominator": 4}]:
            raise ValueError("A primary real recording violates the frozen fixed-4/4 scope")
        path = resolve_path(row["audio_path"])
        path = path if path.is_absolute() else SAMPLES / path
        sources.append(source_row(ident, path))
        admitted.append({"id": ident, "variant": "real_variable" if ident in protocol["primary_real_ids"] else "secondary_rate_only",
                         "parent_group": ident, "role": "real_development_diagnostic",
                         "reference_path": str((SAMPLES / row["reference_path"]).resolve()) if "reference_path" in row else None,
                         "support_seconds": row.get("support_seconds"),
                         "reference_tier": row["reference_tier"], "inventory_id": ident})
    # An existing vocabulary probe is a separate fixed robustness diagnostic.
    fixed_root = SAMPLES / "external/generated-clock-contrast-v1"
    probe = next(row for row in read_json(fixed_root / "source-inputs.json")["samples"] if row["id"] == "control_long1")
    probe = {**probe, "id": "step0_existing_120_1_fixed_probe"}
    sources.append(probe)
    admitted.append({"id": probe["id"], "variant": "fixed_vocabulary_probe", "role": "diagnostic",
                     "parent_group": "existing_fixed_composition:4201",
                     "reference_path": str(fixed_root / "references/control_long1.json"),
                     "reference_tier": "tier1_exact_constructed_transport", "support_seconds": [[0, probe["duration_seconds"]]]})
    from experiments.metronome_benchmark_v1.inference import validate_source
    validate_source(sources)
    write_json(run / "source-inputs.json", {"schema_version": 1, "samples": sources})
    write_json(run / "admission.json", {"schema_version": 1, "rows": admitted,
               "frozen_before_predictions": True, "failed_samples_will_remain": True,
               "synthetic_parent_group_count": 3, "primary_real_count": 3, "secondary_count": 2})
    shutil.copyfile(PACKAGE / "protocol.json", run / "protocol.json")
    model = ROOT / "experiments/metronome_reconstruction_v1"
    shutil.copyfile(model / "config-tap-v2.json", run / "model-config.json")
    snapshot = run / "original-source-snapshot"
    snapshot.mkdir()
    files = [model / name for name in ("infer.py", "hinted.py", "grid.py", "config-tap-v2.json")]
    baseline = SAMPLES / "experiments/metronome_benchmark_v1/20261007-gtzan-development280-frozen-v1/source-snapshot"
    correspondence = {}
    for path in files:
        shutil.copyfile(path, snapshot / path.name)
        correspondence[path.name] = {"current_sha256": digest(path), "baseline_sha256": digest(baseline / path.name),
                                     "matches_frozen_fixed_baseline": digest(path) == digest(baseline / path.name)}
    if not all(row["matches_frozen_fixed_baseline"] for row in correspondence.values()):
        raise ValueError("Original differs from the frozen fixed baseline")
    context = run / "context"
    context.mkdir()
    for path, name in ((args.handoff, "owner-approved-handoff.md"), (args.owner_request, "owner-request.txt")):
        if path:
            shutil.copyfile(path, context / name)
    negatives = []
    for role, name, expected in (("development", "20261007-gtzan-development280-frozen-v1", 280),
                                 ("already_used_validation", "20261007-gtzan-validation87-frozen-v1", 87)):
        original = SAMPLES / "experiments/metronome_benchmark_v1" / name
        original_sources = read_json(original / "source-inputs.json")["samples"]
        if len(original_sources) != expected:
            raise ValueError("Frozen fixed negative-control denominator differs")
        for source in original_sources:
            ident = source["id"]
            negatives.append({"id": ident, "role": role, "duration_seconds": source["duration_seconds"],
                              "evidence_path": str(original / "evidence" / f"{ident}.npz"),
                              "reference_path": str(original / "references" / f"{ident}.json"),
                              "original_prediction_path": str(original / "predictions/audio_only" / f"{ident}.json")})
    write_json(run / "negative-control-admission.json", {"rows": negatives, "count": 367,
               "reserved_consumed": 0, "neural_inference_will_not_be_repeated": True,
               "hypotheses_are_oracle_annotation_fit_and_saved_original_prediction": True})
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    write_json(run / "run.json", {"source_commit": head, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
               "original_correspondence": correspondence, "source_count": len(sources),
               "automatic_condition": "audio_only_original_unchanged", "initial_tap_used": False,
               "reference_data_is_not_in_source_manifest": True, "reserved_inference": False,
               "whole_input_candidate_recovery_precedes_local_proposal_design": True})
    print({"frozen_sources": len(sources), "negative_controls": len(negatives), "baseline_unchanged": True})


if __name__ == "__main__":
    main()
