"""Score a saved human-review map after review, without revealing labels in the UI.

An accepted map is not automatically correct. Event matching cannot certify a
shared musical index origin. This evaluator never estimates alignment offsets.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from grid_metrics import nearest_event_diagnostics, meter_change_metrics
from inspect_inputs import sha256


def evaluate(session, reference, audio_path):
    source = session['source']
    info = sf.info(audio_path)
    if (source['sha256'] != sha256(audio_path) or source['sample_rate'] != info.samplerate
            or source['sample_frames'] != info.frames or source.get('source_frame_offset') != 0):
        raise ValueError('review must retain the identical source audio and sample zero')
    if reference.get('source_audio_sha256') not in (None, source['sha256']):
        raise ValueError('reference source audio mismatch')
    grid = session['map']['grid']
    indices = np.array([e['quarter_position'] for e in grid], dtype=float)
    times = np.array([e['source_seconds'] for e in grid], dtype=float)
    if (len(times) < 2 or not np.isfinite([indices, times]).all()
            or np.any(np.diff(indices) <= 0) or np.any(np.diff(times) <= 0)
            or times[0] < 0 or times[-1] > info.duration):
        raise ValueError('invalid review grid')
    q = np.arange(np.ceil(indices[0]), np.floor(indices[-1])+1)
    proposed = np.interp(q, indices, times)
    low, high = reference['evaluation_support_seconds']
    beats = proposed[(proposed >= low) & (proposed <= high)]
    truth = np.array(reference['beats_seconds'])
    truth = truth[(truth >= low) & (truth <= high)]
    meter_events = session['map'].get('meter_events', [])
    downbeats = []
    for quarter, time in zip(q, proposed):
        active = [e for e in meter_events if e['quarter_position'] <= quarter]
        if active:
            meter = active[-1]
            if meter['denominator'] != 4:
                raise ValueError('review supports explicit quarter-click meters only')
            if abs((quarter - meter['quarter_position']) % meter['numerator']) < 1e-8 and low <= time <= high:
                downbeats.append(time)
    reference_downbeats = reference.get('downbeats_seconds')
    scores = {'beats': {str(t): nearest_event_diagnostics(truth, beats, t) for t in (.02, .07)},
              'downbeats': {str(t): nearest_event_diagnostics(
                  [x for x in reference_downbeats if low <= x <= high], downbeats, t) for t in (.02, .07)}
                  if reference_downbeats is not None and meter_events else None}
    prefix_known = bool(meter_events) and meter_events[0]['quarter_position'] <= indices[0]
    changes = [{'source_seconds': float(np.interp(e['quarter_position'], indices, times)),
                'numerator': e['numerator'], 'denominator': e['denominator']}
               for prev, e in zip(meter_events, meter_events[1:])
               if indices[0] <= e['quarter_position'] <= indices[-1]
               and (prev['numerator'], prev['denominator']) != (e['numerator'], e['denominator'])]
    ref_changes = ([{'source_seconds': e['time_seconds'], 'numerator': e['numerator'], 'denominator': e['denominator']}
                    for prev, e in zip(reference['meter_events'], reference['meter_events'][1:])
                    if low < e['time_seconds'] < high
                    and (prev['numerator'], prev['denominator']) != (e['numerator'], e['denominator'])]
                   if reference_downbeats is not None else None)
    return {'schema_version': 1, 'alignment_or_octave_repair_applied': False,
            'source_identity_verified': True, 'user_accepted': bool(session.get('accepted')),
            'scores': scores, 'meter_changes': (meter_change_metrics(ref_changes, changes) if prefix_known else
                {'status': 'unresolved_prefix_meter', 'reason': 'The first manual meter starts after map support or is missing; a complete change sequence cannot be certified.'}),
            'indexed_grid': {'status': 'unanchored', 'reason': 'Review-local quarter zero is not an independently certified reference origin.'},
            'same_signature_restatements': 'Not counted as numerator/denominator changes; bar-reset correctness requires separate validation.',
            'review_elapsed_ms': session.get('review_elapsed_ms'),
            'correction_action_count': session.get('correction_action_count'),
            'candidate_application_count': session.get('candidate_application_count'),
            'undo_count': session.get('undo_count'),
            'measurement_status': session.get('measurement_status'),
            'warning': 'Correctness metrics and user acceptance are distinct; simulated sessions are not human effort measurements.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--audio', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('output must be new')
    result = evaluate(json.loads(args.session.read_text()), json.loads(args.reference.read_text()), args.audio)
    result['inputs'] = {k: {'path': str(v), 'sha256': sha256(v)} for k, v in
                       [('session', args.session), ('reference', args.reference), ('audio', args.audio)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(args.output)


if __name__ == '__main__':
    main()
