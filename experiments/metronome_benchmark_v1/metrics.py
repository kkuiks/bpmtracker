"""Capability-aware scoring; source-origin assumptions stay diagnostic."""

from __future__ import annotations

from fractions import Fraction
import math

import numpy as np


def event_f1(predicted, reference, tolerance):
    p, r = sorted(predicted), sorted(reference)
    i = j = matches = 0
    while i < len(p) and j < len(r):
        difference = p[i] - r[j]
        if difference < -tolerance - 1e-12:
            i += 1
        elif difference > tolerance + 1e-12:
            j += 1
        else:
            matches += 1
            i += 1
            j += 1
    precision = matches / len(p) if p else 0.0
    recall = matches / len(r) if r else 0.0
    return {"tp": matches, "fp": len(p) - matches, "fn": len(r) - matches,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def clock_error(reference_events, period, phase):
    if not reference_events:
        return None
    reference = np.asarray(reference_events, dtype=np.float64)
    phase %= period
    first_index = round((reference[0] - phase) / period)
    # One initial index choice; preserve the progression instead of repeatedly
    # wrapping individual errors into a beat period and erasing drift.
    predicted = phase + (first_index + np.arange(len(reference))) * period
    error = (predicted - reference) * 1000
    return {"median_absolute_ms": float(np.median(abs(error))),
            "p95_absolute_ms": float(np.quantile(abs(error), .95)),
            "maximum_absolute_ms": float(np.max(abs(error))),
            "initial_signed_ms": float(error[0]), "final_signed_ms": float(error[-1]),
            "accumulated_drift_ms": float(error[-1] - error[0])}


def is_clock(prediction):
    values = [prediction.get("quarter_bpm"), prediction.get("period_seconds"), prediction.get("offset_seconds")]
    return (all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
            and values[0] > 0 and values[1] > 0
            and isinstance(prediction.get("time_signature"), dict))


def score(prediction, reference, duration, protocol):
    result = {"returned_clock": is_clock(prediction),
              "prediction_status": prediction.get("status", "failed"),
              "absolute_phase": {"scored": False, "reason": "independent_audio_origin_unavailable"}}
    if not result["returned_clock"]:
        result["failure"] = prediction.get("error", prediction.get("status", "no_clock"))
        return result
    bpm = prediction["quarter_bpm"]
    expected = reference["quarter_bpm"]
    relative = abs(bpm / expected - 1) * 100
    nearest = Fraction(reference["quarter_bpm_fraction"]["numerator"],
                       reference["quarter_bpm_fraction"]["denominator"]).limit_denominator(4)
    period_difference = prediction["period_seconds"] / reference["period_seconds"] - 1
    ratio = bpm / expected
    relation = ("within_2_percent" if abs(ratio - 1) <= .02 else
                "half_rate" if abs(ratio / .5 - 1) <= .02 else
                "double_rate" if abs(ratio / 2 - 1) <= .02 else "other_rate_error")
    flags = prediction.get("confidence_flags", [])
    result.update({"bpm_absolute_error": abs(bpm - expected), "bpm_relative_error_percent": relative,
                   "within_relative_percent": {str(value): relative <= value for value in protocol["bpm_relative_tolerances_percent"]},
                   "nearest_allowed_reference_bpm_display_only": float(nearest),
                   "nominal_vocabulary_match": abs(bpm - float(nearest)) < 1e-9,
                   "candidate_vocabulary_minimum_bpm_error": abs(float(nearest) - expected),
                   "bpm_implied_drift_ms_over_input": period_difference * duration * 1000,
                   "drift_is_rate_implied_not_observed_alignment": True,
                   "rate_relation": relation, "confidence_flags": flags,
                   "unflagged_rate_error": relation != "within_2_percent" and not flags,
                   "encoded_meter_match": prediction["time_signature"] == reference["time_signature"] if reference["time_signature"] is not None else None})
    start, end = reference["source_support_seconds"]
    quarter = [time for time in prediction.get("quarter_clicks_seconds", []) if start <= time < end]
    downbeat = [time for time in prediction.get("downbeats_seconds", []) if start <= time < end]
    diagnostic = {
        "assumed_audio_offset_seconds": 0,
        "independent_audio_origin_verified": False,
        "interpretation": "Conditional source-tick-zero to audio-zero projection; excluded from absolute-phase accuracy.",
        "quarter_clock": clock_error(reference["quarter_source_seconds"], prediction["period_seconds"], prediction["offset_seconds"]),
        "quarter_f1": {str(value): event_f1(quarter, reference["quarter_source_seconds"], value / 1000)
                       for value in protocol["diagnostic_event_tolerances_ms"]},
    }
    if reference["downbeat_source_seconds"] is not None:
        signature = prediction["time_signature"]
        diagnostic["bar_clock"] = clock_error(reference["downbeat_source_seconds"],
            prediction["period_seconds"] * signature["numerator"] * 4 / signature["denominator"], prediction["offset_seconds"])
        diagnostic["downbeat_f1"] = {str(value): event_f1(downbeat, reference["downbeat_source_seconds"], value / 1000)
                                    for value in protocol["diagnostic_event_tolerances_ms"]}
    result["declared_origin_diagnostic"] = diagnostic
    return result


def aggregate(rows, conditions, protocol):
    eligible = [row for row in rows if row["eligible"]]
    summary = {"catalog_count": len(rows), "qualified_count": len(eligible),
               "excluded_count": sum(row["status"] == "excluded_scope" for row in rows),
               "source_error_count": sum(row["status"] == "data_error" for row in rows),
               "unique_parent_groups": len({row["parent_group"] for row in eligible}),
               "all_samples_role": "development_pilot", "manual_judgments": 0,
               "absolute_phase_qualified_count": 0, "absolute_phase_accuracy": None,
               "absolute_phase_unscored_reason": "Independent source-to-audio origin is unavailable in this pilot.",
               "conditions": {}}
    for name in conditions:
        scored = [row["conditions"][name]["metrics"] for row in eligible]
        maps = [value for value in scored if value["returned_clock"]]
        meter_rows = [value for value in maps if value.get("encoded_meter_match") is not None]
        meter_denominator = sum("encoded_meter" in row["capabilities"] for row in eligible)
        summary["conditions"][name] = {
            "qualified_denominator": len(eligible), "returned_clocks": len(maps),
            "failed_or_abstained": len(eligible) - len(maps),
            "nominal_vocabulary_matches": sum(value["nominal_vocabulary_match"] for value in maps),
            "bpm_within_relative_percent": {str(tolerance): sum(value["within_relative_percent"][str(tolerance)] for value in maps)
                                          for tolerance in protocol["bpm_relative_tolerances_percent"]},
            "encoded_meter_denominator": meter_denominator,
            "encoded_meter_matches": sum(value["encoded_meter_match"] for value in meter_rows),
            "rate_relations": {relation: sum(value["rate_relation"] == relation for value in maps)
                               for relation in ["within_2_percent", "half_rate", "double_rate", "other_rate_error"]},
            "unflagged_rate_errors": sum(value["unflagged_rate_error"] for value in maps),
            "median_bpm_relative_error_percent_returned_maps": float(np.median([value["bpm_relative_error_percent"] for value in maps])) if maps else None,
            "maximum_absolute_rate_implied_drift_ms_returned_maps": max((abs(value["bpm_implied_drift_ms_over_input"]) for value in maps), default=None),
        }
    return summary
