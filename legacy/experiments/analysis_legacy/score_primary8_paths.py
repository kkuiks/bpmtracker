"""Rescore frozen automatic paths against the eight owner-approved maps.

Prediction files must already exist. This script never reads references while
choosing a candidate, fits no offset, and does not infer missing meter labels.
Its rankings describe these eight development songs only.
"""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from reanalyze_status_paths import score_methods
from reanalyze_status_refinements import score as score_refinements
from status_reanalysis_metrics import tempo_rate_diagnostics


CATALOG = Path("data/corpus/primary-references-v1/catalog.json")
MAINTENANCE = Path("data/runs/logic-maintenance/2026-09-26-v1")
CORE = MAINTENANCE / "after-correctness/core-paths-v2/predictions"
REFINEMENTS = MAINTENANCE / "after-correctness/refinements/predictions"
BALANCED = MAINTENANCE / "ranking-fixed-pool/predictions"


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def bound(binding):
    path = Path(binding["path"])
    if digest(path) != binding["sha256"]:
        raise ValueError(f"file hash changed: {path}")
    return path


def compact(method, prediction, metrics, clock=None):
    event = {label: metrics[f"event_{label}"] for label in ("10ms", "20ms", "30ms", "70ms")}
    downbeat = {label: metrics.get(f"downbeat_{label}") for label in ("10ms", "20ms", "30ms", "70ms")}
    change = {label: metrics[f"tempo_changes_{label}"] for label in ("100ms", "500ms")}
    rate = metrics.get("rate_diagnostics")
    return {
        "status": method.get("status"),
        "beat_event_count": len(prediction),
        "beats": event,
        "downbeats": downbeat,
        "tempo_map_status": metrics["tempo_map_status"],
        "tempo_change": change,
        "rate_diagnostics": {key: rate.get(key) for key in (
            "status", "covered_duration_fraction", "time_weighted_mae_bpm",
            "half_rate_duration_fraction", "same_rate_duration_fraction",
            "double_rate_duration_fraction", "drift_status"
        )} if rate else None,
        "clock_support_seconds": clock.get("support_seconds") if clock else None,
        "source_span_coverage": metrics.get("source_span_coverage"),
        "pulse_density_diagnostic": metrics.get("pulse_density_diagnostic"),
        "full_tempo_meter_map_status": metrics["full_tempo_meter_map_status"],
    }


def score_track(track, run_dir):
    track_id = track["id"]
    audio = bound(track["canonical_audio"])
    accepted = bound(track["accepted_tempo_map"])
    bound(track["owner_acceptance"])
    reference = read(accepted)
    duration = track["canonical_audio"]["duration_seconds"]
    reference["evaluation_support_seconds"] = [0.0, duration]
    if track["offset"]["additional_offset_to_apply_when_consuming_accepted_map_seconds"] != 0:
        raise ValueError("accepted map requires an unexpected extra shift")
    if track_id == "legacy_circle":
        paths = {"core": run_dir / "circle-replay/core.json",
                 "refinements": run_dir / "circle-replay/refinements.json",
                 "balanced": run_dir / "circle-replay/balanced.json"}
    else:
        paths = {"core": CORE / track_id / "beat_this/predictions.json",
                 "refinements": REFINEMENTS / track_id / "beat_this.json",
                 "balanced": (BALANCED / track_id / "beat_this.json" if
                              (BALANCED / track_id / "beat_this.json").exists() else
                              run_dir / "balanced-replay" / (track_id + ".json"))}
    core, refined, balanced = (read(paths[key]) for key in ("core", "refinements", "balanced"))
    for name, output in (("core", core), ("refinements", refined)):
        if output["id"] != track_id or output["model"] != "beat_this":
            raise ValueError(f"wrong {name} identity for {track_id}")
        if output["source"]["sha256"] != track["canonical_audio"]["sha256"]:
            raise ValueError(f"{name} used a different decoded source: {track_id}")
        if output["references_used_for_prediction"]:
            raise ValueError(f"{name} used a reference during prediction: {track_id}")
    if balanced["id"] != track_id:
        raise ValueError("wrong balanced-path identity")
    balanced_source = balanced.get("source_sha256") or balanced["source"]["sha256"]
    if balanced_source != track["canonical_audio"]["sha256"]:
        raise ValueError(f"balanced path used a different decoded source: {track_id}")
    if balanced.get("references_used_for_prediction", balanced.get("references_used_for_selection")):
        raise ValueError("balanced path used reference labels")

    core_scores = score_methods(reference, core["methods"])
    refinement_scores = score_refinements(reference, refined)
    methods = {}
    for name, method in core["methods"].items():
        clock = method.get("clock")
        if clock:
            core_scores[name]["rate_diagnostics"] = tempo_rate_diagnostics(reference, clock)
        methods[name] = compact(method, method["prediction"]["beats_seconds"], core_scores[name], clock)
        methods[name]["kind"] = "frozen_core"
    for name, method in refined["methods"].items():
        methods[name] = compact(method, method["prediction"], refinement_scores["methods"][name], method.get("clock"))
        methods[name]["kind"] = "frozen_refinement"

    if "method" in balanced:
        candidate = balanced["method"]
        prediction = candidate["prediction"]["beats_seconds"]
        clock = candidate.get("clock")
        changes = tempo_events(clock) if clock else None
        method = candidate
    else:
        selection = balanced["selections"]["balanced_evidence"]
        prediction = selection["prediction"]
        changes = selection["tempo_events"] if selection["candidate_id"] else None
        pool_binding = balanced["candidate_source"]
        pool = read(bound(pool_binding))
        clock = next((item["clock"] for item in pool["candidates"]
                      if item["id"] == selection["candidate_id"]), None)
        if selection["candidate_id"] and clock is None:
            raise ValueError("selected balanced candidate missing from bound pool")
        method = {"status": "unaccepted_balanced_candidate" if selection["candidate_id"] else "empty_candidate_pool"}
    metrics = evaluate_times(reference, prediction, changes, tempo_map_supported=True)
    if clock:
        metrics["rate_diagnostics"] = tempo_rate_diagnostics(reference, clock)
    methods["balanced_candidate"] = compact(method, prediction, metrics, clock)
    methods["balanced_candidate"]["kind"] = "frozen_opt_in_ranking"
    methods["balanced_candidate"]["downbeats"] = {label: None for label in ("10ms", "20ms", "30ms", "70ms")}

    bars = {}
    for name, value in refinement_scores["bars"].items():
        bars[name] = {"downbeat_scores": value["downbeat_scores"],
                      "unsupported_reference_signatures": value["unsupported_reference_signatures"],
                      "full_meter_map_status": value["full_meter_map_status"]}
    return {"id": track_id, "name": track["name"], "source": {"path": str(audio),
            "sha256": track["canonical_audio"]["sha256"], "duration_seconds": duration},
            "reference": {"path": str(accepted), "sha256": track["accepted_tempo_map"]["sha256"],
                          "tier": track["qualification"]["reference_tier"],
                          "beat_count_in_source": sum(0 <= t <= duration for t in reference["beats_seconds"]),
                          "downbeat_count_in_source": sum(0 <= t <= duration for t in reference["downbeats_seconds"]),
                          "tempo_change_count": sum(0 < e["time_seconds"] < duration for a, e in zip(
                              reference["tempo_events"], reference["tempo_events"][1:])
                              if abs(a["bpm_quarter"] - e["bpm_quarter"]) > 1e-8)},
            "prediction_bindings": {key: {"path": str(path), "sha256": digest(path)} for key, path in paths.items()},
            "methods": methods, "bars": bars}


