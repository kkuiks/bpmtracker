"""Source-only barwise tempo proposal from a beat tracker's event observations.

The candidate keeps the observed bar phase and allows any number of supported
step changes. It is selected only when its physical beat/bar schedule explains
independent raw beat/downbeat events substantially better than the frozen
constant-grid map. Neither this module nor its selector reads a reference.
"""
from __future__ import annotations

from copy import deepcopy
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from grid_metrics import nearest_event_diagnostics
from music_map_contract import interpolate_clock, prepare_map, render_bars


MIN_BARS_PER_SECTION = 8
MIN_RATE_CHANGE_BPM = 1.0
MIN_OBSERVED_BAR_RATIO = 0.8
MIN_BAR_OBSERVATION_F1 = 0.8
MIN_BEAT_OBSERVATION_F1 = 0.75
MIN_IMPROVEMENT = 0.1
MAX_UNOBSERVED_END_BARS = 8


def _events(prepared: dict) -> tuple[list[float], list[float]]:
    knots = prepared['clock_knots']
    duration = prepared['duration_seconds']
    lower = math.ceil(knots[0]['pulse'] - 1e-9)
    upper = math.floor(knots[-1]['pulse'] + 1e-9)
    support = prepared['support_seconds']
    beats = [t for q in range(lower, upper + 1)
             if 0 <= (t := interpolate_clock(knots, float(q))) < duration
             and any(lo - 1e-9 <= t < hi - 1e-9 for lo, hi in support)]
    rendered = render_bars(prepared)
    if rendered['status'] != 'rendered':
        raise ValueError(f'candidate bar rendering failed: {rendered["status"]}')
    bars = [t for t in rendered['bar_events_seconds'] if 0 <= t < duration
            and any(lo - 1e-9 <= t < hi - 1e-9 for lo, hi in support)]
    return beats, bars


def _dedupe(raw: np.ndarray, nominal_bar_seconds: float) -> tuple[np.ndarray, float]:
    gaps = np.diff(raw)
    near = gaps[(gaps > .6 * nominal_bar_seconds) & (gaps < 1.6 * nominal_bar_seconds)]
    if len(near) < MIN_BARS_PER_SECTION * 2:
        raise ValueError('too few plausible bar intervals')
    median = float(np.median(near))
    kept = [float(raw[0])]
    for time in raw[1:]:
        if time - kept[-1] > .65 * median:
            kept.append(float(time))
    if len(kept) < 2 * MIN_BARS_PER_SECTION + 1:
        raise ValueError('too few separated bar events')
    return np.asarray(kept), median


def _segments(rate_seconds: np.ndarray, nominal_bar_seconds: float) -> list[tuple[int, int]]:
    """Penalized robust segmentation; no fixed number of rate changes."""
    n = len(rate_seconds)
    if n < 2 * MIN_BARS_PER_SECTION:
        raise ValueError('too few bars for a variable-tempo comparison')
    clip = .04 * nominal_bar_seconds
    penalty = .006 * nominal_bar_seconds ** 2
    costs = np.full((n + 1, n + 1), np.inf)
    medians = np.full((n + 1, n + 1), np.nan)
    for start in range(n):
        for stop in range(start + MIN_BARS_PER_SECTION, n + 1):
            values = rate_seconds[start:stop]
            center = float(np.median(values))
            medians[start, stop] = center
            costs[start, stop] = float(np.minimum((values - center) ** 2, clip ** 2).sum())
    best = np.full(n + 1, np.inf)
    previous = np.full(n + 1, -1, dtype=int)
    best[0] = -penalty
    for stop in range(MIN_BARS_PER_SECTION, n + 1):
        for start in range(0, stop - MIN_BARS_PER_SECTION + 1):
            score = best[start] + costs[start, stop] + penalty
            if score < best[stop]:
                best[stop], previous[stop] = score, start
    if previous[n] < 0:
        raise ValueError('no valid barwise segmentation')
    parts = []
    stop = n
    while stop:
        start = int(previous[stop])
        parts.append((start, stop))
        stop = start
    parts.reverse()
    # A one-BPM distinction is the minimum new structural claim.
    merged = [parts[0]]
    quarters_per_bar = 4.0  # only 4/4 enters the current barwise proposal
    for start, stop in parts[1:]:
        left_start, left_stop = merged[-1]
        left_bpm = 60 * quarters_per_bar / medians[left_start, left_stop]
        right_bpm = 60 * quarters_per_bar / medians[start, stop]
        if abs(left_bpm - right_bpm) < MIN_RATE_CHANGE_BPM:
            merged[-1] = (left_start, stop)
        else:
            merged.append((start, stop))
    return merged


