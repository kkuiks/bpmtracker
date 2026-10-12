"""A musical coordinate with continuous physical time, never independent phases."""
from __future__ import annotations
import math
import numpy as np

EPS = 1e-8

def sections(prediction):
    if prediction.get('status') != 'map': return []
    initial = prediction['initial']
    bpm, n, d = initial['bpm'], initial['numerator'], initial['denominator']
    anchor_time = float(initial['bar_zero_source_seconds'])
    anchor_q = bar_q = 0.
    start = 0.; result = []
    for event in prediction['events'] + [{'time': prediction['duration_seconds']}]:
        end = float(event['time'])
        if end > start + EPS:
            quarter = anchor_q + (start-anchor_time)*bpm/60.
            bar_start = bar_q + math.floor((quarter-bar_q+EPS)/(n*4/d))*(n*4/d)
            result.append({'start': start, 'end': end, 'bpm': bpm,
                           'phase': start-(quarter-bar_start)*60/bpm,
                           'numerator': n, 'denominator': d,
                           'anchor_quarter': anchor_q, 'anchor_time': anchor_time,
                           'bar_quarter': bar_q})
        if 'quarter' not in event: break
        anchor_time, anchor_q = end, float(event['quarter'])
        bpm = float(event.get('bpm', bpm))
        if 'numerator' in event:
            n, d, bar_q = event['numerator'], event['denominator'], anchor_q
        start = end
    return result

def validate(prediction):
    if prediction.get('status') != 'map':
        return {'source_map_available': False, 'legal': False, 'errors': ['no_source_clock']}
    initial = prediction['initial']; bpm = initial['bpm']
    n, d = initial['numerator'], initial['denominator']
    time, q = initial['bar_zero_source_seconds'], 0.
    bar_q, last_time, errors, residuals = 0., 0., [], []
    for index, event in enumerate(prediction['events']):
        expected = time+(event['quarter']-q)*60/bpm
        old_beat = (event['quarter']-bar_q)*d/4
        residuals.append(abs(expected-event['time']))
        if abs(expected-event['time']) > 1e-7: errors.append([index, 'discontinuous_time'])
        if abs(old_beat-round(old_beat)) > 1e-7: errors.append([index, 'not_old_beat'])
        if event['time'] <= last_time+EPS: errors.append([index, 'nonincreasing_event'])
        if event.get('bpm', bpm) == bpm and (event.get('numerator', n), event.get('denominator', d)) == (n,d):
            errors.append([index, 'redundant_event'])
        time, q, last_time = event['time'], event['quarter'], event['time']
        bpm = event.get('bpm', bpm)
        if 'numerator' in event:
            n, d, bar_q = event['numerator'], event['denominator'], q
    return {'source_map_available': True, 'legal': not errors, 'errors': errors,
            'max_continuity_residual_seconds': max(residuals, default=0.),
            'event_count': len(prediction['events']), 'free_phase_parameters_after_start': 0,
            'continuous_source_coverage': bool(sections(prediction)) and
                 abs(sum(s['end']-s['start'] for s in sections(prediction))-prediction['duration_seconds']) < 1e-7}

def grid(prediction, kind='beat'):
    result = []
    for section in sections(prediction):
        bpm, n, d = section['bpm'], section['numerator'], section['denominator']
        period = 60/bpm * (n*4/d if kind == 'bar' else 4/d if kind == 'beat' else 1.)
        phase = section['phase']
        first = phase+math.ceil((section['start']-phase-EPS)/period)*period
        ticks = first+np.arange(max(0, math.ceil((section['end']-first-EPS)/period)))*period
        result.extend(ticks.tolist())
    return np.asarray(result, dtype=float)

def as_legacy_prediction(prediction, notated=False):
    # Diagnostic adapter: primary prior-study scores compared quarter pulse clocks.
    accepted = []
    for section in sections(prediction):
        period = 60/section['bpm']
        factor = section['denominator']/4 if notated else 1.
        accepted.append({'start': section['start'], 'end': section['end'],
                         'bpm': section['bpm']*factor, 'phase': section['phase'],
                         'clock_index': len(accepted)})
    return {'accepted': accepted, 'duration': prediction['duration_seconds'], 'status':'NATIVE_CONTINUOUS'}
