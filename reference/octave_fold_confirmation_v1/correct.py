"""Correct only local 2x/0.5x families using already retained source clocks.

This is an offline map-component probe. Raw interval edges are fixed, the bank
is unchanged, and no reference, tap number, meter or song name enters here.
"""
from __future__ import annotations

import copy
import numpy as np

from experiments.variable_clock_composition_v1.compose import phase_distance
from .common import CONFIG


def family(raw_rate, previous_rate, tolerance):
    for factor in (2., .5):
        folded = raw_rate / factor
        if abs(folded / previous_rate - 1.) <= tolerance + 1e-12:
            return factor
    return None


def nested_error(candidate, raw):
    period = min(60. / candidate['bpm'], 60. / raw['bpm'])
    return abs((candidate['phase'] - raw['phase'] + period / 2.) % period - period / 2.)


def folded_clock(raw, previous, target, tab, cfg):
    times = tab['time']
    use = (times >= raw['start']) & (times < raw['end'])
    if not use.any():
        return None, {'reason': 'NO_TABLE_CENTERS'}
    rates = np.array([clock['bpm'] for clock in tab['clocks']])
    matching = np.flatnonzero(abs(rates - target) <= cfg['exact_folded_rate_tolerance'])
    usable = []
    for index in matching:
        clock = tab['clocks'][int(index)]
        phase_error = nested_error(clock, raw)
        if phase_error > cfg['maximum_nested_grid_phase_error_seconds'] + 1e-12:
            continue
        quality = tab['quality'][use, index]
        count = tab['seed_count'][use, index]
        qualified = (quality >= cfg['minimum_folded_quality']) & (count >= cfg['minimum_folded_seed_count'])
        if not qualified.any():
            continue
        mean_quality = float(quality.mean())
        continuity = phase_distance(previous, clock, raw['start'])
        value = mean_quality - cfg['continuity_phase_weight'] * continuity
        usable.append((value, mean_quality, -continuity, -int(index), int(index), phase_error,
                       float(qualified.mean())))
    if not usable:
        return None, {'reason': 'NO_SUPPORTED_NESTED_FOLDED_CLOCK', 'rate_candidates': len(matching)}
    winner = max(usable)
    index = winner[4]
    return tab['clocks'][index], {
        'reason': 'SUPPORTED_FOLDED_CLOCK', 'bank_index': index,
        'rate_candidates': len(matching), 'eligible_candidates': len(usable),
        'source_mean_quality': winner[1], 'phase_continuity': -winner[2],
        'nested_phase_error_seconds': winner[5], 'qualified_table_fraction': winner[6],
    }


def apply(raw_prediction, tab, method, options, cfg=None):
    cfg = dict(CONFIG if cfg is None else cfg)
    output = copy.deepcopy(raw_prediction)
    output['method'] = method
    output['correction'] = {
        'mode': options['mode'], 'alias_tolerance': options['tolerance'],
        'raw_interval_boundaries_fixed': True, 'source_bank_unchanged': True,
        'raw_phase_and_predictions_preserved_separately': True,
        'no_numeric_tap_used': True, 'whole_song_rate_band': False,
        'default_assumption': 'near_local_2x_or_0.5x_is_a_counting_change',
        'genuine_2x_exception_detector': False,
    }
    if options['mode'] == 'raw':
        output['correction_events'] = []
        return output
    accepted = []
    decisions = []
    previous = None
    for raw in raw_prediction['accepted']:
        chosen = dict(raw)
        factor = None if previous is None else family(raw['bpm'], previous['bpm'], options['tolerance'])
        if factor is not None:
            target = raw['bpm'] / factor
            replacement = None
            detail = {'reason': 'VETO_HOLD'}
            if options['mode'] == 'fold':
                replacement, detail = folded_clock(raw, previous, target, tab, cfg)
            if replacement is None:
                chosen.update({key: previous[key] for key in ('bpm', 'phase', 'period')})
                chosen['clock_index'] = previous['clock_index']
                chosen['provenance'] = 'held_previous_source_clock'
                action = 'HOLD'
            else:
                chosen.update({key: replacement[key] for key in ('bpm', 'phase')})
                chosen['period'] = 60. / replacement['bpm']
                chosen['clock_index'] = detail['bank_index']
                chosen['provenance'] = 'selected_existing_folded_source_clock'
                action = 'FOLD'
            decisions.append({
                'start': raw['start'], 'end': raw['end'], 'previous_bpm': previous['bpm'],
                'raw_bpm': raw['bpm'], 'factor': factor, 'folded_target_bpm': target,
                'selected_bpm': chosen['bpm'], 'selected_phase': chosen['phase'],
                'action': action, 'source_evidence': detail,
            })
        accepted.append(chosen)
        previous = chosen
    output['accepted'] = accepted
    output['correction_events'] = decisions
    # Preserve the old flags only in the raw baseline. Recompute weak-evidence
    # descriptions for each selected source clock; no output is muted here.
    output['diagnostic'] = []
    return output