def propose_barwise_tempo(base: dict, raw_beats: list[float],
                           raw_downbeats: list[float]) -> tuple[dict, dict]:
    """Return selected prediction and source-only admission evidence."""
    baseline = prepare_map(base['map'])
    meters = baseline['meter_events'] or []
    decision = {
        'source_only': True, 'reference_read': False,
        'policy': 'barwise-robust-change-search-v1',
        'accepted': False, 'reason': None,
    }
    if (len(meters) != 1 or meters[0]['numerator'] != 4 or
            meters[0]['denominator'] != 4 or
            baseline['quarters_per_pulse'] != {'numerator': 1, 'denominator': 1}):
        decision['reason'] = 'current_barwise_proposal_requires_single_4_4_base'
        return base, decision
    knots = baseline['clock_knots']
    nominal_period = (knots[-1]['source_seconds'] - knots[0]['source_seconds']) / (knots[-1]['pulse'] - knots[0]['pulse'])
    nominal_bar_seconds = 4 * nominal_period
    observed_beats = np.asarray(raw_beats, dtype=float)
    observed_bars = np.asarray(raw_downbeats, dtype=float)
    if (len(observed_beats) < 20 or len(observed_bars) < 20 or
            not np.isfinite(observed_beats).all() or
            not np.isfinite(observed_bars).all() or
            np.any(np.diff(observed_beats) <= 0) or
            np.any(np.diff(observed_bars) <= 0)):
        decision['reason'] = 'insufficient_finite_event_observations'
        return base, decision
    duration = baseline['duration_seconds']
    try:
        bars, median = _dedupe(observed_bars, nominal_bar_seconds)
        gaps = np.diff(bars)
        skipped = np.maximum(1, np.rint(gaps / median).astype(int))
        bar_indices = np.r_[0, np.cumsum(skipped)]
        ratio = len(bars) / (1 + int(bar_indices[-1]))
        if ratio < MIN_OBSERVED_BAR_RATIO:
            decision.update(reason='too_many_missing_bar_observations', observed_bar_ratio=ratio)
            return base, decision
        if duration - bars[-1] > MAX_UNOBSERVED_END_BARS * median:
            decision.update(reason='long_unobserved_ending', unobserved_end_seconds=duration - bars[-1])
            return base, decision
        normalized_gaps = gaps / skipped
        parts = _segments(normalized_gaps, median)
        if len(parts) < 2:
            decision.update(reason='no_supported_rate_change', observed_bar_ratio=ratio)
            return base, decision
        # A section boundary is an observed barline. Adjacent sections share
        # that point, so the map cannot accumulate a jump in musical time.
        initial_bar_length = (bars[parts[0][1]] - bars[0]) / bar_indices[parts[0][1]]
        initial_quarter = initial_bar_length / 4
        q0 = -bars[0] / initial_quarter
        if not math.isfinite(q0):
            raise ValueError('invalid source origin')
        proposed_knots = [{'pulse': q0, 'source_seconds': 0.0},
                          {'pulse': 0.0, 'source_seconds': float(bars[0])}]
        for _, stop in parts[:-1]:
            proposed_knots.append({'pulse': float(4 * bar_indices[stop]),
                                   'source_seconds': float(bars[stop])})
        last_start, last_stop = parts[-1]
        last_bar_length = ((bars[last_stop] - bars[last_start]) /
                           (bar_indices[last_stop] - bar_indices[last_start]))
        q_end = proposed_knots[-1]['pulse'] + (duration - proposed_knots[-1]['source_seconds']) * 4 / last_bar_length
        proposed_knots.append({'pulse': float(q_end), 'source_seconds': duration})
        raw_map = deepcopy(base['map'])
        raw_map['clock_knots'] = proposed_knots
        raw_map['bar_anchor_pulse'] = 0.0
        raw_map['meter_events'] = [{'pulse': q0, 'numerator': 4,
                                    'denominator': 4, 'grouping': [1, 1, 1, 1],
                                    'bar_action': 'continue'}]
        raw_map['support_seconds'] = [[0.0, duration]]
        candidate = prepare_map(raw_map)
        candidate_beats, candidate_bars = _events(candidate)
        base_beats, base_bars = _events(baseline)
        candidate_beat_f1 = nearest_event_diagnostics(observed_beats, candidate_beats, .07)['f1']
        candidate_bar_f1 = nearest_event_diagnostics(observed_bars, candidate_bars, .07)['f1']
        base_beat_f1 = nearest_event_diagnostics(observed_beats, base_beats, .07)['f1']
        base_bar_f1 = nearest_event_diagnostics(observed_bars, base_bars, .07)['f1']
        gain = .5 * (candidate_beat_f1 + candidate_bar_f1 - base_beat_f1 - base_bar_f1)
        penalty = .02 * (len(parts) - 1)
        decision.update({
            'observed_bar_ratio': ratio,
            'nominal_bar_seconds': nominal_bar_seconds,
            'deduplicated_bar_count': len(bars),
            'segment_bar_ranges': [[int(bar_indices[start]), int(bar_indices[stop])]
                                   for start, stop in parts],
            'segment_source_seconds': [[float(bars[start]), float(bars[stop])]
                                       for start, stop in parts],
            'candidate_beat_observation_f1_70ms': candidate_beat_f1,
            'candidate_bar_observation_f1_70ms': candidate_bar_f1,
            'base_beat_observation_f1_70ms': base_beat_f1,
            'base_bar_observation_f1_70ms': base_bar_f1,
            'penalized_observation_gain': gain - penalty,
            'change_count': len(parts) - 1,
        })
        if candidate_beat_f1 < MIN_BEAT_OBSERVATION_F1 or candidate_bar_f1 < MIN_BAR_OBSERVATION_F1:
            decision['reason'] = 'poor_raw_event_agreement'
            return base, decision
        if gain - penalty < MIN_IMPROVEMENT:
            decision['reason'] = 'insufficient_source_observation_gain'
            return base, decision
        output = deepcopy(base)
        output['map'] = raw_map
        output['beat_times_seconds'] = candidate_beats
        output['bar_starts_seconds'] = candidate_bars
        output['diagnostics']['constant_grid_only'] = False
        decision.update(accepted=True, reason='variable_tempo_supported_by_source_events')
        output['diagnostics']['barwise_tempo'] = decision
        return output, decision
    except (ValueError, IndexError, OverflowError, ZeroDivisionError) as error:
        decision['reason'] = f'candidate_invalid:{type(error).__name__}'
        decision['error'] = str(error)
        return base, decision
