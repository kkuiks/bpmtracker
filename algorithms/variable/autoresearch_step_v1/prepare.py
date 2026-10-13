"""Freeze a preparation run from explicit, prespecified local inputs."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy

from experiments.beat_event_stability_v1.common import guard as historical_guard
from experiments.multiple_rhythm_continuity_v1.references import normalized
from .common import CONSTANT, HELD, HISTORICAL, MODULE, ROOT, digest, read, stamp, write


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True)
    args = parser.parse_args()
    run, package, parent = args.run.resolve(), args.package.resolve(), args.baseline_run.resolve()
    selected = read(args.selection)
    ids = selected["primary_ids"] + selected["fixed_ids"]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate selected recording")
    historical_guard(parent)
    catalog_path = ROOT / "data/samples/catalog.json"
    catalog = read(catalog_path)
    tracks = {r["id"]: r for r in catalog["tracks"]}
    old_index = {r["original_id"]: r for r in read(parent / "evaluation-index.json")["rows"]}
    old_sources = {r["id"]: r for r in read(parent / "source-inputs.json")["samples"]}
    inventory = read(package / "inventory.json")
    exclusions = read(ROOT / "data/samples/excluded-candidates.json")
    excluded = {r["id"] for r in exclusions["candidates"] if r.get("permanent_exclusion")}
    if set(ids) & excluded:
        raise RuntimeError("Selected an excluded source")
    manifest = read(package / "package_manifest.json")
    for item in manifest["files"]:
        path = package / item["name"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise RuntimeError("Package manifest mismatch: " + item["name"])
    run.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.selection, run / "selection.json")
    inference_files, reference_files, protected_files = {}, {}, {}
    linking, evaluation_rows, missing, audio_identity = [], [], [], []
    for ordinal, ident in enumerate(ids):
        key = f"input{ordinal:03d}"
        track, item = tracks[ident], old_index[ident]
        old_key = item["id"]
        source = old_sources[old_key]
        reference_path = ROOT / "data/samples" / track["reference"]["path"]
        audio_path = ROOT / "data/samples" / track["audio"]["path"]
        history_path = parent / "predictions/L2_DENSE_PROPOSALS/proxy100" / (old_key + ".json")
        prepared_path = parent / "prepared-source" / (old_key + ".json")
        event_path = Path(source["events_path"])
        for path in (reference_path, audio_path, history_path, prepared_path, event_path):
            if not path.is_file():
                missing.append(str(path))
        if missing:
            continue
        if digest(reference_path) != track["reference"]["sha256"]:
            raise RuntimeError("Current catalog reference digest mismatch: " + ident)
        if item["reference_sha256"] != track["reference"]["sha256"]:
            raise RuntimeError("Historical/current reference differs; require explicit new linkage")
        if Path(source["audio_path"]).resolve() != audio_path.resolve():
            raise RuntimeError("Audio linkage differs from catalog: " + ident)
        audio_sha = digest(audio_path)
        if audio_sha != track["audio"]["sha256"] or audio_sha != source["source_audio_sha256"]:
            raise RuntimeError("Source audio identity changed: " + ident)
        reference = normalized(track, read(reference_path))
        if ident in selected["primary_ids"]:
            if len({(s["numerator"], s["denominator"]) for s in reference["states"]}) != 1:
                raise RuntimeError("Primary scope changed meter")
        elif reference["role"] != "fixed_control":
            raise RuntimeError("Prespecified fixed control is no longer fixed")
        prediction = read(history_path)
        directory = run / "source-inputs" / key
        write(directory / "source.json", {"events_path": str(event_path),
                                           "duration_seconds": source["duration_seconds"]})
        shutil.copy2(prepared_path, directory / "prepared.json")
        write(directory / "pinned.json", {
            "initial": prediction.get("initial"), "unit_id": prediction.get("unit_id"),
            "initial_source_origin": prediction.get("initial_source_origin"),
            "adaptive_initial_evidence_end": prediction.get("adaptive_initial_evidence_end")})
        history_target = run / "predictions" / HISTORICAL / (key + ".json")
        history_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(history_path, history_target)
        ref_target = run / "references" / (key + ".json")
        write(ref_target, reference)
        for path in (event_path, directory / "source.json", directory / "prepared.json",
                     directory / "pinned.json"):
            inference_files[str(path)] = digest(path)
        for path in (reference_path, ref_target, history_target, run / "selection.json"):
            reference_files[str(path)] = digest(path)
        for path in (history_path, prepared_path, event_path, reference_path, audio_path):
            protected_files[str(path)] = digest(path) if path != audio_path else audio_sha
        row = {"key": key, "original_id": ident, "historical_id": old_key,
               "title": track["title"], "role": "primary_known_development" if ident in
               selected["primary_ids"] else "fixed_complete_pilot",
               "reference_path": str(ref_target), "canonical_reference_path": str(reference_path),
               "reference_sha256": digest(reference_path), "source": source,
               "pinned_initial": prediction.get("initial"),
               "approved_support": reference["support"],
               "tempo_transitions": len(reference["transitions"]),
               "source_audio_sha256_verified": audio_sha,
               "reference_offset_already_applied": True,
               "reference_additional_offset_applied": 0,
               "historical_prediction": str(history_path),
               "historical_prediction_sha256": digest(history_path),
               "initial_octave_provenance": "Preserved source-fitted L2 proxy100 map; prior discrete-unit proxy, not a fresh tap-free initial estimator.",
               "not_new_holdout": True}
        evaluation_rows.append(row)
        linking.append({k: row[k] for k in ("key", "original_id", "historical_id",
                        "canonical_reference_path", "reference_sha256", "historical_prediction_sha256")})
        audio_identity.append({"key": key, "path": str(audio_path), "sha256": audio_sha,
                               "bytes": audio_path.stat().st_size})
    if missing:
        write(run / "missing-paths.json", {"paths": sorted(set(missing)),
              "effect": "Run cannot start; missing recordings remain selected and in denominators."})
        raise RuntimeError("Missing selected inputs; see missing-paths.json")
    write(run / "evaluation-index.json", {"rows": evaluation_rows})
    write(run / "identity-linkage.json", {"matching": "original_id and exact canonical reference path/hash; no title matching", "rows": linking})
    write(run / "source-audio-identity.json", {"rows": audio_identity, "decoded": False})
    current_inventory = []
    for track in tracks.values():
        path = ROOT / "data/samples" / track["reference"]["path"]
        synthetic = "synthetic" in track["role"]
        auxiliary = track["role"].startswith("auxiliary_")
        ref = normalized(track, read(path)) if not synthetic else None
        current_inventory.append({"id": track["id"], "title": track["title"],
            "catalog_role": track["role"], "normalized_role": ref["role"] if ref else "formal_synthetic",
            "reference_path": "samples/" + track["reference"]["path"],
            "reference_sha256": digest(path), "support": ref["support"] if ref else track.get("reference_support_seconds"),
            "tempo_transitions": len(ref["transitions"]) if ref else None,
            "family_group": track.get("parent_recording_id", track.get("source_parent_id", track["id"])),
            "family_group_status": "Catalog parent when explicit; exact source grouping otherwise. Artist/album independence not certified.",
            "input_kind": "auxiliary_audio" if auxiliary else "synthetic_audio" if ref is None else "original_excerpt_audio" if
                track["role"] == "formal_original_recording_excerpt" else "complete_original_audio",
            "selected_for_preparation": track["id"] in ids,
            "known_development_not_fresh_holdout": True})
    old_inventory = {r["id"]: r for r in inventory["rows"]}
    inventory_diff = [{"id": r["id"], "fields": [k for k in
                      ("reference_path", "reference_sha256", "support", "tempo_transitions")
                      if r[k] != old_inventory[r["id"]].get(k)]}
                      for r in current_inventory if r["id"] in old_inventory]
    write(run / "sample-history.json", {"catalog_snapshot": current_inventory,
        "package_inventory_differences": [r for r in inventory_diff if r["fields"]],
        "existing_feature_only_external_groups": {"count": 98,
            "consumed_in_previous_development": True, "new_holdout": False,
            "reexecuted_in_this_preparation": False},
        "new_independent_evaluation_recordings": [], "generalization_validation_complete": False,
        "no_excerpt_mix_or_augmentation_counted_as_independent_song": True})
    old_freeze = read(parent / "freeze.json")
    original_code = {str(ROOT / rel): sha for rel, sha in old_freeze["code_hashes"].items()}
    inference_code_names = ("__init__.py", "common.py", "core.py", "worker.py")
    for name in inference_code_names:
        inference_files[str(MODULE / name)] = digest(MODULE / name)
    inference_files.update(original_code)
    evaluation_code = dict(original_code)
    # Freeze actual relocated helper source as well as import shims.
    for directory in (ROOT / "experiments", ROOT / "reference"):
        for path in directory.glob("**/*.py"):
            evaluation_code[str(path)] = digest(path)
    for path in MODULE.glob("*.py"):
        evaluation_code[str(path)] = digest(path)
    for path in (catalog_path, package / "objective_spec_draft.json", package / "user_review.json",
                 run / "evaluation-index.json", run / "sample-history.json"):
        reference_files[str(path)] = digest(path)
    write(run / "inference-freeze.json", {"at_utc": stamp(), "files": inference_files,
        "only_source_observations_prepared_candidates_and_pinned_initial": True,
        "historical_guard_preserved": True})
    write(run / "evaluation-freeze.json", {"at_utc": stamp(), "files": {**evaluation_code, **reference_files},
        "objective_version": "reviewed_readings_draft_0.2", "numerical_criteria_owner_approved": False})
    for path in (parent / "freeze.json", parent / "input-freeze.json",
                 parent / "evaluation-index.json", parent / "source-inputs.json",
                 parent / "protocol.json"):
        protected_files[str(path)] = digest(path)
    write(run / "protected-inputs.json", {"files": protected_files})
    for name in ("inference-freeze.json", "evaluation-freeze.json"):
        for path in read(run / name)["files"]:
            path = Path(path)
            if path.suffix == ".py":
                target = run / "code-snapshot" / path.relative_to(ROOT)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
    write(run / "pc-environment.json", {"at_utc": stamp(), "python": sys.version,
        "python_executable": sys.executable, "numpy": np.__version__, "scipy": scipy.__version__,
        "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "source_head": git(ROOT, "rev-parse", "HEAD"),
        "data_head": git(ROOT / "data", "rev-parse", "HEAD"),
        "package_source_versions": read(package / "objective_spec_draft.json")["source_revisions"],
        "source_worktree": git(ROOT, "status", "--porcelain").splitlines(),
        "data_worktree": git(ROOT / "data", "status", "--porcelain").splitlines(),
        "hardware": subprocess.check_output(["lscpu"], text=True),
        "memory": subprocess.check_output(["free", "-h"], text=True),
        "timing_environment": "Sequential source workers, OMP/BLAS/MKL threads=1; one measurement per recording; no neural/PCM recomputation."})
    write(run / "status.json", {"at_utc": stamp(), "state": "frozen_preparation_inputs_ready",
        "selected_recordings": len(ids), "primary_songs": len(selected["primary_ids"]),
        "primary_reference_transitions": sum(r["tempo_transitions"] for r in evaluation_rows
            if r["role"] == "primary_known_development"),
        "new_optimizer_iterations": 0, "next_command": "python -m algorithms.variable.autoresearch_step_v1.run --run " + str(run),
        "numerical_thresholds_owner_approved": False, "app_changed": False})
    print("PREPARED", run, "recordings", len(ids), flush=True)


if __name__ == "__main__":
    main()
