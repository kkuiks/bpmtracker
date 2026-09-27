"""Evaluate frozen alternate-seed maps after source-only prediction completes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run_constant_grid11 import digest, read_bound, save
from .score_primary8 import _source_geometry, reference_map, score_arm
from .score_primary11 import CATALOG, bar_f1_70ms, change_gate
from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    manifest_path = args.predictions.resolve()
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get("complete") or manifest.get("references_available_to_runner") is not False:
        raise ValueError("complete source-only predictions required")
    catalog = json.loads(CATALOG.read_text())
    tracks = {row["id"]: row for row in catalog["tracks"]}
    results = []
    for row in manifest["rows"]:
        track = tracks[row["id"]]
        source = _source_geometry(track)
        if source != row["source"]:
            raise ValueError("source geometry differs")
        reference = json.loads(read_bound(track["accepted_tempo_map"]).read_text())
        read_bound(track["owner_acceptance"])
        ref_map = reference_map(track, reference, source)
        prediction = json.loads(read_bound(row["segmented"]).read_text())
        events = json.loads(read_bound(row["events"]).read_text())
        score = score_arm(ref_map, prediction, reference["beats_seconds"],
                          minimum_tempo_change_bpm=1e-6)
        gates = {
            "quarter_bpm_time_within_1": score["duration"]["quarter_bpm_within_1_reference_fraction"],
            "reviewed_meter_paired_bar_fraction_70ms": score["reviewed_paired_meter_bar_fraction_at70ms"],
            "declared_quarter_grid_f1_70ms": score["quarter_grid_event_70ms"]["f1"],
            "bar_boundary_f1_70ms": bar_f1_70ms(score),
            "tempo_change_f1_or_no_false_positives_500ms": change_gate(score["tempo_change_500ms"]["full_change_scores"]),
            "meter_change_f1_or_no_false_positives_500ms": change_gate(score["meter_change_500ms"])}
        passed = score["map_render_status"] == "rendered" and all(
            value is not None and value >= .9 for value in gates.values())
        raw_beat = nearest_event_diagnostics(reference["beats_seconds"],
                                              events["beats_seconds"], .07)
        raw_bar = nearest_event_diagnostics(reference["downbeats_seconds"],
                                             events["downbeats_seconds"], .07)
        results.append({"id":row["id"],"checkpoint":row["checkpoint"],
                        "prediction_sha256":row["segmented"]["sha256"],
                        "all_six_at_least_90_percent":passed,"gates":gates,
                        "raw_beat_event_70ms":raw_beat,
                        "raw_bar_event_70ms":raw_bar,
                        "tempo_segment_diagnostic":prediction["diagnostics"]["tempo_segments"]})
        print(row["id"],row["checkpoint"],"pass",passed,
              "raw_bar_f1",round(raw_bar["f1"],4),
              "map_bar_f1",round(gates["bar_boundary_f1_70ms"],4),
              "meter",round(gates["reviewed_meter_paired_bar_fraction_70ms"],4),flush=True)
    args.output.mkdir(parents=True)
    save(args.output / "per-candidate.json", results)
    save(args.output / "summary.json", {
        "schema_version":1,"prediction_manifest_sha256":digest(manifest_path),
        "catalog_sha256":digest(CATALOG),
        "evaluation_source_sha256":digest(Path(__file__)),
        "score_primary11_source_sha256":digest(Path(__file__).with_name("score_primary11.py")),
        "score_primary8_source_sha256":digest(Path(__file__).with_name("score_primary8.py")),
        "candidate_count":len(results),
        "passed_candidates":sum(x["all_six_at_least_90_percent"] for x in results),
        "accuracy_claim_scope":"two previously seen development songs; alternate seeds are diagnostics, no source-only route selector",
        "rows":[{k:r[k] for k in ("id","checkpoint","gates","all_six_at_least_90_percent")}
                for r in results]})


if __name__ == "__main__":
    main()
