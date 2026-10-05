"""Reference-explicit grid diagnostics. Never align, rescale or shift predictions."""
from __future__ import annotations

import math
import numpy as np


def _times(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(np.diff(values) <= 0):
        raise ValueError('times must be finite, one dimensional and strictly increasing')
    return values


def _tolerance(value):
    if not math.isfinite(value) or value < 0:
        raise ValueError('tolerance must be finite and nonnegative')


NUMERICAL_BOUNDARY_POLICY = 'inclusive tolerance plus8ULP of compared values, tolerance and1.0; no musical-window change'


def within_tolerance(first, second, tolerance):
    """Compare scalar finite endpoints with only float-representation allowance.

    Using endpoints retains the arithmetic scale at large source origins;
    comparing an already-subtracted error with zero would lose that scale.
    The one-unit ULP floor matches the declared-map evaluator convention. No
    millisecond/rate allowance is added and input values remain unchanged.
    """
    _tolerance(tolerance)
    first, second, tolerance = float(first), float(second), float(tolerance)
    if not math.isfinite(first) or not math.isfinite(second):
        raise ValueError('comparison endpoints must be finite')
    margin = 8 * max(math.ulp(value) for value in (first, second, tolerance, 1.))
    return abs(first-second) <= tolerance + margin


def _errors(errors):
    values = np.asarray(errors, dtype=float)
    if not len(values):
        return None
    return {'signed_median_seconds': float(np.median(values)),
            'absolute_median_seconds': float(np.median(abs(values))),
            'absolute_p95_seconds': float(np.percentile(abs(values), 95)),
            'absolute_max_seconds': float(np.max(abs(values))),
            'first_signed_error_seconds': float(values[0]),
            'last_signed_error_seconds': float(values[-1]),
            'last_minus_first_error_seconds': float(values[-1] - values[0])}


def _counts(tp, reference_count, prediction_count):
    precision = tp / prediction_count if prediction_count else (1. if not reference_count else 0.)
    recall = tp / reference_count if reference_count else 1.
    return {'true_positives': tp, 'false_positives': prediction_count-tp,
            'false_negatives': reference_count-tp, 'precision': precision,
            'recall': recall, 'f1': 2*precision*recall/(precision+recall) if precision+recall else 0.}


def indexed_grid_metrics(reference_events, predicted_events, *, origin_status='unanchored',
                         time_tolerance_seconds=.02):
    """Compare identical musical indices only when their shared origin is explicit.

    Each event is {index, time_seconds}. An input index may be fractional (e.g.
    subdivisions). Origin certification belongs to the caller; nearest-event
    alignment, candidate-relative index zero, and reference-fitted offsets do not
    qualify as a shared explicit origin. Unmatched indices stay errors.
    """
    _tolerance(time_tolerance_seconds)
    ref = _times([e['time_seconds'] for e in reference_events])
    pred = _times([e['time_seconds'] for e in predicted_events])
    ri = _times([e['index'] for e in reference_events])
    pi = _times([e['index'] for e in predicted_events])
    result = {'status': origin_status, 'reference_count': len(ref), 'prediction_count': len(pred),
              'alignment_applied': False, 'time_tolerance_seconds': time_tolerance_seconds,
              'numeric_boundary_policy': NUMERICAL_BOUNDARY_POLICY}
    if origin_status != 'shared_explicit_origin':
        result.update({'status': 'unanchored', 'grid_errors': None,
                       'reason': 'Shared musical index origin is not independently established.'})
        return result
    reference = dict(zip(ri, ref)); prediction = dict(zip(pi, pred))
    common = sorted(reference.keys() & prediction.keys())
    errors = np.array([prediction[i]-reference[i] for i in common])
    result.update({'matched_index_count': len(common),
                   'missing_indices': sorted(reference.keys()-prediction.keys()),
                   'extra_indices': sorted(prediction.keys()-reference.keys()),
                   'grid_errors': _errors(errors),
                   'index_and_time_scores': _counts(sum(within_tolerance(reference[i],prediction[i],time_tolerance_seconds) for i in common),
                                                   len(ref), len(pred)),
                   'index_errors': [{'index': float(i), 'signed_error_seconds': float(e)}
                                    for i,e in zip(common,errors)]})
    return result


def nearest_event_diagnostics(reference_times, predicted_times, tolerance=.02):
    """Ordered one-to-one timing matching, without establishing musical indices."""
    _tolerance(tolerance)
    ref, pred = _times(reference_times), _times(predicted_times)
    i = j = 0; errors = []
    while i < len(ref) and j < len(pred):
        delta = pred[j]-ref[i]
        if within_tolerance(ref[i], pred[j], tolerance):
            errors.append(delta); i += 1; j += 1
        elif delta < 0:
            j += 1
        else:
            i += 1
    return {'status': 'event_matching_not_index_certification', 'alignment_applied': False,
            'tolerance_seconds': tolerance, 'numeric_boundary_policy': NUMERICAL_BOUNDARY_POLICY, **_counts(len(errors),len(ref),len(pred)),
            'matched_event_errors': _errors(errors)}


def temporal_span_coverage(reference_times, start_seconds, end_seconds):
    """Coverage of source duration only; this does not count correct beats."""
    times = _times(reference_times)
    if not np.isfinite([start_seconds,end_seconds]).all() or end_seconds < start_seconds:
        raise ValueError('invalid support span')
    covered = (times >= start_seconds) & (times <= end_seconds)
    return {'kind': 'source_time_span_only_not_correct_pulse_coverage',
            'reference_event_count': len(times), 'inside_span_count': int(covered.sum()),
            'fraction': float(covered.mean()) if len(times) else None}


def pulse_level_diagnostics(reference_times, predicted_times):
    """Local density diagnostics against a declared reference level, no octave repair."""
    ref, pred = _times(reference_times), _times(predicted_times)
    if len(ref) < 2:
        return {'status': 'insufficient_reference', 'reference_interval_count': 0}
    counts = np.diff(np.searchsorted(pred,ref,side='left'))
    return {'status': 'diagnostic_reference_level_not_certified_authored_intent',
            'reference_interval_count': len(counts),
            'predicted_events_per_reference_interval': counts.tolist(),
            'empty_interval_fraction': float(np.mean(counts==0)),
            'single_event_interval_fraction': float(np.mean(counts==1)),
            'multiple_event_interval_fraction': float(np.mean(counts>1)),
            'level_transition_count': int(np.count_nonzero(np.diff(counts))),
            'warning': 'Boundary jitter and phase also affect density; this is not a tempo-switch verdict.'}


def _maximum_matching(reference, prediction, compatible):
    # Small event lists: a deterministic augmenting-path bipartite match prevents
    # a plausible early pair from consuming the only valid mate for another event.
    owners = {}
    def assign(i, seen):
        choices = sorted((j for j in range(len(prediction)) if compatible(reference[i],prediction[j])),
                         key=lambda j:(abs(reference[i]['source_seconds']-prediction[j]['source_seconds']),j))
        for j in choices:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or assign(owners[j],seen):
                owners[j] = i
                return True
        return False
    for i in range(len(reference)):
        assign(i,set())
    return sorted((i,j) for j,i in owners.items())


def tempo_change_metrics(reference_changes, predicted_changes, *, time_tolerance_seconds=.1,
                         rate_tolerance_bpm=.1):
    """Require timing, change type and both rates; None means unknown, not no changes."""
    _tolerance(time_tolerance_seconds); _tolerance(rate_tolerance_bpm)
    if reference_changes is None:
        return {'status':'unscored_missing_reference'}
    for events in (reference_changes,predicted_changes):
        _times([e['source_seconds'] for e in events])
        for e in events:
            if e['type'] not in ('step','ramp_start','ramp_end'):
                raise ValueError('unsupported tempo change type')
            if not np.isfinite([e['bpm_before'],e['bpm_after']]).all() or min(e['bpm_before'],e['bpm_after']) <= 0:
                raise ValueError('rates must be finite and positive')
    def timing(a,b):
        return within_tolerance(a['source_seconds'],b['source_seconds'],time_tolerance_seconds)
    def complete(a,b):
        return (timing(a,b) and a['type']==b['type']
                and np.sign(a['bpm_after']-a['bpm_before']) == np.sign(b['bpm_after']-b['bpm_before'])
                and within_tolerance(a['bpm_before'],b['bpm_before'],rate_tolerance_bpm)
                and within_tolerance(a['bpm_after'],b['bpm_after'],rate_tolerance_bpm))
    pairs = _maximum_matching(reference_changes,predicted_changes,complete)
    return {'status':'scored', 'time_tolerance_seconds':time_tolerance_seconds,
            'rate_tolerance_bpm':rate_tolerance_bpm, 'numeric_boundary_policy':NUMERICAL_BOUNDARY_POLICY,
            'full_change_scores':_counts(len(pairs),len(reference_changes),len(predicted_changes)),
            'timing_only_match_count':len(_maximum_matching(reference_changes,predicted_changes,timing)),
            'matches':[{'reference_index':i,'prediction_index':j,
                        'signed_time_error_seconds':predicted_changes[j]['source_seconds']-reference_changes[i]['source_seconds']}
                       for i,j in pairs]}


def meter_change_metrics(reference_changes, predicted_changes, *, time_tolerance_seconds=.1):
    """Match explicit numerator/denominator and boundary; never infer missing meter."""
    _tolerance(time_tolerance_seconds)
    if reference_changes is None:
        return {'status':'unscored_missing_reference'}
    if predicted_changes is None:
        return {'status':'unresolved_prediction', **_counts(0,len(reference_changes),0)}
    for events in (reference_changes,predicted_changes):
        _times([e['source_seconds'] for e in events])
        for e in events:
            if any(not isinstance(e[k],int) or isinstance(e[k],bool) or e[k] <= 0 for k in ('numerator','denominator')):
                raise ValueError('meter must be explicitly positive integers')
    pairs = _maximum_matching(reference_changes,predicted_changes,
                              lambda a,b:within_tolerance(a['source_seconds'],b['source_seconds'],time_tolerance_seconds)
                              and (a['numerator'],a['denominator'])==(b['numerator'],b['denominator']))
    return {'status':'scored', 'time_tolerance_seconds':time_tolerance_seconds,
            'numeric_boundary_policy':NUMERICAL_BOUNDARY_POLICY, **_counts(len(pairs),len(reference_changes),len(predicted_changes))}
