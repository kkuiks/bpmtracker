"""Reference-explicit diagnostics for frozen predictions; no inference or alignment."""
from __future__ import annotations

import numpy as np


def tempo_rate_diagnostics(reference, clock):
    """Integrate rate error over declared support, excluding uncovered time explicitly.

    Predicted pulse rates are compared to reference quarters as a diagnostic
    hypothesis only. Half/double-rate categories use a disclosed 1% ratio band.
    """
    events = reference.get('tempo_events')
    if not events:
        return {'status': 'unscored_missing_tempo_reference'}
    lo, hi = map(float, reference['evaluation_support_seconds'])
    if not np.isfinite([lo, hi]).all() or hi <= lo:
        raise ValueError('positive finite evaluation support required')
    if clock is None or not clock.get('segments'):
        return {'status': 'no_tempo_map', 'support_seconds': [lo, hi],
                'covered_duration_fraction': 0., 'uncovered_duration_seconds': hi-lo}
    segments = clock['segments']
    boundaries = sorted({lo, hi, *[float(e['time_seconds']) for e in events if lo < e['time_seconds'] < hi],
                         *[float(s[k]) for s in segments for k in ('start_seconds','end_seconds') if lo < s[k] < hi]})
    spans = []
    for a, b in zip(boundaries, boundaries[1:]):
        mid = (a+b)/2
        ref = next((e for e in reversed(events) if e['time_seconds'] <= mid), None)
        pred = next((s for s in segments if s['start_seconds'] <= mid < s['end_seconds']), None)
        if ref is None or pred is None:
            continue
        rate = float(pred['pulse_rate_per_minute']); truth = float(ref['bpm_quarter'])
        if not np.isfinite([rate, truth]).all() or min(rate,truth) <= 0:
            raise ValueError('positive finite tempo rates required')
        spans.append({'start_seconds':a, 'end_seconds':b, 'predicted_pulse_rate':rate,
                      'reference_quarter_bpm':truth, 'ratio':rate/truth, 'absolute_error_bpm':abs(rate-truth)})
    duration = sum(s['end_seconds']-s['start_seconds'] for s in spans)
    def fraction(predicate):
        return sum(s['end_seconds']-s['start_seconds'] for s in spans if predicate(s))/duration if duration else None
    return {'status':'scored_under_quarter_pulse_hypothesis', 'shared_musical_index_origin':'unverified',
            'support_seconds':[lo,hi], 'covered_duration_seconds':duration,
            'covered_duration_fraction':duration/(hi-lo), 'uncovered_duration_seconds':hi-lo-duration,
            'time_weighted_mae_bpm':sum((s['end_seconds']-s['start_seconds'])*s['absolute_error_bpm'] for s in spans)/duration if duration else None,
            'within_absolute_bpm':{str(t):fraction(lambda s:s['absolute_error_bpm']<=t) for t in (.1,.5,1.)},
            'ratio_relative_tolerance':.01,
            'half_rate_duration_fraction':fraction(lambda s:abs(s['ratio']/.5-1)<=.01),
            'same_rate_duration_fraction':fraction(lambda s:abs(s['ratio']-1)<=.01),
            'double_rate_duration_fraction':fraction(lambda s:abs(s['ratio']/2-1)<=.01),
            'segments':spans, 'drift_status':'unscored_without_shared_musical_index_origin'}
