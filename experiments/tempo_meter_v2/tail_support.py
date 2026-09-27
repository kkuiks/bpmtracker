"""Conservative source-only grid-end proposal for a disrupted final passage.

The detector looks for a sustained increase in non-lattice raw beat intervals
and a loss of expected downbeat observations near the physical end. It
abstains if either signal alone is present. A cut is a source-only candidate,
not proof that the producer actually stopped the click there.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from .barwise_tempo import _events, prepare_map, render_bars


def _bar_support(observed: np.ndarray, expected: np.ndarray) -> float:
    if len(expected) == 0 or len(observed) == 0:
        return 0.0
    return float(np.mean([np.min(np.abs(observed - t)) <= .07 for t in expected]))


def propose_tail_stop(prediction: dict, base: dict, raw_beats: list[float],
                      raw_downbeats: list[float]) -> tuple[dict, dict]:
    """Return map with shorter support only if both future signals fail."""
    prepared_base = prepare_map(base['map'])
    duration = prepared_base['duration_seconds']
    fine_knots = prepared_base['clock_knots']
    fine_period = ((fine_knots[-1]['source_seconds'] - fine_knots[0]['source_seconds']) /
                   (fine_knots[-1]['pulse'] - fine_knots[0]['pulse']))
    result = deepcopy(prediction)
    decision = {'source_only': True, 'reference_read': False,
                'policy': 'sustained-last-45s-lattice-and-downbeat-loss-v1',
                'accepted': False, 'reason': None}
    observed_beats = np.asarray(raw_beats, dtype=float)
    observed_bars = np.asarray(raw_downbeats, dtype=float)
    if (len(observed_beats) < 20 or len(observed_bars) < 8 or
            not np.isfinite(observed_beats).all() or
            not np.isfinite(observed_bars).all()):
        decision['reason'] = 'insufficient_events'
        return prediction, decision
    base_rendered = render_bars(prepared_base)
    if base_rendered['status'] != 'rendered':
        decision['reason'] = 'base_bars_unavailable'
        return prediction, decision
    expected = np.asarray(base_rendered['bar_events_seconds'], dtype=float)
    candidates = []
    for time in expected:
        if not duration - 45 <= time <= duration - 8:
            continue
        before = observed_beats[(observed_beats >= time - 8) & (observed_beats < time)]
        after = observed_beats[(observed_beats >= time) & (observed_beats < time + 8)]
        if len(before) < 6 or len(after) < 6:
            continue
        short_before = float(np.mean(np.diff(before) < .65 * fine_period))
        short_after = float(np.mean(np.diff(after) < .65 * fine_period))
        density_after = len(after) / (8 / fine_period)
        past_grid = expected[(expected >= time - 16) & (expected < time)]
        future_grid = expected[(expected >= time) & (expected < time + 16)]
        past_support = _bar_support(observed_bars, past_grid)
        future_support = _bar_support(observed_bars, future_grid)
        if (short_after >= .4 and short_before <= .1 and density_after >= 1.2 and
                future_support <= .4 and past_support >= .5):
            candidates.append({
                'stop_seconds': float(time),
                'short_interval_fraction_before': short_before,
                'short_interval_fraction_after': short_after,
                'event_density_after_to_grid': density_after,
                'bar_support_before': past_support,
                'bar_support_after': future_support,
            })
    if not candidates:
        decision['reason'] = 'no_joint_tail_disruption'
        return prediction, decision
    chosen = candidates[0]
    support = result['map']['support_seconds']
    if len(support) != 1 or not support[0][0] < chosen['stop_seconds'] < support[0][1]:
        decision['reason'] = 'candidate_outside_single_grid_support'
        return prediction, decision
    result['map']['support_seconds'] = [[support[0][0], chosen['stop_seconds']]]
    prepared = prepare_map(result['map'])
    beats, bars = _events(prepared)
    result['beat_times_seconds'] = beats
    result['bar_starts_seconds'] = bars
    decision.update(accepted=True, reason='joint_tail_disruption',
                    selected=chosen, candidate_count=len(candidates))
    result['diagnostics']['tail_support'] = decision
    return result, decision
