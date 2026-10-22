"""Independent provider-event/grid scoring. This module never fits a map."""
from pathlib import Path
import json
import hashlib
import math
import sys
import numpy as np

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[4]
sys.path.insert(0, str(ROOT))
from experiments.continuous_beat_map_v1.map import grid, sections, validate

TOLERANCES = [.01, .02, .03, .07]
HALO = .07


def geometry(prediction, duration):
    """Check finite domains as well as the preserved native continuity contract."""
    if prediction.get('status') != 'map':
        return {'legal': False, 'errors': ['no_source_clock']}
    try:
        initial = prediction['initial']
        assert abs(float(prediction['duration_seconds']) - duration) < 1e-7
        assert math.isfinite(duration) and duration > 0
        assert math.isfinite(initial['bar_zero_source_seconds']) and initial['bar_zero_source_seconds'] <= 1e-8
        states = [initial] + prediction['events']
        for state in states:
            if 'bpm' in state:
                assert math.isfinite(state['bpm']) and 30 <= state['bpm'] <= 400
            if 'numerator' in state:
                assert isinstance(state['numerator'], int) and state['numerator'] > 0
                assert isinstance(state['denominator'], int) and state['denominator'] > 0
            for key in ['time', 'quarter']:
                if key in state:
                    assert math.isfinite(state[key])
            if 'time' in state:
                assert 0 < state['time'] < duration
        result = validate(prediction)
        result['legal'] = bool(result['legal'] and result['continuous_source_coverage'])
        return result
    except Exception as error:
        return {'legal': False, 'errors': ['invalid_native_geometry', type(error).__name__, str(error)]}


def matching(reference, predicted, tolerance):
    """Maximum-cardinality ordered one-to-one matching at an absolute tolerance."""
    i, j, residual = 0, 0, []
    while i < len(reference) and j < len(predicted):
        delta = predicted[j] - reference[i]
        if abs(delta) <= tolerance + 1e-9:
            residual.append(float(delta))
            i += 1
            j += 1
        elif delta < -tolerance:
            j += 1
        else:
            i += 1
    tp, nr, npred = len(residual), len(reference), len(predicted)
    # Empty/empty change lists agree; pulse references themselves are nonempty.
    return {'true_positive': tp, 'reference_count': nr, 'prediction_count': npred,
            'precision': tp / npred if npred else (1. if nr == 0 else 0.),
            'recall': tp / nr if nr else 1.,
            'f1': 2 * tp / (nr + npred) if nr + npred else 1.}


