"""Separate candidate-selection and common-phase headroom on frozen outputs.

Oracle values are reference-assisted diagnostics, never proposed corrections.
Candidate generation and its automatic ranking remain source-only and frozen.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil

import numpy as np

from clock_candidates import CandidateConfig, generate_clock_candidates
from compare_clock_candidates import evaluate_times
from evaluate_tempo_prior import save
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', required=True, type=Path)
    parser.add_argument('--catalogs', required=True, nargs='+', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('new output required')
    benchmark = json.loads(args.benchmark.read_text())
    records = {r['id']: r for p in args.catalogs for r in json.loads(p.read_text())['tracks']}
    output = args.output_dir
    output.mkdir(parents=True)
    snapshot = output/'source-snapshot'
    snapshot.mkdir()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        shutil.copyfile(p, snapshot/p.name)
    configuration = {'candidate': asdict(CandidateConfig()),
        'benchmark': {'path': str(args.benchmark), 'sha256': sha256(args.benchmark)},
        'source_hashes': {p.name: sha256(p) for p in snapshot.glob('*.py')},
        'reference_used_for_candidate_generation_or_ranking': False,
        'reference_used_for_oracles': True, 'default_promoted': False,
        'full_phase_oracle': 'one scalar shift within half the median reference quarter period, 1ms steps; no rate or topology changes',
        'warning': 'Oracle candidate and phase maxima are distinct, nondeployable diagnostics; not a combined algorithm.'}
    save(output/'configuration.json', configuration)
    predictions = []
    for row in benchmark['rows']:
        directory = args.benchmark.parent/row['id']
        if sha256(directory/'logits.npz') != row['logits_sha256']:
            raise ValueError('frozen logits changed')
        logits = np.load(directory/'logits.npz')
        candidates = generate_clock_candidates(logits['beat'], logits['downbeat'], float(logits['fps']),
                                               [v for v in row['methods']['official_minimal']['prediction'] if 0 <= v < records[row['id']]['duration_seconds']],
                                               source_duration_seconds=records[row['id']]['duration_seconds'])
        destination = output/(row['id']+'.json')
        save(destination, candidates)
        predictions.append({'id': row['id'], 'path': str(destination), 'sha256': sha256(destination)})
        print('CANDIDATES', row['id'], len(candidates['candidates']), candidates['selected_candidate_id'], flush=True)
    save(output/'prediction-manifest.json', predictions)
    rows = []
    for base, frozen in zip(benchmark['rows'], predictions):
        record = records[base['id']]['reference']
        if sha256(record['path']) != record['sha256']:
            raise ValueError('reference changed')
        reference = json.loads(Path(record['path']).read_text())
        candidates = json.loads(Path(frozen['path']).read_text())
        scored = {}
        for candidate in candidates['candidates']:
            times = [e['source_seconds'] for e in candidate['indexed_grid']]
            scored[candidate['id']] = evaluate_times(reference, times, candidate['tempo_events'])
        lo, hi = reference['evaluation_support_seconds']
        truth = np.asarray([t for t in reference['beats_seconds'] if lo <= t <= hi])
        times = np.asarray(base['methods']['soft_prior_2']['prediction'])
        half_width_ms = int(np.ceil(np.median(np.diff(truth))*500))
        shifts = sorted(np.arange(-half_width_ms, half_width_ms+1)/1000, key=lambda s: (abs(s), s))
        options = []
        for shift in shifts:
            moved = times+shift
            score = nearest_event_diagnostics(truth, moved[(moved >= lo) & (moved <= hi)], .02)
            options.append((score['f1'], float(shift)))
        best_score, best_shift = max(options, key=lambda x: x[0])
        best_id = max(scored, key=lambda key: scored[key]['event_20ms']['f1']) if scored else None
        selected = candidates['selected_candidate_id']
        available = {'frozen/'+name: score['event_20ms']['f1']
                     for name, score in base['scores']['declared_support'].items()}
        available.update({'candidate/'+name: score['event_20ms']['f1'] for name, score in scored.items()})
        pool_best = max(available, key=available.get)
        row = {'id': base['id'], 'dataset': base['dataset'], 'group_id': base['group_id'],
            'frozen_predictions': frozen, 'reference_sha256': record['sha256'],
            'baseline_f1_20ms': base['scores']['declared_support']['soft_prior_2']['event_20ms']['f1'],
            'candidate_count': len(scored), 'candidate_scores': scored, 'selected_candidate_id': selected,
            'selected_f1_20ms': scored[selected]['event_20ms']['f1'] if selected else None,
            'oracle_candidate_id': best_id, 'oracle_candidate_f1_20ms': scored[best_id]['event_20ms']['f1'] if best_id else None,
            'oracle_available_pool_id': pool_best, 'oracle_available_pool_f1_20ms': available[pool_best],
            'oracle_common_phase_f1_20ms': best_score, 'oracle_common_phase_shift_seconds': best_shift,
            'oracle_common_phase_half_width_ms': half_width_ms, 'oracles_not_deployable': True}
        if sha256(frozen['path']) != frozen['sha256']:
            raise ValueError('candidate predictions changed during scoring')
        rows.append(row)
        print('DIAGNOSE', base['id'], {k: row[k] for k in ('baseline_f1_20ms', 'selected_f1_20ms',
              'oracle_candidate_f1_20ms', 'oracle_common_phase_f1_20ms', 'oracle_common_phase_shift_seconds')}, flush=True)
    summary = {}
    for cohort in sorted({r['dataset'] for r in rows}):
        subset = [r for r in rows if r['dataset'] == cohort]
        summary[cohort] = {'recordings': len(subset), 'empty_candidate_sets': sum(not r['candidate_count'] for r in subset)}
        for key in ('baseline_f1_20ms', 'selected_f1_20ms', 'oracle_candidate_f1_20ms',
                    'oracle_available_pool_f1_20ms', 'oracle_common_phase_f1_20ms'):
            values = [r[key] for r in subset if r[key] is not None]
            summary[cohort][key] = {'eligible': len(values), 'mean': float(np.mean(values)) if values else None}
    save(output/'report.json', {'configuration': configuration, 'rows': rows, 'summary': summary, 'complete': True})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
