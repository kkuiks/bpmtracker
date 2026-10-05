"""Score frozen and new source-only predictions on the eight retained references.

This is an evaluation-only bridge to the reviewed v1 music-map contract.  The
prediction runner must finish and freeze its outputs before this script opens a
reference.  The retained references are development material, not an unseen set.
"""

import argparse
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys

import soundfile as sf


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/analysis"))
from grid_metrics import (meter_change_metrics, nearest_event_diagnostics,
                          tempo_change_metrics)
from music_map_contract import interpolate_clock, prepare_map, render_bars
from music_map_metrics import evaluate_music_maps


CATALOG = ROOT / "data/corpus/primary-references-v1/catalog.json"
FROZEN_SCORES = ROOT / "data/runs/primary8-path-comparison/2026-09-27-v1/scoring-v2/per-track.json"
EVALUATION_DEPENDENCIES = ("grid_metrics.py", "music_map_contract.py",
                           "music_map_metrics.py", "musical_units.py")
QUALIFICATION = {"bar_timing": True, "clock_timing": True,
                 "meter": True, "grouping": False}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_bound(binding):
    path = Path(binding["path"])
    if digest(path) != binding["sha256"]:
        raise ValueError(f"bound file changed: {path}")
    return json.loads(path.read_text())


def _source_geometry(track):
    source = track["canonical_audio"]
    if digest(source["path"]) != source["sha256"]:
        raise ValueError(f"approved audio changed: {track['id']}")
    info = sf.info(source["path"])
    if info.samplerate != source["sample_rate"] or not math.isclose(
            info.frames / info.samplerate, source["duration_seconds"], abs_tol=1e-9):
        raise ValueError(f"approved audio sample clock changed: {track['id']}")
    return {"sha256": source["sha256"], "sample_rate": info.samplerate,
            "sample_frames": info.frames}


def reference_map(track, reference, source):
    """Adapt the accepted MIDI/RPP/CPR clock without fitting or shifting it.

    The Naysayer approved clock begins at +30 ms; its preceding 30 ms has no
    declared reference clock and is outside this map scorer's support.
    """
    duration = source["sample_frames"] / source["sample_rate"]
    tempo = reference["tempo_events"]
    knots = []
    used_tempo = []
    for event in tempo:
        t = float(event["time_seconds"])
        if t > duration:
            break
        if knots:
            previous = used_tempo[-1]
            inferred = knots[-1]["pulse"] + (t - knots[-1]["source_seconds"]) * previous["bpm_quarter"] / 60
        else:
            inferred = 0.0
        q = float(event.get("quarter", inferred))
        if knots and (t <= knots[-1]["source_seconds"] or q <= knots[-1]["pulse"]):
            raise ValueError("reference tempo events must advance in seconds and quarters")
        knots.append({"pulse": q, "source_seconds": t})
        used_tempo.append(event)
    if not knots:
        raise ValueError("reference has no clock in source")
    if duration > knots[-1]["source_seconds"]:
        q = knots[-1]["pulse"] + (duration - knots[-1]["source_seconds"]) * used_tempo[-1]["bpm_quarter"] / 60
        knots.append({"pulse": q, "source_seconds": duration})

    def quarter_at(t):
        j = bisect_right([k["source_seconds"] for k in knots], t) - 1
        if j < 0:
            raise ValueError("meter event precedes reference clock")
        return knots[j]["pulse"] + (t - knots[j]["source_seconds"]) * used_tempo[min(j, len(used_tempo)-1)]["bpm_quarter"] / 60

    meters = [{"pulse": float(event.get("quarter", quarter_at(event["time_seconds"]))),
               "numerator": event["numerator"], "denominator": event["denominator"],
               "grouping": event.get("grouping"), "bar_action": event.get("bar_action", "unspecified")}
              for event in reference["meter_events"] if event["time_seconds"] <= duration]
    if not meters:
        raise ValueError("reference lacks in-source meter")
    lo = max(0.0, knots[0]["source_seconds"])
    raw = {"schema_version": 1, "source": source, "clock_knots": knots,
           "quarters_per_pulse": {"numerator": 1, "denominator": 1},
           "bar_anchor_pulse": meters[0]["pulse"], "meter_events": meters,
           "support_seconds": [[lo, duration]], "analysis_condition": "reference",
           "shared_origin_id": None}
    result = prepare_map(raw)
    rendered = render_bars(result)
    if rendered["status"] != "rendered":
        raise ValueError(f"approved reference could not render: {rendered['status']}")
    actual = [t for t in rendered["bar_events_seconds"] if lo - 1e-8 <= t <= duration + 1e-8]
    expected = [t for t in reference["downbeats_seconds"] if lo - 1e-8 <= t <= duration + 1e-8]
    if len(actual) != len(expected) or any(abs(a - b) > 1e-7 for a, b in zip(actual, expected)):
        raise ValueError(f"approved bar parity failed: {track['id']}")
    return result


