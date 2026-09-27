"""Conservative source-only step-tempo proposals over a quarter grid.

Local periodicity only proposes competing rates and broad change windows.
Whole-song beat/downbeat activations select coherent bar-aligned transitions.
This bounded pilot searches at most three changes and declines ambiguous cases.
"""
from __future__ import annotations

from copy import deepcopy
import math
import numpy as np

from .constant_grid import _probability, beat_period


def _octave_near(rate, reference):
    return min((rate / 2, rate, rate * 2), key=lambda x: abs(math.log(x / reference)))


def _local_runs(logits, fps, base_rate):
    duration = len(logits) / fps
    windows = []
    for center in np.arange(8., duration - 8., 2.):
        part = logits[round((center-8)*fps):round((center+8)*fps)]
        rate = _octave_near(beat_period(part, fps)["quarter_bpm"], base_rate)
        windows.append((float(center), float(rate)))
    runs = []
    current = []
    for center, rate in windows:
        if abs(rate - base_rate) > 2 and (not current or abs(rate-current[-1][1]) < 1.5):
            current.append((center, rate))
        else:
            if len(current) >= 5:
                runs.append(current)
            current = [(center, rate)] if abs(rate-base_rate) > 2 else []
    if len(current) >= 5:
        runs.append(current)
    return [{"first_center": run[0][0], "last_center": run[-1][0],
             "median_bpm": float(np.median([r for _, r in run])),
             "window_count": len(run)} for run in runs]


def _phase(logits, fps, bpm):
    probability = _probability(logits)
    frequency = bpm / 60
    time = np.arange(len(probability)) / fps
    coefficient = np.dot(probability-probability.mean(),
                         np.exp(-2j*np.pi*frequency*time))
    return float((-np.angle(coefficient)/(2*np.pi*frequency)) % (1/frequency))


def _sample(probability, fps, seconds):
    frame = np.clip(np.rint(seconds*fps).astype(int), 0, len(probability)-1)
    neighbors = np.stack((np.clip(frame-1, 0, len(probability)-1), frame,
                          np.clip(frame+1, 0, len(probability)-1)))
    return np.max(probability[neighbors], axis=0)


def _clock_times(pulses, changes, periods, phase):
    times = np.empty_like(pulses, dtype=float)
    start = 0
    at = phase
    for i, end in enumerate((*changes, len(pulses)-1)):
        stop = min(end, len(pulses)-1)
        times[start:stop+1] = at + (pulses[start:stop+1] - start)*periods[i % 2]
        at = float(times[stop])
        start = stop
    return times


def _evaluate(changes, periods, phase, duration, beat, down, fps, bar_size, anchor):
    count = math.ceil((duration-phase) / min(periods)) + 2
    pulses = np.arange(count+1)
    times = _clock_times(pulses, changes, periods, phase)
    inside = times <= duration
    pulses, times = pulses[inside], times[inside]
    if len(times) < 16:
        return -math.inf, pulses, times
    bar_times = times[(pulses-anchor) % bar_size == 0]
    if len(bar_times) < 4:
        return -math.inf, pulses, times
    value = float(_sample(beat, fps, times).mean() +
                  .8*_sample(down, fps, bar_times).mean())
    return value, pulses, times


