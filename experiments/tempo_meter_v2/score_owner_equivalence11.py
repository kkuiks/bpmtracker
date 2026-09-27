"""Score the owner-approved source-start notation equivalence on frozen maps.

This keeps the strict authored-notation score intact. Only a declaration whose
preceding bar began before audio support and whose removal leaves every
in-source bar at the same time is optional. Other changes still count as FP/FN.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from .score_observational_equivalence_probe import (
    optional_source_start_changes, revised_meter_metric,
)
from .score_primary11 import CATALOG, bound, change_gate, digest
from .score_primary8 import _meter_changes, _source_geometry, read_bound, reference_map

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import prepare_map


POLICY_ID = "owner-approved-source-start-grid-equivalence-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--strict-per-track", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("accepted score output must be new")
    manifest = json.loads(args.candidate_manifest.read_text())
    catalog = json.loads(CATALOG.read_text())
    strict = json.loads(args.strict_per_track.read_text())
    if (manifest.get("complete") is not True or
            manifest.get("references_available_to_runner") is not False or
            len(manifest.get("rows", [])) != 11 or
            catalog.get("track_count") != 11 or len(strict) != 11):
        raise ValueError("complete frozen eleven-song inputs required")
    by_id = {row["id"]: row for row in manifest["rows"]}
    scored = {row["id"]: row for row in strict}
    if (len(by_id) != 11 or len(scored) != 11 or
            set(by_id) != {row["id"] for row in catalog["tracks"]} or
            set(scored) != set(by_id)):
        raise ValueError("prediction, reference and strict-score identities differ")

    rows = []
    for track in catalog["tracks"]:
        track_id = track["id"]
        source = _source_geometry(track)
        candidate = by_id[track_id]
        if candidate["source"] != source:
            raise ValueError(f"prediction source changed: {track_id}")
        prediction_binding = candidate["prediction"]
        if scored[track_id]["prediction_sha256"] != prediction_binding["sha256"]:
            raise ValueError(f"strict prediction changed: {track_id}")
        reference = reference_map(
            track, read_bound(track["accepted_tempo_map"]), source)
        read_bound(track["owner_acceptance"])
        prediction = prepare_map(bound(
            Path(prediction_binding["path"]), prediction_binding["sha256"])["map"])
        ref_changes = _meter_changes(reference, reference["support_seconds"])
        pred_changes = _meter_changes(prediction, prediction["support_seconds"])
        optional = optional_source_start_changes(reference)
        counts, neutralized = revised_meter_metric(
            ref_changes, pred_changes, optional)
        previous = scored[track_id]
        gates = dict(previous["gates"])
        gates["meter_change_f1_or_no_false_positives_500ms"] = change_gate(counts)
        passed = previous["score"]["map_render_status"] == "rendered" and all(
            value is not None and value >= .9 for value in gates.values())
        rows.append({
            "id": track_id, "name": track["name"],
            "strict_pass": previous["all_six_at_least_90_percent"],
            "approved_policy_pass": passed,
            "gates": gates,
            "false_positive_counts": {
                **previous["false_positive_counts"],
                "meter_changes_500ms": counts["false_positives"]},
            "meter_change_500ms": counts,
            "optional_source_start_events": optional,
            "neutralized_predicted_events": neutralized,
            "prediction_sha256": prediction_binding["sha256"],
            "accepted_map_sha256": track["accepted_tempo_map"]["sha256"],
        })
    output = args.output.resolve()
    output.mkdir(parents=True)
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot / Path(__file__).name)
    result = {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "approved_by_owner_on": "2026-09-27",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "strict_score_preserved": True,
        "candidate_manifest_sha256": digest(args.candidate_manifest),
        "strict_per_track_sha256": digest(args.strict_per_track),
        "catalog_sha256": digest(CATALOG),
        "runner_sha256": digest(__file__),
        "equivalence_helper_sha256": digest(Path(__file__).with_name(
            "score_observational_equivalence_probe.py")),
        "policy": (
            "A source-start written meter change is optional only when its "
            "preceding bar began before audio support, there is no earlier "
            "in-source barline, and removing it leaves the complete in-source "
            "bar schedule identical. At most one exact matching predicted "
            "optional declaration is neutralized. Every other false change "
            "still lowers precision; a constant reference fails on any FP."),
        "scope": "known eleven-song owner-reviewed development corpus",
        "strict_passed": sum(row["strict_pass"] for row in rows),
        "approved_policy_passed": sum(row["approved_policy_pass"] for row in rows),
        "rows": rows,
    }
    (output / "accepted-score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print("strict", result["strict_passed"],
          "approved", result["approved_policy_passed"])
    print("optional", [(row["id"], len(row["optional_source_start_events"]))
                       for row in rows if row["optional_source_start_events"]])


if __name__ == "__main__":
    main()
