"""Score partial-region restarts as a post-observation development iteration."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from clock_candidate_regions import generate_region_candidates
from compare_clock_candidates import evaluate_times
from inspect_inputs import sha256
from run_crossed_benchmark import load_logits, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cross-reports', type=Path, nargs='+', required=True)
    parser.add_argument('--catalogs', type=Path, nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('output must be new')
    records = {t['id']: t for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    rows = [t for p in args.cross_reports for t in json.loads(p.read_text())['tracks']]
    args.output_dir.mkdir(parents=True)
    files = ('clock_candidate_regions.py', 'clock_candidates.py', 'fit_clock.py',
             'run_region_benchmark.py', 'compare_clock_candidates.py', 'grid_metrics.py')
    report = {'configuration': {'schema_version': 'region-restart-development-v2',
        'source_hashes': {f: sha256(Path(__file__).with_name(f)) for f in files},
        'source_reports': [{'path': str(p), 'sha256': sha256(p)} for p in args.cross_reports],
        'catalogs': [{'path': str(p), 'sha256': sha256(p)} for p in args.catalogs],
        'development_after_observing_v1_failures': True, 'unseen_validation': False,
        'reference_used_for_prediction': False, 'partial_maps_are_not_joined': True,
        'max_candidates_per_model_track': 8}, 'tracks': [], 'complete': False}
    for original in rows:
        started = time.perf_counter()
        track_id = original['id']; source = original['source']
        if sha256(source['path']) != source['sha256']:
            raise ValueError('source audio changed')
        row = {k: deepcopy(original[k]) for k in ('id', 'dataset', 'cohort', 'source', 'model_provenance')}
        row.update(methods={}, candidate_sets={}, oracle_diagnostics={}, v1_source_methods=original['methods'])
        generated = {}
        for model, provenance in original['model_provenance'].items():
            path = Path(provenance['logits_path'])
            if sha256(path) != provenance['logits_sha256']:
                raise ValueError('saved acoustic evidence changed')
            beat, downbeat, fps = load_logits(path, source['duration_seconds'])
            raw = original['methods'][model + '__common_minimal']['prediction']['beats_seconds']
            candidates = generate_region_candidates(beat, downbeat, fps, raw, source_duration_seconds=source['duration_seconds'])
            candidates['input_provenance'] = {'audio': source, **provenance}
            target = args.output_dir / track_id / model
            target.mkdir(parents=True)
            candidate_path = target / 'candidates.json'
            candidate_path.write_text(json.dumps(candidates, indent=2, allow_nan=False) + '\n')
            generated[model] = candidates
            row['candidate_sets'][model] = str(candidate_path)
        # Prediction is finished for both models before any reference is read.
        record = records[track_id]['reference']
        if sha256(record['path']) != record['sha256']:
            raise ValueError('reference changed')
        reference = json.loads(Path(record['path']).read_text())
        row['reference_sha256'] = record['sha256']
        for model, result in generated.items():
            scores = {}
            for candidate in result['candidates']:
                times = [e['source_seconds'] for e in candidate['indexed_grid']]
                score = evaluate_times(reference, times, candidate['tempo_events'], candidate)
                lo = max(reference['evaluation_support_seconds'][0], candidate['source_support_seconds'][0])
                hi = min(reference['evaluation_support_seconds'][1], candidate['source_support_seconds'][1])
                if hi > lo:
                    local_reference = {**reference, 'evaluation_support_seconds': [lo, hi]}
                    score['within_proposed_region_diagnostic'] = evaluate_times(local_reference, times,
                                                                               candidate['tempo_events'], candidate)
                scores[candidate['id']] = score
            chosen = next((c for c in result['candidates'] if c['id'] == result['selected_candidate_id']), None)
            prediction = {'beats_seconds': [e['source_seconds'] for e in chosen['indexed_grid']] if chosen else [],
                          'downbeats_seconds': []}
            method = {'prediction': prediction, 'clock': chosen['clock'] if chosen else None,
                      'status': result['selection_status'], 'selected_candidate_id': result['selected_candidate_id'],
                      'full_song_map': False,
                      'source_support_seconds': chosen['source_support_seconds'] if chosen else None,
                      'unknown_bridges': result['unknown_bridges'],
                      'metrics': scores[chosen['id']] if chosen else evaluate_times(reference, []),
                      'candidate_count': len(result['candidates'])}
            row['methods'][model + '__clock_regions_selected'] = method
            oracle = {'diagnostic_only': True, 'full_song_map': False, 'candidate_scores': scores}
            for metric in ('event_20ms', 'event_70ms'):
                key = max(scores, key=lambda k: scores[k][metric]['f1']) if scores else None
                oracle[metric] = {'candidate_id': key, 'scores': scores[key] if key else None}
            row['oracle_diagnostics'][model] = oracle
        row['elapsed_seconds'] = time.perf_counter() - started
        report['tracks'].append(row); report['summary'] = summarize(report['tracks'])
        report['complete'] = len(report['tracks']) == len(rows)
        (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(track_id, {name: {'candidates': m['candidate_count'], 'whole_song_f1_70': round(m['metrics']['event_70ms']['f1'], 4),
                               'support': m['source_support_seconds']} for name, m in row['methods'].items()}, flush=True)
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
