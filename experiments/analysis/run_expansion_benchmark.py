"""Apply existing frozen analysis settings to newly qualified audio catalogs.

Predictions for every example are saved before references are opened. No model,
prior strength, octave, or shift is selected with labels. Oracle phase search
is a separate post-evaluation diagnostic and never modifies a prediction.
"""
import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import time

import numpy as np
import soundfile as sf
import torch
from beat_this.inference import Audio2Frames
from beat_this.model.postprocessor import Postprocessor

from ablate_clock_inputs import fit_prediction
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from decode_pulses import decode_pulses
from evaluate_tempo_prior import prediction, save
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from phase_alignment import AttackConfig, PhaseConfig, extract_attacks, propose_phase, shifted_clock
from run_beat_this import installed_versions
from tempo_prior import PriorConfig, refine_tempo_clock


METHODS = ('official_minimal', 'meter_free_raw', 'current_clock', 'soft_prior_2', 'phase_consensus')


def summarize(rows):
    result = {}
    for cohort in sorted({r['dataset'] for r in rows}):
        subset = [r for r in rows if r['dataset'] == cohort]
        groups = sorted({r['group_id'] for r in subset})
        methods = {}
        for method in METHODS:
            methods[method] = {}
            for scope in ('declared_support', 'after_5_seconds'):
                scores = [r['scores'][scope][method] for r in subset]
                methods[method][scope] = {
                    'macro_f1_'+key: float(np.mean([s['event_'+key]['f1'] for s in scores]))
                    for key in ('10ms', '20ms', '70ms')}
                methods[method][scope]['group_macro_f1_20ms'] = float(np.mean([
                    np.mean([r['scores'][scope][method]['event_20ms']['f1'] for r in subset if r['group_id'] == group])
                    for group in groups]))
        result[cohort] = {'recordings': len(subset), 'group_count': len(groups), 'methods': methods,
            'nonzero_phase_proposals': sum(abs(r['methods']['phase_consensus']['phase']['applied_shift_seconds']) > 1e-9 for r in subset),
            'oracle_phase_only_20ms': float(np.mean([r['diagnostic_oracle_phase']['f1_20ms'] for r in subset]))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalogs', required=True, nargs='+', type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--calibration', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cuda')
    parser.add_argument('--predict-only', action='store_true',
                        help='Freeze source-only outputs without opening any reference or reporting accuracy')
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('output directory must be new')
    records = [r for path in args.catalogs for r in json.loads(path.read_text())['tracks']]
    if len({r['id'] for r in records}) != len(records):
        parser.error('duplicate recording IDs')
    if not args.predict_only and any(r.get('target_evaluation_eligible') is False or r.get('benchmark_role') == 'diagnostic_only' for r in records):
        parser.error('diagnostic-only or ineligible input cannot enter target benchmark scoring; use --predict-only')
    if not args.predict_only and any(r.get('absolute_timing_verified') is False for r in records):
        parser.error('catalog explicitly lacks verified timing; use --predict-only')
    calibration = json.loads(args.calibration.read_text())
    if calibration['source_hashes']['phase_alignment.py'] != sha256(Path(__file__).with_name('phase_alignment.py')):
        parser.error('calibration feature version mismatch')
    prior_config, phase_config = PriorConfig(strength=2.), PhaseConfig()
    attack_config = AttackConfig(**calibration['configuration'])
    output = args.output_dir
    output.mkdir(parents=True)
    snapshots = output/'source-snapshot'
    snapshots.mkdir()
    # Freeze all experiment modules, including transitive scoring dependencies.
    for path in sorted(Path(__file__).parent.glob('*.py')):
        shutil.copyfile(path, snapshots/path.name)
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision('highest')
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    configuration = {'reference_used_for_prediction': False, 'default_promoted': False,
        'prediction_only': args.predict_only,
        'new_to_local_experiments': True, 'pretrained_model_holdout_status': 'training overlap not audited',
        'device': args.device, 'precision': 'float32', 'versions': installed_versions(),
        'checkpoint_sha256': sha256(args.checkpoint), 'prior': asdict(prior_config),
        'phase': asdict(phase_config), 'attacks': asdict(attack_config),
        'calibration': {'path': str(args.calibration), 'sha256': sha256(args.calibration)},
        'source_hashes': {p.name: sha256(p) for p in snapshots.glob('*.py')},
        'catalogs': [{'path': str(p), 'sha256': sha256(p)} for p in args.catalogs],
        'comparison': 'unchanged final0/minimal, meter-free decoder/fitter, strength-2 prior, calibrated shared phase',
        'oracle_phase': 'diagnostic only: best fixed shift from -100 to +100 ms, 1ms steps, same existing pulse sequence',
        'scope': 'Separate cohort and performer aggregates; drum recordings are not complete studio songs.'}
    save(output/'configuration.json', configuration)
    model = Audio2Frames(checkpoint_path=str(args.checkpoint.resolve()), device=args.device, float16=False)
    minimal = Postprocessor(type='minimal', fps=50)
    rows = []
    for record in records:
        started = time.perf_counter()
        if sha256(record['input']['path']) != record['input']['sha256']:
            raise ValueError('audio hash mismatch')
        target = output/record['id']
        target.mkdir()
        audio, rate = sf.read(record['input']['path'], dtype='float32', always_2d=True)
        if (rate, len(audio)) != (record['sample_rate'], record['sample_frames']):
            raise ValueError('audio geometry differs from catalog')
        beat, downbeat = model(audio, rate)
        beat_array, down_array = beat.detach().cpu().numpy(), downbeat.detach().cpu().numpy()
        np.savez_compressed(target/'logits.npz', beat=beat_array, downbeat=down_array, fps=np.array(50))
        official, official_down = minimal(beat, downbeat)
        raw = decode_pulses(beat_array, fps=50)
        raw = raw[(raw >= 0) & (raw < record['duration_seconds'])]
        clock, fitted, status = fit_prediction({'beats_seconds': raw.tolist(), 'downbeats_seconds': []})
        methods = {
            'official_minimal': {'prediction': official.tolist(), 'downbeats_seconds': official_down.tolist(), 'clock': None},
            'meter_free_raw': {'prediction': raw.tolist(), 'clock': None},
            'current_clock': {'prediction': fitted['beats_seconds'], 'clock': clock, 'status': status}}
        prior, prior_times = clock, fitted['beats_seconds']
        prior_status = 'no_clock_fallback'
        if clock:
            try:
                prior = refine_tempo_clock(raw, clock['input_pulse_indices'], clock, prior_config)
                prior_times = prediction(prior, record['duration_seconds'], clock['pulse_index_span'])
                prior_status = 'refitted_unaccepted_proposal'
            except ValueError as error:
                prior_status = 'unchanged_rejected_refit: '+str(error)
        methods['soft_prior_2'] = {'prediction': prior_times, 'clock': prior, 'status': prior_status}
        attacks = extract_attacks(audio, rate, attack_config)
        attacks.update(audio_sha256=record['input']['sha256'], feature_sha256=configuration['source_hashes']['phase_alignment.py'])
        save(target/'attacks.json', attacks)
        phase = propose_phase(prior_times, attacks, calibration, phase_config) if prior else {
            'status': 'no_clock_fallback', 'applied_shift_seconds': 0.}
        shift = phase['applied_shift_seconds']
        moved = shifted_clock(prior, shift, record['duration_seconds']) if prior and shift else prior
        methods['phase_consensus'] = {'prediction': [t+shift for t in prior_times if 0 <= t+shift < record['duration_seconds']],
            'clock': moved, 'phase': phase}
        row = {k: record[k] for k in ('id', 'dataset', 'group_id', 'genre')}
        row.update(methods=methods, input_sha256=record['input']['sha256'],
            logits_sha256=sha256(target/'logits.npz'), attacks_sha256=sha256(target/'attacks.json'),
            elapsed_seconds=time.perf_counter()-started)
        save(target/'predictions.json', row)
        row.update(prediction_path=str(target/'predictions.json'), prediction_sha256=sha256(target/'predictions.json'))
        rows.append(row)
        print('PREDICT', record['id'], round(row['elapsed_seconds'], 2), phase['status'], shift, flush=True)
    save(output/'prediction-manifest.json', [{'id': r['id'], 'path': r['prediction_path'], 'sha256': r['prediction_sha256']} for r in rows])
    if args.predict_only:
        if any(sha256(Path(__file__).with_name(n)) != h for n, h in configuration['source_hashes'].items()):
            raise ValueError('source modules changed during prediction')
        save(output/'predictions-report.json', {'configuration': configuration, 'rows': rows,
             'complete': True, 'scoring_performed': False,
             'reason': 'Source predictions preserved independently of reference admission.'})
        print('PREDICTION ONLY: no reference opened, no accuracy score produced', flush=True)
        return
    # All inference is complete and immutable before the first label is opened.
    for row, record in zip(rows, records):
        if sha256(record['reference']['path']) != record['reference']['sha256']:
            raise ValueError('reference hash mismatch')
        reference = json.loads(Path(record['reference']['path']).read_text())
        row['reference_sha256'] = record['reference']['sha256']
        row['scores'] = {}
        for scope in ('declared_support', 'after_5_seconds'):
            lo, hi = reference['evaluation_support_seconds']
            if scope == 'after_5_seconds':
                lo = max(lo, 5.)
            scoped = {**reference, 'evaluation_support_seconds': [lo, hi]}
            truth = np.asarray([t for t in reference['beats_seconds'] if lo <= t <= hi])
            row['scores'][scope] = {}
            for name, method in row['methods'].items():
                scores = evaluate_times(scoped, method['prediction'], tempo_events(method['clock']) if method['clock'] else None)
                estimated = np.asarray([t for t in method['prediction'] if lo <= t <= hi])
                scores['event_10ms'] = nearest_event_diagnostics(truth, estimated, .01)
                row['scores'][scope][name] = scores
        lo, hi = reference['evaluation_support_seconds']
        truth = np.asarray([t for t in reference['beats_seconds'] if lo <= t <= hi])
        times = np.asarray(row['methods']['soft_prior_2']['prediction'])
        shifts = sorted(np.arange(-100, 101)/1000, key=lambda v: (abs(v), v))
        options = []
        for shift in shifts:
            moved = times+shift
            score = nearest_event_diagnostics(truth, moved[(moved >= lo) & (moved <= hi)], .02)
            options.append((score['f1'], float(shift)))
        f1, shift = max(options, key=lambda x: x[0])
        row['diagnostic_oracle_phase'] = {'not_deployable': True, 'f1_20ms': f1, 'shift_seconds': shift,
            'warning': 'Reference-selected offset; no claim of recoverable acoustic evidence or full-map correctness.'}
        if sha256(row['prediction_path']) != row['prediction_sha256']:
            raise ValueError('prediction changed during evaluation')
        print('SCORE', row['id'], {m: round(row['scores']['declared_support'][m]['event_20ms']['f1'], 4) for m in METHODS}, flush=True)
    if any(sha256(Path(__file__).with_name(n)) != h for n, h in configuration['source_hashes'].items()):
        raise ValueError('source modules changed during run')
    report = {'configuration': configuration, 'rows': rows, 'summary': summarize(rows), 'complete': True}
    save(output/'report.json', report)
    with (output/'cases.csv').open('w') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', 'cohort', 'group', 'genre', *METHODS, 'oracle_phase_only_20ms', 'proposed_shift_ms'])
        for r in rows:
            writer.writerow([r['id'], r['dataset'], r['group_id'], r['genre'],
                *[r['scores']['declared_support'][m]['event_20ms']['f1'] for m in METHODS],
                r['diagnostic_oracle_phase']['f1_20ms'], 1000*r['methods']['phase_consensus']['phase']['applied_shift_seconds']])
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
