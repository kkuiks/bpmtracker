"""Evaluation-only adapters; no clocks or labels enter source prediction."""
from __future__ import annotations

from fractions import Fraction
import numpy as np


def nominal(value):
    value = float(value); simple = float(Fraction(value).limit_denominator(4))
    return simple if abs(simple - value) < .001 else value


def seconds(event):
    if isinstance(event, (float, int)):
        return float(event)
    for name in ('master_seconds', 'audio_seconds', 'time_seconds', 'project_seconds'):
        if name in event:
            return float(event[name])
    raise ValueError('No accepted audio coordinate')


def inside(times, spans):
    result = np.zeros(len(times), dtype=bool)
    for start, end in spans:
        result |= (times >= start) & (times < end)
    return result


def normalized(track, reference):
    support = [[float(a), float(b)] for a, b in track['reference_support_seconds']]
    if not support:
        raise ValueError('Missing accepted support')
    tempo = [{'time': seconds(e), 'bpm': nominal(e.get('bpm_quarter', e.get('bpm', e.get('quarter_bpm'))))}
             for e in reference.get('tempo_events', [])]
    if not tempo:
        tempo = [{'time': min(support[0][0], float(reference['first_beat_source_seconds'])),
                  'bpm': nominal(reference['quarter_bpm'])}]
    tempo.sort(key=lambda e: e['time'])
    meters = [{'time': seconds(e), 'numerator': int(e['numerator']), 'denominator': int(e['denominator'])}
              for e in reference.get('meter_events', [])]
    if not meters:
        meter = reference['meter']
        meters = [{'time': support[0][0], 'numerator': int(meter['numerator']), 'denominator': int(meter['denominator'])}]
    meters.sort(key=lambda e: e['time'])
    field = next((name for name in ['quarter_times_seconds', 'quarter_beats_seconds', 'quarter_beats_audio_seconds',
                                    'beats_seconds', 'beat_times_seconds', 'quarter_events'] if name in reference), None)
    if field is None:
        raise ValueError('No accepted quarter timestamps')
    quarters = np.array(sorted(set(seconds(e) for e in reference[field])), dtype=float)
    quarters = quarters[inside(quarters, support)]
    bar_field = next((name for name in ['downbeats_seconds', 'bar_starts_seconds', 'bar_events'] if name in reference), None)
    bars = (np.array(sorted(set(seconds(e) for e in reference[bar_field])), dtype=float) if bar_field else
            np.array([seconds(e) for e in reference.get('quarter_events', []) if isinstance(e, dict) and (e.get('bar_start') or e.get('accent'))]))
    bars = bars[inside(bars, support)]
    if len(quarters) < 2:
        raise ValueError('Insufficient approved quarter timing')
    states, segments = [], []
    for start, end in support:
        boundaries = sorted({start, end} | {e['time'] for e in tempo + meters if start < e['time'] < end})
        for left, right in zip(boundaries, boundaries[1:]):
            t = [e for e in tempo if e['time'] <= left + 1e-8]
            m = [e for e in meters if e['time'] <= left + 1e-8]
            if not t or not m:
                raise ValueError('No inherited reference state at source start')
            state = {'start': left, 'end': right, 'bpm': t[-1]['bpm'],
                     'numerator': m[-1]['numerator'], 'denominator': m[-1]['denominator']}
            if states and states[-1]['end'] == left and all(states[-1][key] == state[key] for key in ('bpm', 'numerator', 'denominator')):
                states[-1]['end'] = right
            else:
                states.append(state)
        for i, event in enumerate(tempo):
            left = max(start, event['time']); right = min(end, tempo[i+1]['time'] if i+1 < len(tempo) else end)
            if right > left:
                segment = {'start_seconds': left, 'end_seconds': right, 'quarter_bpm': event['bpm']}
                if segments and segments[-1]['end_seconds'] == left and segments[-1]['quarter_bpm'] == event['bpm']:
                    segments[-1]['end_seconds'] = right
                else:
                    segments.append(segment)
    transitions = [{'time': right['start_seconds'], 'left_bpm': left['quarter_bpm'],
                    'right_bpm': right['quarter_bpm'], 'left_start': left['start_seconds'], 'right_end': right['end_seconds']}
                   for left, right in zip(segments, segments[1:]) if abs(left['end_seconds'] - right['start_seconds']) < 1e-7]
    role = 'variable' if transitions else 'meter_control' if any(
        (s['numerator'], s['denominator']) != (states[0]['numerator'], states[0]['denominator']) for s in states) else 'fixed_control'
    return {'support': support, 'quarters': quarters.tolist(), 'bars': bars.tolist(), 'states': states,
            'segments': segments, 'transitions': transitions, 'initial_bpm': segments[0]['quarter_bpm'],
            'quarter_field': field, 'role': role, 'additional_offset_applied_seconds': 0,
            'reference_clock_interpretation_not_independent_millisecond_truth': True}


def coordinate(times, ref):
    times = np.asarray(times, dtype=float)
    quarters = np.asarray(ref['quarters'])
    result = np.interp(times, quarters, np.arange(len(quarters), dtype=float))
    left = times < quarters[0]; right = times > quarters[-1]
    result[left] = (times[left] - quarters[0]) * ref['states'][0]['bpm'] / 60.
    result[right] = len(quarters)-1 + (times[right] - quarters[-1]) * ref['states'][-1]['bpm'] / 60.
    return result


def arrays(times, ref):
    bpm = np.full(len(times), np.nan); state_index = np.full(len(times), -1, dtype=int)
    for index, state in enumerate(ref['states']):
        use = (times >= state['start']) & (times < state['end'])
        bpm[use] = state['bpm']; state_index[use] = index
    return bpm, state_index, inside(times, ref['support'])


def reading_parameters(reading, state):
    kind = reading['kind']; compound = state['denominator'] == 8 and state['numerator'] % 3 == 0
    if kind == 'constant':
        return reading['factor'], reading['offset']
    if kind == 'denominator':
        return state['denominator'] / 4., None
    if kind == 'compound_large':
        return (2/3, None) if compound else (1., 0.)
    if kind == 'compound_binary':
        return (4/3, None) if compound else (1., 0.)
    if kind == 'pair_grouping':
        return (.5, None) if state['denominator'] == 4 and state['numerator'] >= 4 and state['numerator'] % 2 == 0 else (1., 0.)
    if kind == 'triple_grouping':
        if compound:
            return 2/3, None
        return (1/3, None) if state['denominator'] == 4 and state['numerator'] % 3 == 0 else (1., 0.)
    raise ValueError(kind)


def templates(ref, readings):
    output = []
    quarter_times = np.asarray(ref['quarters']); bars = np.asarray(ref['bars'])
    for reading in readings:
        states = []
        for state in ref['states']:
            factor, offset = reading_parameters(reading, state)
            anchor_used = False
            if offset is None:
                available = bars[(bars >= state['start'] - 1e-8) & (bars < state['end'] - 1e-8)]
                if len(available):
                    anchor = float(available[0]); anchor_used = True
                else:
                    available = quarter_times[(quarter_times >= state['start'] - 1e-8) & (quarter_times < state['end'] - 1e-8)]
                    anchor = float(available[0]) if len(available) else state['start']
                offset = float((coordinate(np.array([anchor]), ref)[0] * factor) % 1.)
            states.append({**state, 'factor': factor, 'offset': offset, 'pulse_bpm': state['bpm'] * factor,
                           'bar_anchor_used': anchor_used})
        output.append({'name': reading['name'], 'states': states,
                       'rule_derived_not_each_individually_listening_confirmed': True})
    return output