def quarter_beats(raw):
    if raw is None:
        return []
    value = prepare_map(raw)
    knots = value["clock_knots"]
    if len(knots) < 2:
        return []
    lo = math.ceil(knots[0]["pulse"] - 1e-9)
    hi = math.floor(knots[-1]["pulse"] + 1e-9)
    events = [interpolate_clock(knots, float(q)) for q in range(lo, hi+1)]
    return [t for t in events if any(a - 1e-9 <= t <= b + 1e-9
                                      for a, b in value["support_seconds"])]


def _overlap(left, right):
    output = []
    for a, b in left:
        for c, d in right:
            lo, hi = max(a, c), min(b, d)
            if hi > lo:
                output.append((lo, hi))
    return output


def _rate_segments(value):
    knots = value["clock_knots"]
    return [(a["source_seconds"], b["source_seconds"],
             60 * (b["pulse"]-a["pulse"]) / (b["source_seconds"]-a["source_seconds"]))
            for a, b in zip(knots, knots[1:])]


def _meter_sections(value):
    knots = value["clock_knots"]
    events = value["meter_events"] or []
    times = [interpolate_clock(knots, event["pulse"]) for event in events]
    return [(t, (event["numerator"], event["denominator"])) for t, event in zip(times, events)]


def _step_value(segments, t):
    for lo, hi, value in segments:
        if lo <= t < hi:
            return value
    raise ValueError("time has no declared rate")


def _meter_value(events, t):
    index = bisect_right([row[0] for row in events], t) - 1
    if index < 0:
        raise ValueError("time has no declared meter")
    return events[index][1]


def duration_diagnostics(reference, prediction):
    ref_support = reference["support_seconds"]
    ref_seconds = sum(b-a for a, b in ref_support)
    if prediction is None:
        return {"reference_seconds": ref_seconds, "overlap_seconds": 0.0,
                "coverage_fraction": 0.0, "quarter_bpm_mae_on_overlap": None,
                "quarter_bpm_within_1_reference_fraction": 0.0,
                "exact_meter_reference_fraction": 0.0}
    pred_support = prediction["support_seconds"]
    overlap = _overlap(ref_support, pred_support)
    ref_rates, pred_rates = _rate_segments(reference), _rate_segments(prediction)
    ref_meters, pred_meters = _meter_sections(reference), _meter_sections(prediction)
    duration = error = within = same = 0.0
    for lo, hi in overlap:
        boundaries = {lo, hi}
        boundaries.update(t for a, b, _ in ref_rates + pred_rates for t in (a, b) if lo < t < hi)
        boundaries.update(t for t, _ in ref_meters + pred_meters if lo < t < hi)
        points = sorted(boundaries)
        for a, b in zip(points, points[1:]):
            if b <= a:
                continue
            t = (a+b)/2
            difference = abs(_step_value(ref_rates, t) - _step_value(pred_rates, t))
            span = b-a
            duration += span
            error += span*difference
            within += span*(difference <= 1.0)
            same += span*(_meter_value(ref_meters, t) == _meter_value(pred_meters, t))
    return {"reference_seconds": ref_seconds, "overlap_seconds": duration,
            "coverage_fraction": duration/ref_seconds if ref_seconds else None,
            "quarter_bpm_mae_on_overlap": error/duration if duration else None,
            "quarter_bpm_within_1_reference_fraction": within/ref_seconds if ref_seconds else None,
            "exact_meter_reference_fraction": same/ref_seconds if ref_seconds else None,
            "strict_meter_notation_only": True,
            "reviewed_4_4_8_4_equivalence_scored_separately_on_paired_bars": True}


def _tempo_changes(value, support, *, minimum_change_bpm=0.1):
    rates = _rate_segments(value)
    result = []
    for before, after in zip(rates, rates[1:]):
        t = before[1]
        if support[0][0] < t < support[-1][1] and abs(before[2]-after[2]) > minimum_change_bpm:
            result.append({"source_seconds": t, "bpm_before": before[2],
                           "bpm_after": after[2], "type": "step"})
    return result


def _meter_changes(value, support):
    events = _meter_sections(value)
    result = []
    for previous, current in zip(events, events[1:]):
        if current[1] != previous[1] and support[0][0] < current[0] < support[-1][1]:
            result.append({"source_seconds": current[0], "numerator": current[1][0],
                           "denominator": current[1][1]})
    return result