def event_score(reference, predicted, duration, available=True):
    ref = np.asarray(reference, dtype=float)
    if len(ref) == 0:
        return None
    # One fixed halo for all four tolerances avoids losing edge events simply
    # because a slightly early/late estimate crosses the annotation envelope.
    support = [max(0., float(ref[0]) - HALO), min(duration, float(ref[-1]) + HALO)]
    pred = np.asarray(predicted, dtype=float)
    pred = pred[(pred >= support[0]) & (pred <= support[1]) & (pred >= 0) & (pred < duration)]
    result = {'annotation_envelope_seconds': [float(ref[0]), float(ref[-1])],
              'scoring_envelope_with_fixed_halo_seconds': support, 'valid_map_available': available,
              'tolerances_seconds': {str(tol): matching(ref, pred, tol) for tol in TOLERANCES}}
    if len(pred):
        right = np.searchsorted(pred, ref)
        left = np.clip(right - 1, 0, len(pred) - 1)
        right = np.clip(right, 0, len(pred) - 1)
        nearest = np.where(np.abs(pred[left] - ref) <= np.abs(pred[right] - ref), pred[left], pred[right])
        signed = nearest - ref
        result['nearest_tick_absolute_residual_seconds'] = {
            'median': float(np.median(np.abs(signed))), 'p95': float(np.quantile(np.abs(signed), .95)),
            'max': float(np.max(np.abs(signed)))}
        part = max(1, len(ref) // 4)
        result['nearest_tick_signed_residual_shift_last_minus_first_quartile_seconds'] = float(
            np.median(signed[-part:]) - np.median(signed[:part]))
    else:
        result['nearest_tick_absolute_residual_seconds'] = None
        result['nearest_tick_signed_residual_shift_last_minus_first_quartile_seconds'] = None
    return result


def tempo_score(prediction, reference, support, pulse_mode):
    """Duration-weighted agreement with self-consistent provider tempo labels."""
    left, right = support
    refs = reference['provider_tempo_events']
    sects = sections(prediction)
    bounds = sorted({left, right} | {float(x['start']) for x in refs if left < x['start'] < right}
                    | {float(x['start']) for x in sects if left < x['start'] < right})
    total, absolute, logarithmic, within1, within3 = 0., 0., 0., 0., 0.
    for a, b in zip(bounds, bounds[1:]):
        middle = (a + b) / 2
        valid_ref = [x for x in refs if x['start'] <= middle]
        valid_pred = [x for x in sects if x['start'] <= middle < x['end']]
        if not valid_ref or not valid_pred:
            continue
        ref, pred = valid_ref[-1], valid_pred[-1]
        predicted_bpm = pred['bpm'] * (pred['denominator'] / 4 if pulse_mode else 1.)
        ratio, weight = predicted_bpm / ref['bpm'], b - a
        total += weight
        absolute += abs(ratio - 1) * weight
        logarithmic += abs(math.log2(ratio)) * weight
        within1 += (abs(ratio - 1) <= .01 + 1e-12) * weight
        within3 += (abs(ratio - 1) <= .03 + 1e-12) * weight
    duration = right - left
    pred_changes = []
    old = prediction.get('initial')
    if old:
        bpm, denominator = old['bpm'], old['denominator']
        for event in prediction['events']:
            new_bpm, new_d = event.get('bpm', bpm), event.get('denominator', denominator)
            before = bpm * (denominator / 4 if pulse_mode else 1.)
            after = new_bpm * (new_d / 4 if pulse_mode else 1.)
            if left < event['time'] < right and abs(before - after) > 1e-9:
                pred_changes.append(event['time'])
            bpm, denominator = new_bpm, new_d
    ref_changes = [float(new['start']) for old, new in zip(refs, refs[1:])
                   if left < new['start'] < right and abs(old['bpm'] - new['bpm']) > 1e-9]
    changes = {str(tol): matching(ref_changes, pred_changes, tol) for tol in [.07, 1., 2.]}
    if not sects:
        for values in changes.values():
            values.update(precision=0., recall=0., f1=0.)
    return {'scored_duration_seconds': duration, 'map_covered_duration_seconds': total,
            'mean_absolute_relative_tempo_error': absolute / total if total else None,
            'mean_absolute_log2_tempo_error': logarithmic / total if total else None,
            'duration_fraction_within_1_percent': within1 / duration if duration else 0.,
            'duration_fraction_within_3_percent': within3 / duration if duration else 0.,
            'provider_change_count': len(ref_changes), 'predicted_change_count': len(pred_changes),
            'provider_change_event_agreement': changes,
            'meaning': 'Provider tempo-label agreement; no certification of musical intent or native ideal map.'}


def score(receipt, capability, reference):
    duration = capability['whole_source_duration_seconds']
    raw = receipt.get('prediction') or {'status': 'no_source_clock'}
    native = geometry(raw, duration)
    available = bool(native['legal'])
    prediction = raw if available else {'status': 'no_source_clock', 'duration_seconds': duration, 'events': []}
    times = np.asarray(reference['times'], dtype=float)
    in_source = (times >= 0) & (times < duration)
    times = times[in_source]
    result = {'id': receipt['id'], 'method': receipt['method'], 'condition': receipt['condition'],
              'status': receipt['status'], 'native_contract_independent_check': native,
              'valid_map_available': available,
              'provider_pulse': event_score(times, grid(prediction, 'beat'), duration, available),
              'literal_quarter': event_score(times, grid(prediction, 'quarter'), duration, available),
              'provider_downbeat': None, 'provider_tempo_notated_pulse': None, 'provider_tempo_literal_quarter': None,
              'written_meter_accuracy': None, 'native_ideal_map_C_P': None,
              'intentional_change_correctness': None,
              'declaration_count_whole_source': len(prediction['events']) if available else None,
              'whole_source_duration_seconds': duration}
    if capability['capabilities']['provider_downbeat_grid']:
        positions = np.asarray(reference['positions'], dtype=int)[in_source]
        result['provider_downbeat'] = event_score(times[positions == 1], grid(prediction, 'bar'), duration, available)
    if capability['capabilities']['provider_tempo_grid']:
        result['provider_tempo_notated_pulse'] = tempo_score(prediction, reference, capability['evaluation_support'], True)
        result['provider_tempo_literal_quarter'] = tempo_score(prediction, reference, capability['evaluation_support'], False)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--prediction', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.prediction.read_text())
    caps = {x['id']: x for x in map(json.loads, (RUN / 'qualification/metric-capabilities.jsonl').read_text().splitlines())}
    reference_path = RUN / 'qualification/evaluation-references' / (receipt['id'] + '.json')
    freeze = json.loads((RUN / 'inference-freeze.json').read_text())
    if hashlib.sha256(reference_path.read_bytes()).hexdigest() != freeze['evaluation_reference_sha256'][str(reference_path.relative_to(RUN))]:
        raise RuntimeError('Frozen evaluation reference changed')
    reference = json.loads(reference_path.read_text())
    result = score(receipt, caps[receipt['id']], reference)
    destination = RUN / 'scores' / receipt['condition'] / receipt['method'] / (receipt['id'] + '.json')
    if destination.exists():
        raise RuntimeError('Score overwrite forbidden')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.writing')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(destination)


if __name__ == '__main__':
    main()
