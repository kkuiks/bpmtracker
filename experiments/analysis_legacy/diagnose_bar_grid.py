"""C4: replace the pulse grid while holding saved downbeat evidence fixed.

Privileged reference-grid results are diagnostic controls, never automatic
meter accuracy. The unchanged decoder emits 2/3/4 input-pulse groups; it still
cannot declare a denominator or distinguish 3/4 from 6/8 by group count alone.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from decode_bar_structure import bar_path
from grid_metrics import nearest_event_diagnostics

DEFAULT_COHORT = Path('data/runs/music-map-contract/2026-09-26-v1/prediction-capabilities.json')
DEFAULT_REFINEMENTS = Path('data/runs/logic-maintenance/2026-09-26-v1/after-correctness/refinements-v2')
PARAMETERS = {'lengths': [4, 3, 2], 'change_penalty': 2., 'variables': [False, True]}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_bound(binding):
    path = Path(binding['path'])
    if sha(path) != binding['sha256']:
        raise ValueError(f'input changed: {path}')
    return json.loads(path.read_text())


def binding(path):
    return {'path': str(path), 'sha256': sha(path)}


def representability(meter_events):
    if not meter_events:
        return {'supported': False, 'reason': 'no_declared_meter'}
    lengths = sorted({Fraction(e['numerator'] * 4, e['denominator']) for e in meter_events})
    unsupported = [str(length) for length in lengths if length not in (2, 3, 4)]
    return {'supported': not unsupported,
            'quarter_lengths': [str(length) for length in lengths],
            'unsupported_quarter_lengths': unsupported,
            'meter_signature_inferred': False}


def compare_grids(predicted_grid, reference_grid, reference_downbeats, downbeat_logits, fps, support):
    lo, hi = support
    inputs = {'saved_grid': [float(t) for t in predicted_grid if lo <= t <= hi],
              'oracle_quarter_grid': [float(t) for t in reference_grid if lo <= t <= hi]}
    truth = [float(t) for t in reference_downbeats if lo <= t <= hi]
    results = {}
    for name, grid in inputs.items():
        results[name] = {'input_grid_seconds': grid, 'oracle': name == 'oracle_quarter_grid', 'decoders': {}}
        for variable in PARAMETERS['variables']:
            started = time.perf_counter()
            decoded = bar_path(grid, downbeat_logits, fps=fps, lengths=tuple(PARAMETERS['lengths']),
                               change_penalty=PARAMETERS['change_penalty'], variable=variable)
            elapsed = time.perf_counter() - started
            if decoded.get('pulse_times_changed', False) or any(t not in grid for t in decoded['downbeats_seconds']):
                raise AssertionError('bar decoder altered its input grid')
            scores = {str(tolerance): nearest_event_diagnostics(truth, decoded['downbeats_seconds'], tolerance)
                      for tolerance in (.02, .07)}
            results[name]['decoders']['variable' if variable else 'fixed'] = {
                'prediction': decoded, 'scores_to_supplied_bar_events': scores, 'elapsed_seconds': elapsed}
    return {'support_seconds': list(support), 'reference_downbeats_seconds': truth, 'arms': results,
            'intervention': 'grid timing, count, pulse level and coverage jointly; raw downbeat evidence unchanged',
            'quarter_or_meter_unit_inferred_by_decoder': False,
            'same_physical_evaluation_window': True, 'reference_used_to_align_saved_grid': False,
            'windowed_redecoding_may_differ_from_original_full_source_path': True}


def run(cohort_path, output_dir):
    cohort = json.loads(Path(cohort_path).read_text())
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('diagnostic output must be new or empty')
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for item in cohort['proposed_fixed_diagnostic_cohort']:
        if 'C4' not in item['planned_control_ids']:
            continue
        ref = read_bound(item['reference'])
        rep = representability(ref.get('meter_events'))
        reason = None
        if not rep['supported']:
            reason = 'reference_bar_lengths_outside_existing_decoder_vocabulary'
        if item['id'] == 'gmd_drummer6_session1_4':
            reason = 'supplied_midi_and_publisher_bar_labels_conflict_unresolved'
        for source in item['prediction_inputs']:
            core = read_bound(source)
            cases.append({'id': item['id'], 'model': source['model'], 'role': item['role'],
                          'core': source, 'reference': item['reference'],
                          'logits': {'path': core['source']['logits_path'], 'sha256': core['source']['logits_sha256']},
                          'representability': rep, 'blocked_reason': reason,
                          'reference_tier': item['reference_tier'],
                          'reference_caveats': item.get('reference_caveats')})
    manifest = {'control': 'C4', 'scope': 'fixed development diagnostic set, not independent accuracy',
                'cohort': binding(cohort_path), 'parameters': PARAMETERS, 'cases': cases,
                'sources': {name: sha(Path(__file__).with_name(name)) for name in
                            ('diagnose_bar_grid.py', 'decode_bar_structure.py', 'grid_metrics.py', 'run_beat_this.py')},
                'state': 'frozen_before_execution', 'model_inference_performed': False,
                'reference_assisted_controls_are_automatic_results': False}
    (output_dir/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    rows = []
    for case in cases:
        row = {key: case[key] for key in ('id', 'model', 'role', 'reference_tier', 'representability')}
        if case['blocked_reason']:
            row.update(status='not_executed', reason=case['blocked_reason'])
        else:
            core = read_bound(case['core']); ref = read_bound(case['reference'])
            if sha(case['logits']['path']) != case['logits']['sha256']:
                raise ValueError('logit cache changed')
            with np.load(case['logits']['path'], allow_pickle=False) as saved:
                downbeats = np.asarray(saved['downbeat'], dtype=float)
                fps = float(saved['fps'])
            if fps != core['source']['native_frame_rate']:
                raise ValueError('cache frame rate differs from source declaration')
            try:
                result = compare_grids(core['methods']['meter_free_clock']['prediction']['beats_seconds'],
                                       ref['beats_seconds'], ref['downbeats_seconds'], downbeats, fps,
                                       ref['evaluation_support_seconds'])
                row.update(status='executed_oracle_control', result=result)
            except ValueError as exc:
                row.update(status='diagnostic_failed', error=str(exc))
        rows.append(row)
        (output_dir/'report.json').write_text(json.dumps({'manifest_sha256': sha(output_dir/'manifest.json'),
            'rows': rows, 'complete': len(rows) == len(cases)}, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        print(case['id'], case['model'], row['status'], flush=True)
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path, default=DEFAULT_COHORT)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.cohort, args.output_dir)
