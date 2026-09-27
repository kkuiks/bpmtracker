"""Conservative source-only BPM cleanup for a finished tempo/meter map.

Choose nearby integer BPM first, then nearby half BPM. Retain the original
continuous estimate whenever a candidate would move any in-source click or
change boundary too far, alter event counts, or erase a selected tempo step.
No reference map or score is consulted.
"""
from __future__ import annotations

from copy import deepcopy
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import interpolate_clock, prepare_map, render_bars


INTEGER_WINDOW_BPM = 0.1
HALF_WINDOW_BPM = 0.05
MAX_EVENT_SHIFT_SECONDS = 0.035
CHANGE_EPSILON_BPM = 1e-6


def _rates(value: dict) -> list[float]:
    knots = value["clock_knots"]
    unit = (value["quarters_per_pulse"]["numerator"] /
            value["quarters_per_pulse"]["denominator"])
    return [
        60 * (b["pulse"] - a["pulse"]) * unit /
        (b["source_seconds"] - a["source_seconds"])
        for a, b in zip(knots, knots[1:])
    ]


def _events(value: dict) -> tuple[list[float], list[float]]:
    prepared = prepare_map(value)
    knots = prepared["clock_knots"]
    duration = prepared["duration_seconds"]
    support = prepared["support_seconds"]
    lo = math.ceil(knots[0]["pulse"] - 1e-9)
    hi = math.floor(knots[-1]["pulse"] + 1e-9)
    beats = [
        t for pulse in range(lo, hi + 1)
        if (t := interpolate_clock(knots, float(pulse))) < duration
        and any(start - 1e-9 <= t < stop for start, stop in support)
    ]
    rendered = render_bars(prepared)
    if rendered["status"] != "rendered":
        raise ValueError(f"map cannot render bars: {rendered['status']}")
    bars = [
        t for t in rendered["bar_events_seconds"]
        if 0 <= t < duration and
        any(start - 1e-9 <= t < stop for start, stop in support)
    ]
    return beats, bars


def _preferred_rate(rate: float) -> tuple[float, str]:
    integer = float(round(rate))
    if abs(rate - integer) <= INTEGER_WINDOW_BPM + 1e-9:
        return integer, "integer"
    half = round(rate * 2) / 2
    if abs(rate - half) <= HALF_WINDOW_BPM + 1e-9:
        return float(half), "half"
    return rate, "continuous"


def _step_pattern_preserved(before: list[float], after: list[float]) -> bool:
    for a, b, c, d in zip(before, before[1:], after, after[1:]):
        old = b - a
        new = d - c
        if (abs(old) > CHANGE_EPSILON_BPM) != (abs(new) > CHANGE_EPSILON_BPM):
            return False
        if abs(old) > CHANGE_EPSILON_BPM and old * new <= 0:
            return False
    return True


def snap_prediction(prediction: dict) -> tuple[dict, dict]:
    """Return the selected map and a reasoned decision, without references."""
    original = prepare_map(prediction["map"])
    knots = original["clock_knots"]
    duration = original["duration_seconds"]
    if abs(knots[-1]["source_seconds"] - duration) > 1e-7:
        raise ValueError("source clock must reach the physical audio end")
    old_rates = _rates(original)
    choices = [_preferred_rate(rate) for rate in old_rates]
    wanted = [rate for rate, _ in choices]
    segments = [
        {"original_bpm": old, "proposed_bpm": new, "kind": kind}
        for old, (new, kind) in zip(old_rates, choices)
    ]
    decision = {
        "policy": "near-integer-then-half-with-whole-song-drift-guard-v1",
        "integer_window_bpm": INTEGER_WINDOW_BPM,
        "half_window_bpm": HALF_WINDOW_BPM,
        "maximum_event_shift_seconds": MAX_EVENT_SHIFT_SECONDS,
        "source_only": True,
        "reference_read": False,
        "segments": segments,
        "accepted": False,
        "reason": None,
        "observed_maximum_event_shift_seconds": 0.0,
    }
    if not any(abs(a - b) > 1e-10 for a, b in zip(old_rates, wanted)):
        decision["reason"] = "already_clean_or_no_nearby_candidate"
        return prediction, decision
    if not _step_pattern_preserved(old_rates, wanted):
        decision["reason"] = "tempo_step_would_change"
        return prediction, decision

    unit = (original["quarters_per_pulse"]["numerator"] /
            original["quarters_per_pulse"]["denominator"])
    updated = [dict(knots[0])]
    for index, (last, rate) in enumerate(zip(knots[1:], wanted)):
        if index < len(wanted) - 1:
            end_pulse = last["pulse"]
            end_seconds = updated[-1]["source_seconds"] + (
                end_pulse - updated[-1]["pulse"]) * 60 * unit / rate
        else:
            end_seconds = duration
            end_pulse = updated[-1]["pulse"] + (
                end_seconds - updated[-1]["source_seconds"]) * rate / (60 * unit)
        if (end_pulse <= updated[-1]["pulse"] or
                end_seconds <= updated[-1]["source_seconds"]):
            decision["reason"] = "retimed_clock_not_monotonic"
            return prediction, decision
        updated.append({"pulse": float(end_pulse), "source_seconds": float(end_seconds)})

    result = deepcopy(prediction)
    result["map"]["clock_knots"] = updated
    try:
        revised = prepare_map(result["map"])
        before_beats, before_bars = _events(original)
        after_beats, after_bars = _events(revised)
    except (ValueError, TypeError, KeyError, OverflowError):
        decision["reason"] = "retimed_map_cannot_render"
        return prediction, decision
    if len(before_beats) != len(after_beats) or len(before_bars) != len(after_bars):
        decision["reason"] = "click_event_count_changed"
        return prediction, decision
    shifts = [
        abs(a - b)
        for old, new in ((before_beats, after_beats), (before_bars, after_bars))
        for a, b in zip(old, new)
    ]
    shifts.extend(abs(a["source_seconds"] - b["source_seconds"])
                  for a, b in zip(knots[1:-1], updated[1:-1]))
    maximum = max(shifts, default=0.0)
    decision["observed_maximum_event_shift_seconds"] = maximum
    if maximum > MAX_EVENT_SHIFT_SECONDS + 1e-9:
        decision["reason"] = "whole_song_drift_exceeds_budget"
        return prediction, decision
    if not _step_pattern_preserved(old_rates, _rates(revised)):
        decision["reason"] = "retimed_tempo_step_changed"
        return prediction, decision

    result["beat_times_seconds"] = after_beats
    result["bar_starts_seconds"] = after_bars
    result["diagnostics"]["plausible_bpm"] = decision | {
        "accepted": True, "reason": "near_human_rate_within_drift_budget"}
    decision["accepted"] = True
    decision["reason"] = "near_human_rate_within_drift_budget"
    return result, decision
