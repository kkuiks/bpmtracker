"""Frozen map evaluation accepting equivalent declarations, never gratuitous switches.

The shared legacy score is retained as a diagnostic. Only event classification
and its resulting eight-second stability penalty differ. The four-second event
matching tolerance belongs to evaluation, not to the inference architecture.
"""
from __future__ import annotations
import numpy as np
from experiments.continuous_beat_map_v1.evaluate import (
    score as literal_score, native_arrays, validity)
from experiments.continuous_beat_map_v1.map import sections
from experiments.multiple_rhythm_continuity_v1.references import inside
from experiments.multiple_rhythm_continuity_v1.common import PRIMARY_READINGS


def classify(prediction, reference):
    segments = sections(prediction)
    records = []
    for event in prediction.get('events', []):
        time = event['time']
        record = dict(event)
        if not inside(np.asarray([time]), reference['support'])[0]:
            record['classification'] = 'OUTSIDE_APPROVED_SCOPE'
            records.append(record)
            continue
        before = next(s for s in reversed(segments) if s['start'] < time - 1e-8)
        after = next(s for s in segments if s['start'] >= time - 1e-8)

        def acceptable(section, where):
            fields = {k: np.asarray([section[k]], float)
                      for k in ['bpm', 'phase', 'numerator', 'denominator']}
            pulse, bar, _, _, support = validity(fields, np.asarray([where]), reference)
            return bool(support[0] and pulse[:, 0].any() and bar[0])

        matches = []
        for left, right in zip(reference['states'], reference['states'][1:]):
            boundary = right['start']
            old_before = acceptable(before, boundary - 1e-5)
            old_after = acceptable(before, boundary + 1e-5)
            new_after = acceptable(after, boundary + 1e-5)
            literal_kind = (('bpm' in event and abs(left['bpm']-right['bpm']) > 1e-8)
                            or ('numerator' in event and
                                (left['numerator'], left['denominator']) !=
                                (right['numerator'], right['denominator'])))
            if abs(time-boundary) <= 4 and old_before and not old_after and new_after:
                matches.append({'reference_time': boundary, 'error_seconds': time-boundary,
                                'literal_declaration_kind_matches': literal_kind})
        if matches:
            record.update(classification='MUSICAL_CHANGE', matches=matches)
        else:
            old_before = acceptable(before, time-1e-4)
            old_after = acceptable(before, time+1e-4)
            new_after = acceptable(after, time+1e-4)
            record.update(old_valid_before=old_before, old_still_valid_after=old_after,
                          new_valid_after=new_after)
            record['classification'] = ('UNNECESSARY_CHANGE' if old_after or old_before and new_after
                                        else 'RECOVERY' if new_after else 'UNSUPPORTED_CHANGE')
        records.append(record)
    return records


def score(prediction, reference):
    original = literal_score(prediction, reference)
    changes = classify(prediction, reference)
    times = np.arange(.025, max(b for _, b in reference['support']), .05)
    fields = native_arrays(prediction, times)
    pulse, bar, _, _, support = validity(fields, times, reference)
    joint = np.zeros(len(times), bool)
    for state in reference['states']:
        use = support & (times >= state['start']) & (times < state['end'])
        if use.any():
            counts = (pulse[:, use] & bar[use]).sum(axis=1)
            joint[use] = pulse[int(np.argmax(counts)), use] & bar[use]
    penalty = np.zeros(len(times), bool)
    for event in changes:
        if event['classification'] == 'UNNECESSARY_CHANGE':
            penalty |= (times >= event['time']) & (times < event['time']+8)
    details = []
    for right in reference['states'][1:]:
        boundary = right['start']
        matched = [m for e in changes for m in e.get('matches', [])
                   if abs(m['reference_time']-boundary) < 1e-7]
        best = min(matched, key=lambda m: abs(m['error_seconds'])) if matched else None
        details.append({'reference_time': boundary, 'success': best is not None,
                        'best_match': best})
    return {**original,
            'literal_kind_stable_native_map_fraction': original['stable_native_map_fraction'],
            'literal_kind_unnecessary_native_changes': original['unnecessary_native_changes'],
            'stable_native_map_fraction': float((joint & ~penalty & support).sum()/support.sum()),
            'native_changes': changes,
            'unnecessary_native_changes': sum(e['classification']=='UNNECESSARY_CHANGE' for e in changes),
            'unsupported_native_changes': sum(e['classification']=='UNSUPPORTED_CHANGE' for e in changes),
            'musical_native_changes': sum(e['classification']=='MUSICAL_CHANGE' for e in changes),
            'native_successful_boundaries': sum(d['success'] for d in details),
            'native_eligible_boundaries': len(details), 'native_boundary_details': details,
            'native_reading_set_unchanged': [r['name'] for r in PRIMARY_READINGS]}
