"""Qualification and coarse-label scoring for the published GTZAN features."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from .metrics import clock_error, event_f1, is_clock


SOURCE_FIELDS = ("id", "spectrogram_path", "spectrogram_key", "spectrogram_frames",
                 "mel_bands", "fps", "duration_seconds")


def reference_from_annotations(times, positions, duration, protocol):
    """Use every original timestamp; fit a clock only to assess fixed scope."""
    times = np.asarray(times, dtype=np.float64)
    if times.ndim != 1 or not np.isfinite(times).all() or len(times) < 2:
        raise ValueError("Invalid beat timestamp vector")
    if times[0] < 0 or times[-1] >= duration or np.any(np.diff(times) <= 0):
        raise ValueError("Annotations must increase strictly within feature coverage")
    index = np.arange(len(times), dtype=np.float64)
    centered = index - index.mean()
    period = float(centered @ (times - times.mean()) / (centered @ centered))
    intercept = float(times.mean() - period * index.mean())
    residual = times - (intercept + index * period)
    p95_ms = float(np.quantile(np.abs(residual), .95) * 1000)
    maximum_ms = float(np.max(np.abs(residual)) * 1000)
    bpm = 60 / period
    reasons = []
    if len(times) < protocol["minimum_annotated_beats"] or times[-1] - times[0] < 10:
        reasons.append("insufficient_annotation_support")
    if not protocol["pulse_bpm_range"][0] <= bpm <= protocol["pulse_bpm_range"][1]:
        reasons.append("unsupported_annotated_pulse_bpm")
    if (p95_ms > protocol["fixed_fit_p95_absolute_residual_ms"]
            or maximum_ms > protocol["fixed_fit_maximum_absolute_residual_ms"]):
        reasons.append("annotations_do_not_support_approximately_constant_pulse")
    bar_count, downbeats = None, None
    if positions is not None:
        positions = np.asarray(positions)
        if (positions.shape != times.shape or not np.isfinite(positions).all()
                or not np.equal(positions, np.floor(positions)).all() or np.any(positions < 0)):
            raise ValueError("Invalid annotated bar position vector")
        if np.any(positions > 0):
            bar_count = int(positions.max())
            if bar_count not in protocol["supported_bar_pulse_counts"]:
                reasons.append("unsupported_annotated_bar_pulse_count")
            if (np.any(positions < 1)
                    or np.any(positions[1:] != positions[:-1] % bar_count + 1)):
                reasons.append("inconsistent_or_changing_annotated_bar_positions")
            downbeats = times[positions == 1].tolist()
            if len(downbeats) < protocol["minimum_annotated_downbeats"]:
                reasons.append("insufficient_annotated_downbeats")
    capabilities = ["annotated_pulse_bpm", "coarse_beat_events"]
    if bar_count is not None:
        capabilities += ["annotated_bar_pulse_count", "coarse_downbeat_events"]
    return {
        "kind": "published_audio_aligned_beat_annotation", "capabilities": capabilities,
        "pulse_bpm": bpm, "fitted_period_seconds": period,
        "fitted_first_annotation_seconds": intercept,
        "fixed_fit_p95_absolute_residual_ms": p95_ms,
        "fixed_fit_maximum_absolute_residual_ms": maximum_ms,
        "beat_times_seconds": times.tolist(), "downbeat_times_seconds": downbeats,
        "bar_pulse_count": bar_count,
        "support_seconds": [max(0, float(times[0]) - period / 2),
                            min(duration, float(times[-1]) + period / 2)],
        "source_annotation_unchanged": True, "reference_creation_uses_model_predictions": False,
        "precise_producer_clock_verified": False,
        "notation_denominator_verified": False,
        "quarter_note_interpretation": "annotation pulse used as a quarter only for a diagnostic",
    }, reasons


def group_role(group, protocol):
    value = int(hashlib.sha256(f"{protocol['split_seed']}:{group}".encode()).hexdigest()[:8], 16) % 100
    boundary = 0
    for role, percentage in protocol["split_percentages"].items():
        boundary += percentage
        if value < boundary:
            return role
    raise ValueError("Split percentages do not cover the complete group domain")


def select_pilot(rows, references, protocol, role, limit):
    """Balance declared source strata before predictions without duplicating groups."""
    candidates = sorted((row for row in rows if row["eligible"] and row["role"] == role),
                        key=lambda row: row["id"])
    groups, strata = set(), {}
    for row in candidates:
        if row["parent_group"] in groups:
            continue
        groups.add(row["parent_group"])
        key = (row["genre"], str(references[row["id"]]["bar_pulse_count"]))
        strata.setdefault(key, []).append(row)
    for members in strata.values():
        members.sort(key=lambda row: hashlib.sha256(
            f"{protocol['split_seed']}:pilot:{row['parent_group']}".encode()).hexdigest())
    selected = []
    while any(strata.values()) and (limit == 0 or len(selected) < limit):
        for key in sorted(strata):
            if strata[key] and (limit == 0 or len(selected) < limit):
                selected.append(strata[key].pop(0)["id"])
    return set(selected)


def qualify_dataset(root: Path, protocol: dict):
    info = json.loads((root / "gtzan/info.json").read_text())
    if info.get("has_downbeats") is not True:
        raise ValueError("Unexpected published GTZAN annotation contract")
    bundle_path = (root / "gtzan.npz").resolve()
    rows, references = [], {}
    with np.load(bundle_path, allow_pickle=False) as bundle:
        keys = sorted(key for key in bundle.files if key.endswith("/track"))
        if not keys:
            raise ValueError("No original features in the published bundle")
        for key in keys:
            ident = key.split("/")[0]
            if len(key.split("/")) != 2 or not ident.startswith("gtzan_"):
                raise ValueError("Unexpected original feature identity")
            row = {"id": ident, "status": "data_error", "eligible": False, "reasons": [],
                   "capabilities": [], "data_origin": "published_real_recording_features",
                   "manual_judgments": 0, "artist_independence_verified": False}
            try:
                feature = bundle[key]
                if (feature.ndim != 2 or feature.shape[1] != 128 or feature.dtype != np.float16
                        or not np.isfinite(feature).all()):
                    raise ValueError("Unexpected feature shape, storage precision or values")
                identity = hashlib.sha256(str((feature.shape, feature.dtype.str)).encode()
                                          + feature.tobytes(order="C")).hexdigest()
                group = f"feature:{identity}"
                row.update({"spectrogram_path": str(bundle_path), "spectrogram_key": key,
                            "spectrogram_frames": feature.shape[0], "mel_bands": feature.shape[1],
                            "fps": protocol["fps"], "duration_seconds": feature.shape[0] / protocol["fps"],
                            "parent_group": group, "role": group_role(group, protocol),
                            "feature_sha256": identity, "genre": ident.split("_")[1],
                            "grouping_limit": "Exact feature equality only; recording and artist identity can remain shared."})
                annotation = root / "gtzan/annotations/beats" / f"{ident}.beats"
                if not annotation.is_file():
                    row.update(status="excluded_scope", reasons=["no_published_annotation"])
                else:
                    original = annotation.read_bytes()
                    labels = np.loadtxt(annotation, ndmin=2)
                    if labels.shape[1] not in (1, 2):
                        raise ValueError("Unexpected beat annotation columns")
                    reference, reasons = reference_from_annotations(labels[:, 0],
                        labels[:, 1] if labels.shape[1] == 2 else None, row["duration_seconds"], protocol)
                    if row["duration_seconds"] < protocol["minimum_feature_duration_seconds"]:
                        reasons.append("feature_input_too_short")
                    row.update({"annotation_sha256": hashlib.sha256(original).hexdigest(),
                                "reference_fixed_fit": {key: reference[key] for key in
                                    ["pulse_bpm", "fixed_fit_p95_absolute_residual_ms",
                                     "fixed_fit_maximum_absolute_residual_ms", "bar_pulse_count"]},
                                "reasons": reasons})
                    if reasons:
                        row["status"] = "excluded_scope"
                    else:
                        row.update(status="qualified_coarse", eligible=True,
                                   capabilities=reference["capabilities"])
                        reference.update(id=ident, annotation_version=protocol["annotation_version"],
                                         annotation_sha256=row["annotation_sha256"])
                        references[ident] = reference
            except Exception as exc:
                row["reasons"].append("source_data_error")
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate published source identity")
    return rows, references


def score_annotation(prediction, reference, protocol, *, events_only=False):
    returned = (prediction.get("status") == "event_proposal" if events_only else is_clock(prediction))
    start, end = reference["support_seconds"]
    def in_support(key):
        return [value for value in prediction.get(key, []) if start <= value < end] if returned else []
    beats = in_support("quarter_clicks_seconds")
    downbeats = in_support("downbeats_seconds")
    result = {"returned_prediction": returned, "status": prediction.get("status", "inference_failed"),
              "producer_precision_scored": False,
              "beat_f1": {str(ms): event_f1(beats, reference["beat_times_seconds"], ms / 1000)
                          for ms in protocol["diagnostic_event_tolerances_ms"]},
              "downbeat_f1": {str(ms): event_f1(downbeats, reference["downbeat_times_seconds"], ms / 1000)
                              for ms in protocol["diagnostic_event_tolerances_ms"]}
                             if reference["downbeat_times_seconds"] is not None else None}
    if not returned:
        result["failure"] = prediction.get("error", prediction.get("status", "missing_prediction"))
    if not events_only and returned:
        ratio = prediction["quarter_bpm"] / reference["pulse_bpm"]
        relative = abs(ratio - 1) * 100
        relation = ("within_2_percent" if abs(ratio - 1) <= .02 else
                    "half_rate" if abs(ratio / .5 - 1) <= .02 else
                    "double_rate" if abs(ratio / 2 - 1) <= .02 else "other_rate_error")
        result.update({"pulse_bpm_relative_error_percent": relative,
                       "within_relative_percent": {str(value): relative <= value
                           for value in protocol["bpm_relative_tolerances_percent"]},
                       "bar_pulse_count_match": prediction["time_signature"]["numerator"] == reference["bar_pulse_count"]
                           if reference["bar_pulse_count"] is not None else None,
                       "rate_relation": relation, "confidence_flags": prediction.get("confidence_flags", []),
                       "pulse_clock_error_against_annotations": clock_error(reference["beat_times_seconds"],
                           prediction["period_seconds"], prediction["offset_seconds"])})
    return result


def aggregate_annotations(rows, references, protocol, selected_role):
    eligible = [row for row in rows if row["eligible"]]
    selected = [row for row in rows if row.get("selected_for_inference")]
    summary = {"catalog_count": len(rows), "qualified_count": len(eligible),
               "selected_count": len(selected), "selected_role": selected_role,
               "excluded_count": sum(row["status"] == "excluded_scope" for row in rows),
               "source_error_count": sum(row["status"] == "data_error" for row in rows),
               "qualified_by_role": dict(Counter(row["role"] for row in eligible)),
               "selected_genres": dict(Counter(row["genre"] for row in selected)),
               "qualified_bar_pulse_counts": dict(Counter(str(references[row["id"]]["bar_pulse_count"]) for row in eligible)),
               "selected_bar_pulse_counts": dict(Counter(str(references[row["id"]]["bar_pulse_count"]) for row in selected)),
               "selected_unique_exact_feature_groups": len({row["parent_group"] for row in selected}),
               "manual_judgments": 0, "producer_precision_scored": False,
               "artist_independence_verified": False, "reserved_is_final_locked_test": False,
               "conditions": {}}
    for name in protocol["conditions"]:
        scores = [row["conditions"][name]["metrics"] for row in selected]
        returned = [value for value in scores if value["returned_prediction"]]
        value = {"selected_denominator": len(scores), "returned_predictions": len(returned),
                 "failed_or_abstained": len(scores) - len(returned)}
        for channel in ("beat", "downbeat"):
            supported = [score for score in scores if score[channel + "_f1"] is not None]
            value[channel + "_denominator"] = len(supported)
            value[channel + "_macro_f1"] = {str(ms): float(np.mean([score[channel + "_f1"][str(ms)]["f1"]
                for score in supported])) if supported else None for ms in protocol["diagnostic_event_tolerances_ms"]}
            value[channel + "_micro_f1"] = {}
            for ms in protocol["diagnostic_event_tolerances_ms"]:
                counts = {key: sum(score[channel + "_f1"][str(ms)][key] for score in supported)
                          for key in ("tp", "fp", "fn")}
                denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
                value[channel + "_micro_f1"][str(ms)] = {**counts,
                    "f1": 2 * counts["tp"] / denominator if denominator else 0.0}
        if name != "beat_this_events":
            value.update({"pulse_bpm_denominator": len(scores),
                "bpm_within_relative_percent": {str(tol): sum(score["within_relative_percent"][str(tol)] for score in returned)
                                                for tol in protocol["bpm_relative_tolerances_percent"]},
                "bar_pulse_count_denominator": sum(references[row["id"]]["bar_pulse_count"] is not None for row in selected),
                "bar_pulse_count_matches": sum(score.get("bar_pulse_count_match") is True for score in returned),
                "rate_relations": dict(Counter(score["rate_relation"] for score in returned))})
        summary["conditions"][name] = value
    return summary
