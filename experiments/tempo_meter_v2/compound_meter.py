"""Source-only six-eighth interpretation of a six-pulse fine grid.

A six-pulse bar alone does not identify 6/8. This proposal requires the official
beat observation to spend most of the song at three fine pulses per event,
consistent with two dotted-quarter groups per bar. It keeps the original
physical beat and bar phase; only the declared quarter unit and meter change.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from .barwise_tempo import _events, prepare_map


def propose_compound_6_8(base: dict, raw_beats: list[float]) -> tuple[dict, dict]:
    meter = base['map']['meter_events'][0]
    knots = base['map']['clock_knots']
    period = ((knots[-1]['source_seconds'] - knots[0]['source_seconds']) /
              (knots[-1]['pulse'] - knots[0]['pulse']))
    fine_bpm = 60 / period
    decision = {
        'source_only': True, 'reference_read': False,
        'policy': 'six-fine-pulses-with-three-pulse-observed-beats-v1',
        'fine_pulse_bpm': fine_bpm,
        'accepted': False, 'reason': None,
        'alternative_notation': '6/4 on the same physical bar clock',
    }
    if (len(base['map']['meter_events']) != 1 or
            (meter['numerator'], meter['denominator']) != (6, 4) or
            not 160 <= fine_bpm <= 320):
        decision['reason'] = 'six_fine_pulse_grid_not_present'
        return base, decision
    events = np.asarray(raw_beats, dtype=float)
    if len(events) < 24 or not np.isfinite(events).all() or np.any(np.diff(events) <= 0):
        decision['reason'] = 'insufficient_raw_beat_events'
        return base, decision
    gaps = np.diff(events)
    triple = np.abs(gaps / period - 3) <= .36
    coverage = float(gaps[triple].sum() / gaps.sum())
    decision['three_pulse_gap_time_fraction'] = coverage
    if coverage < .5:
        decision['reason'] = 'no_sustained_three_pulse_grouping'
        return base, decision
    result = deepcopy(base)
    for knot in result['map']['clock_knots']:
        knot['pulse'] /= 2
    result['map']['bar_anchor_pulse'] /= 2
    result['map']['meter_events'] = [{
        'pulse': meter['pulse'] / 2,
        'numerator': 6, 'denominator': 8,
        'grouping': [3, 3], 'bar_action': 'continue',
    }]
    prepared = prepare_map(result['map'])
    beats,bars = _events(prepared)
    result['beat_times_seconds'] = beats
    result['bar_starts_seconds'] = bars
    result['diagnostics']['constant_grid_only'] = False
    decision.update(accepted=True, reason='supported_compound_six_eighth_interpretation',
                    quarter_bpm=fine_bpm / 2)
    result['diagnostics']['compound_meter'] = decision
    return result, decision
