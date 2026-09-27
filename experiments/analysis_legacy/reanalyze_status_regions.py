"""Replay the existing bounded partial-region path on qualified acoustic caches.

Every candidate remains a partial map. Whole-annotation diagnostics penalize
uncovered events; local scores use an explicit intersection with its support.
No reference is opened until the candidate output is saved.
"""
import argparse
from collections import Counter
from pathlib import Path
import resource
import shutil
import time

import torch

from build_status_audit_report import owner_review_decisions
from clock_candidate_regions import generate_region_candidates
from compare_clock_candidates import evaluate_times
from inspect_inputs import sha256
from replay_integrity import prediction_index, merge_prediction_rows
from reanalyze_status_paths import read, save, TOLERANCES
from run_crossed_benchmark import load_logits


def score_regions(reference, generated):
    candidate_scores = {}
    for candidate in generated['candidates']:
        times = [e['source_seconds'] for e in candidate['indexed_grid']]
        metrics = evaluate_times(reference, times, candidate['tempo_events'], candidate,
                                 tempo_map_supported=True)
        lo = max(reference['evaluation_support_seconds'][0], candidate['source_support_seconds'][0])
        hi = min(reference['evaluation_support_seconds'][1], candidate['source_support_seconds'][1])
        local = None
        if hi > lo:
            local = evaluate_times({**reference, 'evaluation_support_seconds': [lo, hi]},
                times, candidate['tempo_events'], candidate, tempo_map_supported=True)
        candidate_scores[candidate['id']] = {'whole_annotation_diagnostic': metrics,
            'within_proposed_region_diagnostic': local,
            'region_evaluation_support_seconds': [lo, hi] if hi > lo else None,
            'source_support_seconds': candidate['source_support_seconds'],
            'full_song_map': False, 'downbeat_capability': 'unsupported', 'meter_capability': 'unsupported'}
    selected_id = generated['selected_candidate_id']
    selected = candidate_scores.get(selected_id)
    if selected is None:
        selected = {'whole_annotation_diagnostic': evaluate_times(reference, [], None, tempo_map_supported=True),
            'within_proposed_region_diagnostic': None, 'full_song_map': False,
            'downbeat_capability': 'unsupported', 'meter_capability': 'unsupported'}
    oracle = {'diagnostic_only': True, 'reference_used_for_candidate_choice': True,
        'full_song_map': False, 'selection_scope': 'best whole-annotation event F1 among emitted partial candidates'}
    for label in TOLERANCES:
        metric = 'event_' + label
        winner = max(candidate_scores, key=lambda k: candidate_scores[k]['whole_annotation_diagnostic'][metric]['f1']) if candidate_scores else None
        oracle[metric] = {'candidate_id': winner,
            'scores': candidate_scores[winner] if winner else None}
    return {'selected_candidate_id': selected_id, 'selected': selected,
            'candidate_scores': candidate_scores, 'oracle_diagnostics': oracle}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core-dir', type=Path, required=True)
    p.add_argument('--old-root', type=Path, default=Path('data/runs/status-audit/2026-09-25-v1'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--candidate-ranking-policy', choices=('legacy',), default='legacy')
    args = p.parse_args()
    if not 1 <= args.threads <= 4:
        p.error('threads must be between one and four')
    if args.output_dir.exists() and not args.resume:
        p.error('existing output requires --resume')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    manifest_path = args.core_dir / 'manifest.json'
    core = read(manifest_path)
    if not core['complete']:
        p.error('core availability inventory must be complete')
    prediction_index(core)
    previous_path=args.output_dir/'manifest.json'
    previous=prediction_index(read(previous_path)) if previous_path.exists() else {}
    catalog = read(args.old_root / 'catalog-scored-audio.json')
    references = {t['id']: t['reference'] for t in catalog['tracks']}
    _, rejected = owner_review_decisions(args.old_root / 'reference-review-batch1-v2/owner-decisions.json', catalog)
    source_root = Path(__file__).parent
    files = ('clock_candidate_regions.py', 'clock_candidates.py', 'fit_clock.py', 'replay_integrity.py')
    configuration = {'schema_version': 1, 'algorithm_hashes': {f: sha256(source_root / f) for f in files},
        'core_manifest': str(manifest_path), 'core_manifest_sha256': sha256(manifest_path),
        'reference_used_for_prediction': False, 'full_song_map': False,
        'settings': 'unchanged RegionConfig and CandidateConfig defaults; max2 regions/max8 candidates',
        'threads': args.threads, 'candidate_ranking_policy': args.candidate_ranking_policy,
        'evaluation_hashes': {f: sha256(source_root / f) for f in ('reanalyze_status_regions.py', 'compare_clock_candidates.py', 'grid_metrics.py')}}
    configuration_path = args.output_dir / 'configuration.json'
    if configuration_path.exists() and read(configuration_path) != configuration:
        raise ValueError('cannot resume changed source/configuration')
    save(configuration_path, configuration)
    for f in (*files, 'reanalyze_status_regions.py', 'compare_clock_candidates.py', 'grid_metrics.py'):
        target = args.output_dir / 'source-snapshot' / f
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.copyfile(source_root / f, target)
    manifest = {'schema_version': 1, 'rows': [], 'complete': False,
        'scope': 'existing region restarts; partial-only outputs and diagnostic oracle kept separate'}
    processed_rows=[]
    for core_row in core['rows']:
        row = {k: core_row[k] for k in ('id', 'cohort', 'model', 'evaluation_admission')}
        if core_row['status'] != 'predictions_saved':
            row.update(status=core_row['status'], reason='core model evidence unavailable', individually_executed=False)
        else:
            started = time.perf_counter()
            try:
                original_path = Path(core_row['prediction_path'])
                if sha256(original_path) != core_row['prediction_sha256']:
                    raise ValueError('core prediction changed')
                original = read(original_path); source = original['source']
                if sha256(source['path']) != source['sha256'] or sha256(source['logits_path']) != source['logits_sha256']:
                    raise ValueError('source or native logits changed')
                target = args.output_dir / 'predictions' / row['id'] / row['model'] / 'predictions.json'
                if target.exists():
                    if (row['id'],row['model']) not in previous:raise ValueError('unbound region prediction')
                    predicted = read(target)
                    if predicted['core_prediction_sha256'] != core_row['prediction_sha256']:
                        raise ValueError('saved partial reconstruction source changed')
                    row['postprocessing_execution'] = 'reused_this_reanalysis_prediction'
                else:
                    beat, downbeat, fps = load_logits(source['logits_path'], source['duration_seconds'], source['native_frame_rate'])
                    generating = time.perf_counter()
                    generated = generate_region_candidates(beat, downbeat, fps,
                        original['methods']['common_minimal']['prediction']['beats_seconds'],
                        source_duration_seconds=source['duration_seconds'], ranking_policy=args.candidate_ranking_policy)
                    predicted = {'schema_version': 1, 'id': row['id'], 'model': row['model'],
                        'cohort': row['cohort'], 'source': source,
                        'core_prediction_path': str(original_path), 'core_prediction_sha256': core_row['prediction_sha256'],
                        'references_used_for_prediction': False, 'full_song_map': False, 'generated': generated,
                        'execution': {'postprocessing_elapsed_seconds': time.perf_counter() - generating,
                            'memory_process_high_water_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                            'memory_scope': 'cumulative process RSS high-water mark; not per-track isolated',
                            'acoustic_inference_performed': False}}
                    save(target, predicted)
                    row['postprocessing_execution'] = 'executed_existing_frozen_path'
                row.update(status='prediction_saved_pending_evaluation', prediction_path=str(target),prediction_sha256=sha256(target))
                checkpoint_rows=merge_prediction_rows([*processed_rows,row],list(previous.values()))
                save(args.output_dir/'manifest.json',{**manifest,'rows':checkpoint_rows,'complete':False})
                # Every candidate has been persisted before opening reference events.
                generated = predicted['generated']
                score = {**row, 'prediction_path': str(target), 'prediction_sha256': sha256(target),
                    'full_song_map': False, 'scores': None}
                if row['evaluation_admission'] == 'admitted_reference':
                    if row['id'] in rejected:
                        raise ValueError('owner-rejected reference cannot be scored')
                    reference = references[row['id']]
                    if sha256(reference['path']) != reference['sha256']:
                        raise ValueError('reference changed')
                    score.update(reference=reference, scores=score_regions(read(reference['path']), generated))
                else:
                    score['reason'] = row['evaluation_admission']
                score_path = args.output_dir / 'scores' / row['id'] / (row['model'] + '.json')
                save(score_path, score)
                row.update(status='predictions_saved', prediction_path=str(target), prediction_sha256=sha256(target),
                    score_path=str(score_path), selection_status=generated['selection_status'],
                    candidate_count=len(generated['candidates']), region_count=len(generated['regions']),
                    full_song_map=False, this_invocation_elapsed_seconds=time.perf_counter()-started)
            except Exception as error:
                row.update(status='reanalysis_failed', exception_type=type(error).__name__, reason=str(error))
        processed_rows.append(row)
        manifest['rows']=merge_prediction_rows(processed_rows,list(previous.values()))
        manifest['state_counts'] = dict(Counter(r['status'] for r in manifest['rows']))
        save(args.output_dir / 'manifest.json', manifest)
        print(row['id'], row['model'], row['status'], row.get('candidate_count', ''), flush=True)
    manifest['complete'] = True
    save(args.output_dir / 'manifest.json', manifest)


if __name__ == '__main__':
    main()