def score_arm(reference, raw_prediction, reference_beats, frozen_beats=None, *,
              minimum_tempo_change_bpm=0.1):
    candidate = raw_prediction.get("map") if raw_prediction else None
    prepared = None
    error = None
    if candidate is not None:
        try:
            prepared = prepare_map(candidate)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    metrics = evaluate_music_maps(reference, candidate, reference_qualification=QUALIFICATION)
    if metrics["status"] == "blocked_source_identity_or_sample_clock_mismatch":
        prepared = None
        error = metrics["status"]
    support = reference["support_seconds"]
    reference_changes = _tempo_changes(reference, support,
                                       minimum_change_bpm=minimum_tempo_change_bpm)
    reference_meter_changes = _meter_changes(reference, support)
    predicted_changes = (_tempo_changes(prepared, prepared["support_seconds"],
                                       minimum_change_bpm=minimum_tempo_change_bpm)
                         if prepared and prepared["support_seconds"] else [])
    predicted_meter_changes = _meter_changes(prepared, prepared["support_seconds"]) if prepared and prepared["support_seconds"] else []
    tempo_metric = (tempo_change_metrics(reference_changes, predicted_changes,
                                         time_tolerance_seconds=.5, rate_tolerance_bpm=.1)
                    if raw_prediction is not None else {"status": "unsupported_original_map"})
    meter_metric = (meter_change_metrics(reference_meter_changes, predicted_meter_changes,
                                         time_tolerance_seconds=.5)
                    if raw_prediction is not None else {"status": "unsupported_original_map"})
    if raw_prediction is not None and prepared is None:
        tempo_metric["status"] = "failed_no_map"
        meter_metric["status"] = "failed_no_map"
        if not reference_changes:
            for metric in (tempo_metric["full_change_scores"], meter_metric):
                for key in ("precision", "recall", "f1"):
                    metric[key] = None
    beats = frozen_beats if frozen_beats is not None else (raw_prediction.get("beat_times_seconds") if raw_prediction else None)
    if beats is None:
        beats = quarter_beats(prepared) if prepared else []
    physical_duration = reference["duration_seconds"]
    beats = [t for t in beats if 0 <= t <= physical_duration]
    reference_beats = [t for t in reference_beats if 0 <= t <= physical_duration]
    return {"status": raw_prediction.get("status") if raw_prediction else "unsupported_original_map",
            "map_validation_error": error, "map_render_status": metrics["prediction"]["render_status"] if metrics.get("prediction") else None,
            "duration": duration_diagnostics(reference, prepared),
            "beat_event_20ms": nearest_event_diagnostics(reference_beats, beats, .02),
            "beat_event_70ms": nearest_event_diagnostics(reference_beats, beats, .07),
            "quarter_grid_event_20ms": nearest_event_diagnostics(quarter_beats(reference),
                quarter_beats(prepared) if prepared else [], .02),
            "quarter_grid_event_70ms": nearest_event_diagnostics(quarter_beats(reference),
                quarter_beats(prepared) if prepared else [], .07),
            "tempo_change_500ms": tempo_metric,
            "meter_change_500ms": meter_metric,
            "music_map_components": metrics,
            "reviewed_paired_meter_bar_fraction_at70ms": _reviewed_paired_meter_fraction(metrics)}


def _reviewed_paired_meter_fraction(metrics):
    profiles = [p for p in metrics.get("timing_profiles", [])
                if p["tolerance_seconds"] == .07]
    if not profiles:
        return None
    profile = profiles[0]
    denominator = profile["reference_full_or_partial_bar_count"]
    if profile.get("paired_bars") is None:
        return 0.0 if denominator else None
    valid = {"same_written_meter",
             "reviewed_4_4_8_4_allowance_requires_bar_correspondence"}
    correct = sum(item["notation_relation"] in valid
                  for item in profile["paired_bars"]["comparisons"])
    return correct / denominator if denominator else None