def infer_tempo_segments(base, beat_logits, downbeat_logits, fps, observed_beats):
    """Propose an alternate full-source map only for a supported step pattern."""
    if base["status"] != "proposed_map" or not base["diagnostics"].get("constant_grid_only"):
        raise ValueError("frozen constant-grid proposal required")
    source = base["map"]["source"]
    duration = source["sample_frames"] / source["sample_rate"]
    beat = _probability(beat_logits)
    down = _probability(downbeat_logits)
    if len(beat) != len(down) or len(beat)/fps < duration-.03:
        raise ValueError("source-wide logits required")
    global_rate = base["diagnostics"]["period"]["quarter_bpm"]
    runs = _local_runs(beat_logits, fps, global_rate)
    result = deepcopy(base)
    diagnostic = {"source_only": True, "local_window_seconds": 16,
                  "local_hop_seconds": 2, "minimum_run_windows": 5,
                  "max_transitions": 3, "local_alternative_runs": runs,
                  "accepted": False, "reason": None}
    result["diagnostics"]["tempo_segments"] = diagnostic
    if not runs:
        diagnostic["reason"] = "no_sustained_alternate_rate"
        return result
    if len(runs) > 2 or max(x["median_bpm"] for x in runs)-min(x["median_bpm"] for x in runs) > 1.5:
        diagnostic["reason"] = "multiple_inconsistent_alternate_runs"
        return result
    first = runs[0]["first_center"]
    prefix_end = first - 8
    if prefix_end < 24:
        diagnostic["reason"] = "no_stable_starting_rate"
        return result
    prefix = beat_logits[:round(prefix_end*fps)]
    base_rate = _octave_near(beat_period(prefix, fps)["quarter_bpm"], global_rate)
    if abs(base_rate-global_rate) > 1.0:
        diagnostic["reason"] = "global_and_prefix_rates_disagree"
        return result
    longest = max(runs, key=lambda x:x["window_count"])
    core_start = longest["first_center"]+8
    core_end = longest["last_center"]-8
    if core_end-core_start < 8:
        midpoint = (longest["first_center"]+longest["last_center"])/2
        core_start, core_end = midpoint-8, midpoint+8
    alt_part = beat_logits[round(core_start*fps):round(core_end*fps)]
    alt_rate = _octave_near(beat_period(alt_part, fps)["quarter_bpm"], global_rate)
    if abs(alt_rate-base_rate) < 2:
        diagnostic["reason"] = "alternate_rate_not_distinct"
        return result
    phase = _phase(prefix, fps, base_rate)
    meter = base["map"]["meter_events"][0]
    bar_quarters = 4*meter["numerator"]/meter["denominator"]
    if abs(bar_quarters-round(bar_quarters)) > 1e-9:
        diagnostic["reason"] = "noninteger_bar_quarter_grid"
        return result
    bar_size = int(round(bar_quarters))
    anchor = int(round(base["map"]["bar_anchor_pulse"])) % bar_size
    transition_windows = []
    for run in runs:
        transition_windows.append((run["first_center"]-8, run["first_center"]+20))
        if run["last_center"] < duration-10:
            transition_windows.append((run["last_center"]-12, run["last_center"]+8))
    if len(transition_windows) > 3:
        diagnostic["reason"] = "more_than_three_transition_windows"
        return result
    periods = (60/base_rate, 60/alt_rate)
    constant_score, _, _ = _evaluate((), periods, phase, duration, beat, down, fps,
                                     bar_size, anchor)
    possibilities = []
    def search(level, previous_pulse, previous_time, keys):
        if level == len(transition_windows):
            score, _, _ = _evaluate(keys, periods, phase, duration, beat, down, fps,
                                     bar_size, anchor)
            possibilities.append((score, keys))
            return
        low, high = transition_windows[level]
        step = periods[level % 2]
        lower = max(previous_pulse+bar_size,
                    previous_pulse+math.ceil((low-previous_time)/step))
        upper = previous_pulse+math.floor((high-previous_time)/step)
        lower += (anchor-lower) % bar_size
        for pulse in range(lower, upper+1, bar_size):
            change_time = previous_time+(pulse-previous_pulse)*step
            if 0 < change_time < duration:
                search(level+1, pulse, change_time, (*keys, pulse))
    search(0, 0, phase, ())
    if not possibilities:
        diagnostic["reason"] = "no_bar_aligned_change_candidate"
        return result
    possibilities.sort(key=lambda x:-x[0])
    best_score, selected = possibilities[0]
    second_score = possibilities[1][0] if len(possibilities)>1 else -math.inf
    gain = best_score - constant_score - .015*len(selected)
    margin = best_score-second_score
    diagnostic.update({"base_bpm": float(base_rate), "alternate_bpm": float(alt_rate),
                       "prefix_seconds": float(prefix_end),
                       "alternate_core_seconds": [float(core_start),float(core_end)],
                       "candidate_count": len(possibilities),
                       "constant_acoustic_score": constant_score,
                       "best_acoustic_score": best_score,
                       "penalized_gain": float(gain), "best_to_second_margin": float(margin),
                       "selected_change_quarters": list(selected)})
    if gain < .07 or margin < .025:
        diagnostic["reason"] = "insufficient_acoustic_advantage"
        return result
    _, pulses, times = _evaluate(selected, periods, phase, duration, beat, down,
                                  fps, bar_size, anchor)
    boundaries = [0, *selected]
    knots = [{"pulse": float(pulse), "source_seconds": float(times[pulse])}
             for pulse in boundaries]
    knots.append({"pulse": float(selected[-1]+(duration-times[selected[-1]])/periods[len(selected)%2]),
                  "source_seconds": float(duration)})
    if any(a["pulse"] >= b["pulse"] or a["source_seconds"] >= b["source_seconds"]
           for a,b in zip(knots,knots[1:])):
        raise ValueError("nonmonotonic step map")
    result["map"]["clock_knots"] = knots
    result["map"]["bar_anchor_pulse"] = float(anchor)
    # A four half-note bar and eight quarter-note bar share physical boundaries.
    # An observed half-note pulse provides a notation hypothesis, not certainty.
    observed = np.asarray(observed_beats,dtype=float)
    if bar_size == 8 and len(observed)>3:
        ratio = float(np.median(np.diff(observed)) / periods[0])
        if 1.8 <= ratio <= 2.2:
            result["map"]["meter_events"] = [{"pulse":0.0,"numerator":4,
                "denominator":2,"grouping":[1,1,1,1],"bar_action":"continue"}]
            diagnostic["half_note_notation_hypothesis"] = True
    result["map"]["support_seconds"] = [[float(phase),float(duration)]]
    result["beat_times_seconds"] = times.tolist()
    result["bar_starts_seconds"] = times[(pulses-anchor)%bar_size==0].tolist()
    result["diagnostics"]["constant_grid_only"] = False
    diagnostic["accepted"] = True
    return result
