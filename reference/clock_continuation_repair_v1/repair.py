"""Repair absent output without muting weak source evidence or inventing clocks.

The original composer and frozen maps stay untouched. The repair runs before
the existing half/double correction so its initial source clock participates in
that correction. Internal gaps always hold the last corrected physical clock.
"""
from __future__ import annotations

import copy
import numpy as np

from experiments.variable_clock_composition_v1.compose import initial_episode
from experiments.variable_clock_composition_v1.common import CONFIG as SOURCE_CONFIG
from experiments.variable_clock_composition_v1.evidence import intervals, seed_episodes
from experiments.octave_fold_confirmation_v1.correct import apply as octave_apply


def initial_clock(tab, packet):
    clocks = tab['clocks']
    if not clocks:
        return None, 'NO_AUDIO_CLOCK'
    permitted = np.ones(len(clocks), dtype=bool)
    if packet and packet.get('available'):
        layers = np.floor(np.log2(np.array([h['bpm'] for h in clocks]) / packet['base_bpm']) + .5).astype(int)
        permitted = layers == packet['power']
        source_index = int(packet['clock'])
        if 0 <= source_index < len(clocks) and permitted[source_index]:
            return source_index, 'PREPARED_INITIAL_SOURCE_CLOCK'
    else:
        episode = initial_episode(tab, SOURCE_CONFIG)
        if episode is not None:
            return int(episode['clock']), 'EARLIEST_QUALIFIED_SOURCE_EPISODE'
    episodes = [e for e in seed_episodes(tab, SOURCE_CONFIG) if permitted[e['clock']]
                and e['start'] <= SOURCE_CONFIG['initial_deadline']]
    if episodes:
        earliest = min(e['start'] for e in episodes)
        early = [e for e in episodes if e['start'] <= earliest + 1.]
        chosen = max(early, key=lambda e: (e['quality'], e['rank'], -e['clock']))
        return int(chosen['clock']), 'QUALIFIED_INITIAL_UNIT_EPISODE'
    # Keep an acoustic clock available even when confidence is below the seed
    # threshold. The input unit only filters retained candidates; no tap number,
    # target BPM, reference phase or reference boundary is available here.
    if packet and packet.get('available'):
        use = (tab['time'] >= packet['scope_start']) & (tab['time'] < packet['scope_end'])
    else:
        use = tab['time'] < SOURCE_CONFIG['initial_deadline']
    if not use.any():
        use = np.ones(len(tab['time']), dtype=bool)
    candidates = np.flatnonzero(permitted & np.any(tab['seed_count'][use] > 0., axis=0))
    if not len(candidates):
        return None, 'NO_SOURCE_SUPPORTED_INITIAL_UNIT_CLOCK'
    winner = max(candidates, key=lambda j: (float(tab['quality'][use, j].mean()), -int(j)))
    return int(winner), 'LOW_CONFIDENCE_RETAINED_SOURCE_CLOCK'


def source_segment(tab, index, start, end, reason):
    h = tab['clocks'][index]
    return {'start': float(start), 'end': float(end), 'bpm': h['bpm'], 'phase': h['phase'],
            'period': 60. / h['bpm'], 'clock_index': int(index),
            'provenance': 'source_clock_continuation', 'continuation_gap': 'INITIAL',
            'continuation_reason': reason}


def repair_raw(raw, tab, packet=None):
    result = copy.deepcopy(raw)
    spans = sorted(result['accepted'], key=lambda s: s['start'])
    duration = float(tab['duration'])
    repaired, changes = [], []
    if not spans or spans[0]['start'] > 0.:
        end = float(spans[0]['start']) if spans else duration
        index, reason = initial_clock(tab, packet)
        if index is not None:
            repaired.append(source_segment(tab, index, 0., end, reason))
            changes.append({'start': 0., 'end': end, 'kind': 'INITIAL', 'clock_index': index, 'reason': reason})
        else:
            changes.append({'start': 0., 'end': end, 'kind': 'UNAVAILABLE', 'reason': reason})
    for segment in spans:
        if repaired and segment['start'] > repaired[-1]['end']:
            previous = repaired[-1]
            held = {**previous, 'start': previous['end'], 'end': segment['start'],
                    'continuation_gap': 'HOLD', 'continuation_reason': 'KEEP_PREVIOUS_PHYSICAL_CLOCK'}
            repaired.append(held)
            changes.append({'start': held['start'], 'end': held['end'], 'kind': 'HOLD', 'clock_index': held['clock_index']})
        repaired.append(segment)
    if repaired and repaired[-1]['end'] < duration:
        previous = repaired[-1]
        held = {**previous, 'start': previous['end'], 'end': duration,
                'continuation_gap': 'HOLD', 'continuation_reason': 'KEEP_PREVIOUS_PHYSICAL_CLOCK'}
        repaired.append(held)
        changes.append({'start': held['start'], 'end': held['end'], 'kind': 'HOLD', 'clock_index': held['clock_index']})
    result['accepted'] = repaired
    result['continuation_repair'] = {'events': changes, 'numeric_tap_available': False,
                                   'original_accepted_spans_preserved': True,
                                   'source_bank_unchanged': True, 'mute_on_low_confidence': False}
    return result


def predict(raw, tab, packet=None, fold=True):
    repaired = repair_raw(raw, tab, packet)
    result = copy.deepcopy(repaired)
    options = {'mode': 'fold' if fold else 'raw', 'tolerance': .05}
    method = 'R1_FOLD_CONTINUE' if fold else 'R0_RAW_CONTINUE'
    metadata = octave_apply({**repaired, 'accepted': []}, tab, method, options)
    result['correction'] = metadata['correction']
    accepted, decisions = [], []
    for raw_segment in repaired['accepted']:
        if raw_segment.get('continuation_gap') == 'HOLD' and accepted:
            previous = accepted[-1]
            chosen = dict(raw_segment)
            chosen.update({k: previous[k] for k in ['bpm', 'phase', 'period', 'clock_index']})
            chosen['provenance'] = 'held_previous_corrected_source_clock'
        elif fold and accepted:
            pair = octave_apply({**repaired, 'accepted': [accepted[-1], raw_segment]}, tab, method, options)
            chosen = pair['accepted'][-1]
            decisions.extend(pair['correction_events'])
        else:
            chosen = dict(raw_segment)
        accepted.append(chosen)
    result['accepted'] = accepted
    result['method'] = method
    result['correction_events'] = decisions
    # Confidence metadata remains observable and never controls click emission.
    diagnostics = []
    for s in accepted:
        use = np.flatnonzero((tab['time'] >= s['start']) & (tab['time'] < s['end']))
        if not len(use): continue
        j = s['clock_index']
        weak = (tab['quality'][use, j] < SOURCE_CONFIG['quality_threshold']) | (tab['count'][use, j] < 4)
        for a, b in intervals(weak):
            diagnostics.append({'start': max(s['start'], float(tab['time'][use[a]] - SOURCE_CONFIG['step']/2)),
                                'end': min(s['end'], float(tab['time'][use[b-1]] + SOURCE_CONFIG['step']/2)),
                                'status': 'HELD_WEAK_EVIDENCE', 'bpm': s['bpm'], 'phase': s['phase']})
    for event in result['continuation_repair']['events']:
        if event['kind'] == 'UNAVAILABLE': diagnostics.append({**event, 'status': 'NO_AUDIO_CLOCK_AVAILABLE'})
    result['diagnostic'] = diagnostics
    return result
