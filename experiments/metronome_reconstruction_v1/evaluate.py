"""Evaluation-only reference adapters and transparent grid metrics."""

import numpy as np

from .grid import match_events, restrict, timestamps


def reference_events(ref: dict, support: list[list[float]]):
    # Existing accepted audio-relative events are used, never re-rendered from
    # original MIDI, nominal BPM, alignment offset, or source project timestamps.
    if "beats_seconds" in ref:
        beat = np.asarray(ref["beats_seconds"], dtype=np.float64)
    elif "beat_times_seconds" in ref:
        beat = np.asarray(ref["beat_times_seconds"], dtype=np.float64)
    else:
        beat = np.asarray([event["master_seconds"] for event in ref["quarter_events"]], dtype=np.float64)
    if "downbeats_seconds" in ref:
        downbeat = np.asarray(ref["downbeats_seconds"], dtype=np.float64)
    elif "bar_starts_seconds" in ref:
        downbeat = np.asarray(ref["bar_starts_seconds"], dtype=np.float64)
    elif "bar_events" in ref:
        downbeat = np.asarray([event["master_seconds"] for event in ref["bar_events"]], dtype=np.float64)
    else:
        downbeat = np.asarray([event["master_seconds"] for event in ref["quarter_events"]
                               if event.get("accent") or event.get("bar_start")], dtype=np.float64)
    return np.sort(restrict(beat, support)), np.sort(restrict(downbeat, support))


def event_metrics(predicted, reference, tolerances):
    results = {}
    for tolerance in tolerances:
        pi, ri = match_events(predicted, reference, tolerance)
        count = len(pi)
        precision = count / len(predicted) if len(predicted) else 0.0
        recall = count / len(reference) if len(reference) else 0.0
        results[str(int(round(tolerance * 1000)))] = {
            "tp": count, "fp": len(predicted) - count, "fn": len(reference) - count,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
    pi, ri = match_events(predicted, reference, max(tolerances))
    residual = predicted[pi] - reference[ri]
    timing = {"matched_count": len(residual), "predicted_count": len(predicted),
              "reference_count": len(reference), "conditioned_on_matching_within_max_tolerance": True,
              "median_absolute_error_ms": float(np.median(np.abs(residual)) * 1000) if len(residual) else None,
              "p95_absolute_error_ms": float(np.quantile(np.abs(residual), 0.95) * 1000) if len(residual) else None}
    return {"tolerances_ms": results, "matched_event_timing": timing}


def paired_clock_errors(reference, reference_period, predicted_period, offset):
    """Keep quarter/bar index correspondence: do not wrap away BPM drift."""
    if not len(reference):
        return {}, np.empty(0)
    phase = offset % predicted_period
    first_index = int(np.rint((reference[0] - phase) / predicted_period))
    indices = np.rint((reference - reference[0]) / reference_period).astype(int)
    predicted = phase + (first_index + indices) * predicted_period
    error = predicted - reference
    centered = reference - np.mean(reference)
    slope = float(np.dot(centered, error - np.mean(error)) / np.dot(centered, centered)) if len(reference) > 1 else None
    return {
        "median_absolute_error_ms": float(np.median(np.abs(error)) * 1000),
        "p95_absolute_error_ms": float(np.quantile(np.abs(error), 0.95) * 1000),
        "max_absolute_error_ms": float(np.max(np.abs(error)) * 1000),
        "initial_phase_error_ms": float(error[0] * 1000),
        "final_phase_error_ms": float(error[-1] * 1000),
        "accumulated_drift_ms": float((error[-1] - error[0]) * 1000),
        "residual_slope_seconds_per_second": slope,
        "same_quarter_or_bar_index_pairing": True,
    }, error


def score_map(prediction, beat_ref, down_ref, metadata, config):
    support = metadata["reference_support_seconds"]
    duration = metadata["duration_seconds"]
    ref_bpm = metadata["reference_quarter_bpm_values_exact_as_stored"][0]
    ref_meter = metadata["reference_meter_values"][0]
    period = prediction["period_seconds"]
    meter = prediction["time_signature"]["numerator"]
    offset = prediction["offset_seconds"]
    beats = restrict(timestamps(period, offset, duration), support)
    downbeats = restrict(timestamps(period * meter, offset, duration), support)
    quarter_clock, quarter_error = paired_clock_errors(beat_ref, 60 / ref_bpm, period, offset)
    bar_clock, bar_error = paired_clock_errors(down_ref, 60 / ref_bpm * ref_meter["numerator"], period * meter, offset)
    metrics = {
        "bpm_absolute_error": abs(prediction["quarter_bpm"] - ref_bpm),
        "bpm_relative_error": abs(prediction["quarter_bpm"] - ref_bpm) / ref_bpm,
        "time_signature_exact_match": prediction["time_signature"] == ref_meter,
        "quarter_events": event_metrics(beats, beat_ref, config["evaluation_tolerances_seconds"]),
        "downbeat_events": event_metrics(downbeats, down_ref, config["evaluation_tolerances_seconds"]),
        "paired_quarter_clock": quarter_clock, "paired_bar_clock": bar_clock,
    }
    return metrics, beats, downbeats, quarter_error, bar_error


def regression_baseline(beats, downbeats, duration, config):
    if len(beats) < 2:
        return None
    indices = np.arange(len(beats), dtype=float)
    period, intercept = np.linalg.lstsq(np.column_stack([indices, np.ones(len(indices))]), beats, rcond=None)[0]
    if period <= 0:
        return None
    if len(downbeats) >= 2:
        nearest = np.searchsorted(beats, downbeats)
        nearest = np.clip(nearest, 0, len(beats) - 1)
        left = np.maximum(nearest - 1, 0)
        nearest = np.where(abs(beats[left] - downbeats) < abs(beats[nearest] - downbeats), left, nearest)
        differences = np.diff(nearest)
        meter = min(config["meters"], key=lambda value: float(np.mean(np.abs(differences - value))))
        downbeat_index = int(np.rint(np.median(nearest % meter))) % meter
    else:
        meter, downbeat_index = config["meters"][-1], 0
    return {"quarter_bpm": float(60 / period), "period_seconds": float(period),
            "time_signature": {"numerator": int(meter), "denominator": 4},
            "offset_seconds": float((intercept + downbeat_index * period) % (period * meter)),
            "status": "consecutive_official_event_regression_baseline"}