def _frozen_beats(value):
    if "method" in value:
        return value["method"]["prediction"]["beats_seconds"]
    return value["selections"]["balanced_evidence"]["prediction"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scoring-name", default="scoring-v2",
                        help="new output directory name; existing scored evidence is never overwritten")
    args = parser.parse_args()
    if not args.scoring_name.startswith("scoring-") or "/" in args.scoring_name or ".." in args.scoring_name:
        raise ValueError("scoring name must be a simple scoring-* directory")
    run_dir = args.run_dir.resolve()
    manifest = json.loads((run_dir / "prediction-manifest.json").read_text())
    if not manifest.get("complete") or len(manifest["rows"]) != 8:
        raise ValueError("eight source-only predictions must finish before scoring")
    catalog = json.loads(CATALOG.read_text())
    if catalog.get("track_count") != 8 or {x["id"] for x in catalog["tracks"]} != {x["id"] for x in manifest["rows"]}:
        raise ValueError("prediction and approved reference sets differ")
    frozen_rows = json.loads(FROZEN_SCORES.read_text())
    frozen_by_id = {item["id"]: item for item in frozen_rows}
    results = []
    for track in catalog["tracks"]:
        row = next(item for item in manifest["rows"] if item["id"] == track["id"])
        source = _source_geometry(track)
        if row["source"] != source:
            raise ValueError(f"prediction and approved source geometry differ: {track['id']}")
        reference = read_bound(track["accepted_tempo_map"])
        read_bound(track["owner_acceptance"])
        adapted = reference_map(track, reference, source)
        frozen = read_bound(row["frozen_balanced"])
        frozen_beats = _frozen_beats(frozen)
        arms = {}
        for name in ("baseline_completed", "joint_sparse"):
            prediction = read_bound(row[name])
            arms[name] = score_arm(adapted, prediction, reference["beats_seconds"])
        arms["frozen_balanced"] = score_arm(adapted, None, reference["beats_seconds"], frozen_beats)
        for label, key in (("20ms", "beat_event_20ms"), ("70ms", "beat_event_70ms")):
            old = frozen_by_id[track["id"]]["methods"]["balanced_candidate"]["beats"][label]["f1"]
            new = arms["frozen_balanced"][key]["f1"]
            if abs(old - new) > 1e-12:
                raise ValueError(f"frozen beat score no longer reproduces: {track['id']} {label}")
        results.append({"id": track["id"], "name": track["name"],
                        "source_sha256": source["sha256"],
                        "accepted_map_sha256": track["accepted_tempo_map"]["sha256"],
                        "reference_support_seconds": adapted["support_seconds"],
                        "reference_tempo_change_count": len(_tempo_changes(adapted, adapted["support_seconds"])),
                        "reference_meter_change_count": len(_meter_changes(adapted, adapted["support_seconds"])),
                        "arms": arms})
    output = run_dir / args.scoring_name
    output.mkdir(exist_ok=False)
    (output / "per-track.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    summary = {"catalog_sha256": digest(CATALOG), "prediction_manifest_sha256": digest(run_dir / "prediction-manifest.json"),
               "evaluation_code_sha256": digest(__file__),
               "evaluation_dependencies_sha256": {name: digest(ROOT / "experiments/analysis" / name)
                                                   for name in EVALUATION_DEPENDENCIES},
               "frozen_score_sha256": digest(FROZEN_SCORES), "reference_scope": "owner-reviewed development songs; not original-click millisecond certification",
               "missing_original_map_is_unsupported_not_zero_accuracy": True, "arms": {}}
    for name in ("frozen_balanced", "baseline_completed", "joint_sparse"):
        values = [item["arms"][name] for item in results]
        summary["arms"][name] = {"map_rendered_tracks": sum(v["map_render_status"] == "rendered" for v in values),
            "mean_reference_coverage_fraction": mean(v["duration"]["coverage_fraction"] for v in values),
            "mean_quarter_bpm_within_1_reference_fraction": mean(v["duration"]["quarter_bpm_within_1_reference_fraction"] for v in values),
            "mean_strict_written_meter_reference_fraction": mean(v["duration"]["exact_meter_reference_fraction"] for v in values),
            "mean_reviewed_paired_meter_bar_fraction_at70ms": mean(v["reviewed_paired_meter_bar_fraction_at70ms"] or 0
                                                                  for v in values),
            "mean_beat_event_f1_20ms": mean(v["beat_event_20ms"]["f1"] for v in values),
            "mean_beat_event_f1_70ms": mean(v["beat_event_70ms"]["f1"] for v in values),
            "mean_declared_quarter_grid_f1_20ms": None if name == "frozen_balanced" else mean(v["quarter_grid_event_20ms"]["f1"] for v in values),
            "mean_declared_quarter_grid_f1_70ms": None if name == "frozen_balanced" else mean(v["quarter_grid_event_70ms"]["f1"] for v in values),
            "tempo_change_500ms_counts": None if name == "frozen_balanced" else {
                key: sum(v["tempo_change_500ms"]["full_change_scores"][key] for v in values)
                for key in ("true_positives", "false_positives", "false_negatives")},
            "meter_change_500ms_counts": None if name == "frozen_balanced" else {
                key: sum(v["meter_change_500ms"][key] for v in values)
                for key in ("true_positives", "false_positives", "false_negatives")}}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps(summary["arms"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