def summarize(rows):
    names = sorted(set.intersection(*(set(row["methods"]) for row in rows)))
    ranking = []
    baseline = {row["id"]: row["methods"]["official"]["beats"]["20ms"]["f1"] for row in rows}
    for name in names:
        values = [row["methods"][name] for row in rows]
        beat20 = [value["beats"]["20ms"]["f1"] for value in values]
        beat70 = [value["beats"]["70ms"]["f1"] for value in values]
        downbeat20 = [value["downbeats"]["20ms"]["f1"] for value in values if value["downbeats"]["20ms"]]
        produced = [value for value in values if value["tempo_map_status"] == "tempo_map_produced"]
        ranking.append({"method": name, "track_count": len(values),
            "beat_20ms_macro_f1": mean(beat20), "beat_70ms_macro_f1": mean(beat70),
            "clock_covered_duration_macro_fraction": mean(
                (value["rate_diagnostics"] or {}).get("covered_duration_fraction") or 0.0 for value in values),
            "quarter_rate_same_fraction_where_mapped": mean([
                value["rate_diagnostics"]["same_rate_duration_fraction"]
                for value in values if value["rate_diagnostics"] and
                value["rate_diagnostics"]["same_rate_duration_fraction"] is not None
            ]) if any(value["rate_diagnostics"] and
                      value["rate_diagnostics"]["same_rate_duration_fraction"] is not None
                      for value in values) else None,
            "downbeat_20ms_macro_f1_where_supported": mean(downbeat20) if downbeat20 else None,
            "downbeat_supported_track_count": len(downbeat20),
            "tempo_maps_produced": len(produced),
            "beat_20ms_improved_tracks_vs_official": sum(value["beats"]["20ms"]["f1"] > baseline[row["id"]] + 1e-12
                for row, value in zip(rows, values)),
            "beat_20ms_regressed_tracks_vs_official": sum(value["beats"]["20ms"]["f1"] < baseline[row["id"]] - 1e-12
                for row, value in zip(rows, values)),
            "tempo_change_500ms_counts": {key: sum((value["tempo_change"]["500ms"].get("full_change_scores") or {}).get(key, 0)
                for value in values) for key in ("true_positives", "false_positives", "false_negatives")}})
    ranking.sort(key=lambda row: row["beat_20ms_macro_f1"], reverse=True)
    return {"method_ranked_by_beat_20ms_macro_f1": ranking,
            "ranking_scope": "eight development references; after-scoring path comparison, not unseen generalization",
            "no_full_tempo_meter_map_from_these_paths": True,
            "no_per_song_oracle_selection": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    catalog = read(CATALOG)
    if catalog["track_count"] != 8 or len(catalog["tracks"]) != 8:
        raise ValueError("expected exactly eight primary references")
    rows = [score_track(track, args.run_dir) for track in catalog["tracks"]]
    directory = args.run_dir / "scoring-v2"
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "per-track.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    report = {"catalog": {"path": str(CATALOG), "sha256": digest(CATALOG)},
              "evaluation_code": {"path": __file__, "sha256": digest(__file__)},
              "source_only_prediction_files_verified": True,
              "accepted_maps_already_source_aligned": True,
              "reference_timing_scope": "owner-reviewed complete songs; not certified original-click millisecond ground truth",
              "ranking": summarize(rows)}
    (directory / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    for item in report["ranking"]["method_ranked_by_beat_20ms_macro_f1"]:
        print(item["method"], f"beat20={item['beat_20ms_macro_f1']:.4f}",
              f"beat70={item['beat_70ms_macro_f1']:.4f}", f"maps={item['tempo_maps_produced']}/8")


if __name__ == "__main__":
    main()
