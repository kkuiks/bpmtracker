"""Score a frozen source-only eleven-song prediction set against owner-reviewed maps.

The first eight predictions and scores remain frozen. The three added acoustic
predictions must finish before this evaluation-only command reads any reference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from .score_primary8 import _source_geometry, read_bound, reference_map, score_arm


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data/corpus/primary-references-v4/catalog.json"
OLD = ROOT / "data/runs/tempo-meter-v2/2026-09-27-v1"
ADDED = ROOT / "data/runs/tempo-meter-v2/primary11-initial-20260927-v1"
FROZEN_SCORE = OLD / "scoring-v2/per-track.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def bound(path: Path, expected: str) -> dict:
    if digest(path) != expected:
        raise ValueError(f"prediction hash changed: {path}")
    return json.loads(path.read_text())


def bar_f1_70ms(score: dict) -> float:
    profiles = [item for item in score["music_map_components"]["timing_profiles"]
                if item["tolerance_seconds"] == .07]
    if len(profiles) != 1:
        raise ValueError("70 ms map score is unavailable")
    return profiles[0]["bar_boundaries"]["scores"]["f1"]


def change_gate(counts: dict) -> float | None:
    """Penalize false changes, including any false alarm on a constant map."""
    if counts.get("status") in ("unsupported_original_map", "failed_no_map"):
        return None
    true = counts["true_positives"]
    false = counts["false_positives"]
    missed = counts["false_negatives"]
    if true + missed == 0:
        return float(false == 0)
    return counts["f1"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path,
                        help="optional frozen source-only eleven-song prediction manifest")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("scoring output must be new")

    old_manifest_path = OLD / "prediction-manifest.json"
    added_manifest_path = ADDED / "prediction-manifest.json"
    if args.candidate_manifest:
        candidate_path = args.candidate_manifest.resolve()
        candidate = json.loads(candidate_path.read_text())
        if (not candidate.get("complete") or len(candidate.get("rows", [])) != 11 or
                candidate.get("references_available_to_runner") is not False):
            raise ValueError("candidate predictions must be a complete source-only eleven-song run")
        predictions = {row["id"]: row["prediction"] for row in candidate["rows"]}
        prediction_inputs = {"candidate_manifest_sha256": digest(candidate_path)}
    else:
        old_manifest = json.loads(old_manifest_path.read_text())
        added_manifest = json.loads(added_manifest_path.read_text())
        if not old_manifest["complete"] or len(old_manifest["rows"]) != 8:
            raise ValueError("original eight predictions are incomplete")
        if not added_manifest["complete"] or len(added_manifest["rows"]) != 3:
            raise ValueError("three added source-only predictions are incomplete")
        if added_manifest["decoder_sha256"] != old_manifest["implementation"]["decoder.py"]["sha256"]:
            raise ValueError("new cases did not use the frozen decoder")
        predictions = {
            row["id"]: row["joint_sparse"] for row in old_manifest["rows"]
        } | {
            row["id"]: row["prediction"] for row in added_manifest["rows"]
        }
        prediction_inputs = {"old_prediction_manifest_sha256": digest(old_manifest_path),
                             "added_prediction_manifest_sha256": digest(added_manifest_path)}
    if len(predictions) != 11:
        raise ValueError("duplicate source-only prediction identity")

    catalog = json.loads(CATALOG.read_text())
    if catalog["track_count"] != 11 or {row["id"] for row in catalog["tracks"]} != set(predictions):
        raise ValueError("eleven approved reference identities differ from predictions")
    frozen = {row["id"]: row for row in json.loads(FROZEN_SCORE.read_text())}
    if {row["id"] for row in catalog["tracks"][:8]} != set(frozen):
        raise ValueError("frozen eight score identities changed")

    results = []
    for track in catalog["tracks"]:
        source = _source_geometry(track)
        reference = read_bound(track["accepted_tempo_map"])
        read_bound(track["owner_acceptance"])
        ref_map = reference_map(track, reference, source)
        prediction = bound(Path(predictions[track["id"]]["path"]), predictions[track["id"]]["sha256"])
        # The historical primary-eight view ignores <=0.1 BPM differences.
        # For the eleven-song target, every material predicted step is an event:
        # matching tolerance is not an exemption from false-positive counting.
        score = score_arm(ref_map, prediction, reference["beats_seconds"],
                          minimum_tempo_change_bpm=1e-6)
        if not args.candidate_manifest and track["id"] in frozen:
            prior = frozen[track["id"]]["arms"]["joint_sparse"]
            for path in (("duration", "quarter_bpm_within_1_reference_fraction"),
                         ("duration", "exact_meter_reference_fraction"),
                         ("quarter_grid_event_70ms", "f1")):
                a = score[path[0]][path[1]]
                b = prior[path[0]][path[1]]
                if abs(a - b) > 1e-12:
                    raise ValueError(f"frozen eight score changed: {track['id']} {path}")
        bpm = score["duration"]["quarter_bpm_within_1_reference_fraction"]
        meter = score["reviewed_paired_meter_bar_fraction_at70ms"]
        beat = score["quarter_grid_event_70ms"]["f1"]
        bar = bar_f1_70ms(score)
        bar_scores = next(profile for profile in score["music_map_components"]["timing_profiles"]
                          if profile["tolerance_seconds"] == .07)["bar_boundaries"]["scores"]
        tempo_changes = score["tempo_change_500ms"]["full_change_scores"]
        meter_changes = score["meter_change_500ms"]
        false_positive_counts = {
            "quarter_beats_70ms": score["quarter_grid_event_70ms"]["false_positives"],
            "bar_boundaries_70ms": bar_scores["false_positives"],
            "tempo_changes_500ms": tempo_changes["false_positives"],
            "meter_changes_500ms": meter_changes["false_positives"]}
        gates = {"quarter_bpm_time_within_1": bpm,
                 "reviewed_meter_paired_bar_fraction_70ms": meter,
                 "declared_quarter_grid_f1_70ms": beat,
                 "bar_boundary_f1_70ms": bar,
                 "tempo_change_f1_or_no_false_positives_500ms": change_gate(tempo_changes),
                 "meter_change_f1_or_no_false_positives_500ms": change_gate(meter_changes)}
        passed = score["map_render_status"] == "rendered" and all(
            value is not None and value >= .9 for value in gates.values())
        results.append({"id": track["id"], "name": track["name"],
                        "source_sha256": source["sha256"],
                        "accepted_map_sha256": track["accepted_tempo_map"]["sha256"],
                        "prediction_sha256": predictions[track["id"]]["sha256"],
                        "gates": gates, "false_positive_counts": false_positive_counts,
                        "all_six_at_least_90_percent": passed,
                        "strict_written_meter_time_fraction":
                            score["duration"]["exact_meter_reference_fraction"],
                        "coverage_fraction": score["duration"]["coverage_fraction"],
                        "tempo_change_500ms": score["tempo_change_500ms"],
                        "meter_change_500ms": score["meter_change_500ms"],
                        "score": score})
        print(track["id"], "pass" if passed else "fail",
              " ".join(f"{key}={value:.3f}" if value is not None else f"{key}=n/a"
                       for key, value in gates.items()), flush=True)

    output.mkdir(parents=True)
    (output / "per-track.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    keys = tuple(results[0]["gates"])
    summary = {
        "schema_version": 1,
        "catalog_sha256": digest(CATALOG),
        **prediction_inputs,
        "frozen_eight_scores_sha256": digest(FROZEN_SCORE),
        "evaluation_source_sha256": digest(Path(__file__)),
        "target": "Each of 11 known development songs must render a map and pass four map/timing scores and two change-event scores at >=0.9.",
        "time_tolerance_seconds": .07,
        "quarter_bpm_tolerance": "+/-1 BPM, reference-supported time denominator",
        "meter_policy": "reviewed same meter or explicit 4/4-8/4 allowance on paired bars",
        "change_policy": "One-to-one change-event F1 at +/-500ms; a constant reference fails on any false change. Tempo steps above 1e-6 BPM are counted; true matches require rate agreement within 0.1 BPM. Beat/bar F1 penalizes extra events.",
        "accuracy_claim_scope": "known owner-reviewed development songs, not unseen recordings",
        "passed_songs": sum(row["all_six_at_least_90_percent"] for row in results),
        "total_songs": 11,
        "all_songs_pass": all(row["all_six_at_least_90_percent"] for row in results),
        "macro": {key: mean(row["gates"][key] or 0 for row in results) for key in keys},
        "per_song": [{key: row[key] for key in ("id", "gates", "false_positive_counts",
                                                "all_six_at_least_90_percent", "coverage_fraction",
                                                "strict_written_meter_time_fraction")}
                     for row in results],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({"passed_songs": summary["passed_songs"],
                      "all_songs_pass": summary["all_songs_pass"],
                      "macro": summary["macro"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
