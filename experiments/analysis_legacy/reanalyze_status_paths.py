"""Replay existing frozen reconstruction paths from qualified acoustic caches.

This is audit/evaluation plumbing, not a new analyzer. It never runs a model,
loads reference events before persisting predictions, or changes decoder knobs.
An inventory covers every audio/model pair, including unavailable caches.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np
import soundfile as sf
import torch

from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from replay_integrity import prediction_index, merge_prediction_rows
from run_crossed_benchmark import common_minimal, load_logits, reconstruct_model

BEAT_THIS_HASH = '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331'
TRANSFORMER_HASH = 'b76033014dd07d12307743b92337b7dffadf1f20a6ccd5a1edb03276e99a4512'
METHOD_RENAME = {'clock_current': 'meter_free_clock'}
TEMPO_CAPABLE = {'meter_free_clock', 'clock_candidates_selected', 'legacy_dbn_clock'}
TOLERANCES = {'10ms': .01, '20ms': .02, '30ms': .03, '70ms': .07}
PREDICTION_SOURCES = ('run_crossed_benchmark.py', 'clock_candidates.py', 'decode_pulses.py',
    'fit_clock.py', 'ablate_clock_inputs.py', 'legacy_dbn.py', 'run_beat_this.py',
    'reanalyze_status_paths.py', 'replay_integrity.py')


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def geometry(path):
    info = sf.info(path)
    return {'sample_rate': info.samplerate, 'channels': info.channels,
            'sample_frames': info.frames, 'duration_seconds': info.frames / info.samplerate}


def validate_model_config(model, configuration):
    if model == 'beat_this':
        if configuration.get('checkpoint_sha256') != BEAT_THIS_HASH:
            raise ValueError('Beat This checkpoint is not frozen final0')
        if configuration.get('precision') != 'float32':
            raise ValueError('Beat This precision mismatch')
        version = configuration.get('package_version', configuration.get('versions', {}).get('beat-this'))
        if version != '1.1.0':
            raise ValueError('Beat This frontend package version mismatch')
        if configuration.get('frame_rate', 50) != 50:
            raise ValueError('Beat This frame rate mismatch')
        return 50.
    if model != 'beat_transformer':
        raise ValueError('unknown acoustic model')
    if configuration.get('checkpoint', {}).get('sha256') != TRANSFORMER_HASH:
        raise ValueError('Beat Transformer checkpoint mismatch')
    if configuration.get('precision') != 'float32' or configuration.get('frame_time_offset_seconds') != 0:
        raise ValueError('Beat Transformer precision/time origin mismatch')
    if configuration.get('frame_rate') != 44100 / 1024:
        raise ValueError('Beat Transformer frame rate mismatch')
    if configuration.get('decoder') != 'official_demo_madmom_separate_beat_and_downbeat_dbns':
        raise ValueError('Beat Transformer decoder mismatch')
    return float(configuration['frame_rate'])


def qualify_cache(asset, cache):
    """Verify exact source bytes, decode mapping, model, geometry and logit span."""
    original = Path(asset['input_path'])
    if sha256(original) != asset['input_sha256']:
        raise ValueError('original audio bytes changed')
    source = Path(cache.get('input_path', original))
    source_hash = sha256(source)
    mapping = None
    if source_hash != asset['input_sha256']:
        if not cache.get('mapping_path'):
            raise ValueError('different source bytes require a preserved canonical decode mapping')
        mapping_path = Path(cache['mapping_path'])
        mapping = read(mapping_path)
        if (mapping['source']['sha256'] != asset['input_sha256'] or
                mapping['decoded']['sha256'] != source_hash or
                (mapping_path.parent / mapping['decoded']['file']).resolve() != source.resolve()):
            raise ValueError('canonical decode mapping mismatch')
        if 'no additional start_time subtraction' not in mapping['decoded'].get('origin_policy', ''):
            raise ValueError('unqualified canonical decode time origin')
    current_geometry = geometry(source)
    recorded = cache.get('audio')
    if recorded:
        if recorded.get('sha256') != source_hash or recorded.get('source_frame_offset', 0) != 0:
            raise ValueError('cached source hash/origin mismatch')
        for field, expected in [('sample_rate', current_geometry['sample_rate']),
                                ('channels', current_geometry['channels']),
                                ('source_frames', current_geometry['sample_frames']),
                                ('analyzed_frames', current_geometry['sample_frames'])]:
            if recorded.get(field) != expected:
                raise ValueError('cached source geometry mismatch: ' + field)
    elif cache.get('input_sha256') != source_hash:
        raise ValueError('cache/catalog source hash mismatch')
    if cache.get('duration_seconds') is not None and abs(cache['duration_seconds'] - current_geometry['duration_seconds']) > 1 / current_geometry['sample_rate']:
        raise ValueError('cached source duration mismatch')
    if mapping and mapping['decoded']['sample_frames'] != current_geometry['sample_frames']:
        raise ValueError('canonical decoded frames mismatch')
    fps = validate_model_config(cache['model'], cache['model_configuration'])
    logits_path = Path(cache['logits_path'])
    if cache.get('logits_sha256') and sha256(logits_path) != cache['logits_sha256']:
        raise ValueError('cached logits changed')
    beat, downbeat, observed_fps = load_logits(logits_path, current_geometry['duration_seconds'], fps)
    if cache['model'] == 'beat_transformer':
        frontend = cache['frontend']
        expected = {'audio_sha256': source_hash, 'source_sample_rate': current_geometry['sample_rate'],
            'source_frames': current_geometry['sample_frames'], 'analyzed_source_frames': current_geometry['sample_frames'],
            'source_frame_offset': 0, 'frame_time_offset_seconds': 0, 'fps': fps}
        if any(frontend.get(key) != value for key, value in expected.items()):
            raise ValueError('Beat Transformer frontend source mapping mismatch')
        if frontend.get('feature_shape') != [5, len(beat), 128] or frontend.get('versions', {}).get('spleeter') != '2.3.2':
            raise ValueError('Beat Transformer frontend shape/version mismatch')
        if frontend.get('stft', {}).get('zero_padding_samples_each_side') != 4096:
            raise ValueError('Beat Transformer frontend padding mismatch')
        # Official Spleeter STFT pads its source: these native frames are kept,
        # while reconstruct_model separately clips returned events to the audio.
        if len(beat) / fps > current_geometry['duration_seconds'] + 6 / fps:
            raise ValueError('logits exceed recorded native frontend padding')
    elif len(beat) / fps > current_geometry['duration_seconds'] + 2 / fps:
        raise ValueError('logits extend beyond the full source duration')
    return {'original_path': str(original), 'original_sha256': asset['input_sha256'],
            'path': str(source), 'sha256': source_hash, **current_geometry,
            'source_frame_offset': 0, 'frame_time_offset_seconds': 0,
            'canonical_decode_mapping': ({'path': cache['mapping_path'], 'sha256': sha256(cache['mapping_path'])} if mapping else None),
            'original_inventory_geometry': asset['geometry'],
            'logits_path': str(logits_path), 'logits_sha256': sha256(logits_path),
            'native_frame_rate': observed_fps}, beat, downbeat


def caches_from_sources(old_root, external=None):
    caches = {}
    report_path = old_root / 'beat-this-scored41/report.json'
    report = read(report_path)
    for row in report['tracks']:
        caches[(row['id'], 'beat_this')] = {'model': 'beat_this', 'input_sha256': row['input_sha256'],
            'duration_seconds': row['duration_seconds'], 'model_configuration': report['configuration'],
            'logits_path': str(report_path.parent / row['id'] / 'logits.npz'),
            'result_path': str(report_path.parent / row['id'] / 'result.json'),
            'native': row['variants']['official_minimal'], 'legacy_variants': row['variants'],
            'legacy_clock': row['clock'], 'legacy_clock_status': row['clock_status'],
            'historical_timing_seconds': row['timing_seconds']}
    daybreak_path = Path('data/runs/corpus-expansion/daybreak3-predictions-v1/predictions-report.json')
    if daybreak_path.is_file():
        report = read(daybreak_path)
        for row in report['rows']:
            caches[(row['id'], 'beat_this')] = {'model': 'beat_this', 'input_sha256': row['input_sha256'],
                'model_configuration': report['configuration'], 'logits_sha256': row['logits_sha256'],
                'logits_path': str(daybreak_path.parent / row['id'] / 'logits.npz'),
                'result_path': row['prediction_path'], 'native': None,
                'native_output_origin': 'official minimal decoder replay from exact saved logits; historic expansion saved beat times only'}
    manifest = read(old_root / 'beat-transformer-scored41/manifest.json')
    for entry in manifest['rows']:
        if entry['status'] != 'reused':
            continue
        path = Path(entry['result_dir']) / 'result.json'
        row = read(path)
        caches[(entry['id'], 'beat_transformer')] = {'model': 'beat_transformer',
            'audio': row['audio'], 'model_configuration': row['model'], 'frontend': row['frontend'],
            'logits_path': str(path.with_name('logits.npz')), 'result_path': str(path),
            'native': {k: row[k] for k in ('beats_seconds', 'downbeats_seconds')},
            'historical_timing_seconds': row['timing_seconds'], 'historical_gpu_memory': row['gpu_memory']}
    for slug in ('circle', 'faint', 'cry-baby'):
        path = Path('data/runs/beat-this') / (slug + '-final0-gpu') / 'result.json'
        mapping = Path('data/runs/preflight') / (slug + '-20260921') / 'report.json'
        if not path.is_file() or not mapping.is_file():
            continue
        row = read(path)
        caches[('legacy_' + slug, 'beat_this')] = {'model': 'beat_this', 'audio': row['audio'],
            'model_configuration': row['model'], 'input_path': str(mapping.parent / 'audio.wav'),
            'mapping_path': str(mapping), 'logits_path': str(path.with_name('logits.npz')),
            'result_path': str(path), 'native': {k: row[k] for k in ('beats_seconds', 'downbeats_seconds')},
            'historical_timing_seconds': row['timing_seconds'], 'historical_gpu_memory': row['gpu_memory']}
    if external:
        for entry in read(external).get('caches', read(external).get('rows', [])):
            path = Path(entry['result_path']); row = read(path); model = entry['model']
            caches[(entry['id'], model)] = {**entry, 'audio': row['audio'],
                'model_configuration': row['model'], 'logits_path': entry.get('logits_path', str(path.with_name('logits.npz'))),
                'native': {k: row[k] for k in ('beats_seconds', 'downbeats_seconds')},
                'historical_timing_seconds': row['timing_seconds'], 'historical_gpu_memory': row.get('gpu_memory')}
    return caches


def score_methods(reference, methods):
    scores = {}
    for name, method in methods.items():
        prediction = method['prediction']; clock = method.get('clock')
        capable = name in TEMPO_CAPABLE
        metrics = evaluate_times(reference, prediction['beats_seconds'],
            tempo_events(clock) if clock else None, tempo_map_supported=capable)
        downbeat_capable = name != 'clock_candidates_selected'
        metrics['downbeat_capability'] = 'supported' if downbeat_capable else 'unsupported'
        downbeats = reference.get('downbeats_seconds')
        for label, tolerance in TOLERANCES.items():
            if downbeats is None or not downbeat_capable:
                metrics['downbeat_' + label] = None
            else:
                lo, hi = reference['evaluation_support_seconds']
                truth = [v for v in downbeats if lo <= v <= hi]
                predicted = [v for v in prediction['downbeats_seconds'] if lo <= v <= hi]
                metrics['downbeat_' + label] = nearest_event_diagnostics(truth, predicted, tolerance)
        metrics['meter_capability'] = 'unsupported_in_this_path'
        scores[name] = metrics
    return scores


def build_predictions(asset, cache, source, beat, downbeat, *, ranking_policy='legacy'):
    duration, fps = source['duration_seconds'], source['native_frame_rate']
    native = cache['native'] if cache['native'] is not None else common_minimal(beat, downbeat, fps, duration)
    started = time.perf_counter()
    reconstructed = reconstruct_model(beat, downbeat, fps, native, duration, candidate_ranking_policy=ranking_policy)
    elapsed = time.perf_counter() - started
    methods = {METHOD_RENAME.get(k, k): v for k, v in reconstructed.items()
               if k in ('official', 'common_minimal', 'clock_current', 'clock_candidates_selected')}
    if cache.get('legacy_variants'):
        methods['legacy_dbn'] = {'prediction': cache['legacy_variants']['legacy_dbn'], 'clock': None,
            'status': 'cached_legacy_dbn', 'source_method': 'legacy_dbn'}
        methods['legacy_dbn_clock'] = {'prediction': cache['legacy_variants']['clock_pipeline'],
            'clock': cache['legacy_clock'], 'status': cache['legacy_clock_status'], 'source_method': 'clock_pipeline'}
    for name, method in methods.items():
        method['capabilities'] = {'tempo_map': name in TEMPO_CAPABLE,
            'downbeat': name != 'clock_candidates_selected', 'meter_map': False,
            'full_tempo_meter_map': False}
        clock = method.get('clock')
        method['output_state'] = {'beat_event_count': len(method['prediction']['beats_seconds']),
            'tempo_map_produced': clock is not None,
            'support_seconds': clock.get('support_seconds') if clock else None,
            'full_source_contract_validated': False,
            'source_duration_seconds': duration}
    return {'schema_version': 1, 'id': asset['id'], 'cohort': asset['cohort'], 'model': cache['model'],
        'source': source, 'references_used_for_prediction': False, 'methods': methods,
        'model_configuration': cache['model_configuration'],
        'native_output_origin': cache.get('native_output_origin', 'preserved cached model-native output'),
        'native_output_unfiltered': native,
        'cache': {'result_path': cache['result_path'], 'result_sha256': sha256(cache['result_path']),
            'historical_timing_seconds': cache.get('historical_timing_seconds'),
            'historical_gpu_memory': cache.get('historical_gpu_memory')},
        'execution': {'postprocessing_elapsed_seconds': elapsed,
            'memory_process_high_water_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            'memory_scope': 'cumulative process RSS high-water mark; not isolated per-track allocation',
            'acoustic_inference_performed': False},
        'decoder_control': reconstructed['decoder_control']}, reconstructed['candidate_set']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--old-root', type=Path, default=Path('data/runs/status-audit/2026-09-25-v1'))
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--external-caches', type=Path)
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--candidate-ranking-policy', choices=('legacy','balanced_evidence'), default='legacy')
    p.add_argument('--track', nargs='*')
    p.add_argument('--model', choices=('beat_this', 'beat_transformer'), nargs='*')
    p.add_argument('--inventory-only', action='store_true')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--rescore', action='store_true')
    args = p.parse_args()
    if not 1 <= args.threads <= 4:
        p.error('threads must be between one and four')
    if args.output_dir.exists() and not args.resume:
        p.error('existing output requires --resume')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision('highest')
    inventory_path = args.old_root / 'inventory.json'
    inventory = read(inventory_path)
    catalog = read(args.old_root / 'catalog-scored-audio.json')
    references = {t['id']: t['reference'] for t in catalog['tracks']}
    decisions_path = args.old_root / 'reference-review-batch1-v2/owner-decisions.json'
    from build_status_audit_report import owner_review_decisions
    decisions, rejected = owner_review_decisions(decisions_path, catalog)
    caches = caches_from_sources(args.old_root, args.external_caches)
    source_root = Path(__file__).parent
    algorithm_hashes = {name: sha256(source_root / name) for name in PREDICTION_SOURCES}
    configuration = {'schema_version': 1, 'inventory_path': str(inventory_path), 'inventory_sha256': sha256(inventory_path),
        'owner_decisions_path': str(decisions_path), 'owner_decisions_sha256': sha256(decisions_path),
        'algorithm_hashes': algorithm_hashes, 'threads': args.threads,
        'candidate_ranking_policy': args.candidate_ranking_policy,
        'model_checkpoints': {'beat_this': BEAT_THIS_HASH, 'beat_transformer': TRANSFORMER_HASH},
        'reference_used_for_prediction': False, 'settings_tuned_with_references': False,
        'optional_selection_experiment': args.candidate_ranking_policy != 'legacy',
        'prediction_contract': 'existing reconstruct_model, source-relative output; common native-frame minimal control',
        'metric_source_hashes': {name: sha256(source_root / name) for name in
            ('compare_clock_candidates.py', 'grid_metrics.py', 'reanalyze_status_paths.py')}}
    config_path = args.output_dir / 'configuration.json'
    if config_path.exists():
        prior = read(config_path)
        if (prior['algorithm_hashes'] != algorithm_hashes or prior['inventory_sha256'] != configuration['inventory_sha256']
                or prior.get('candidate_ranking_policy','legacy') != args.candidate_ranking_policy
                or prior['owner_decisions_sha256'] != configuration['owner_decisions_sha256']):
            raise ValueError('cannot resume with changed algorithm or source inventory')
        if prior['metric_source_hashes'] != configuration['metric_source_hashes'] and not args.rescore:
            raise ValueError('evaluator changed; explicit --rescore required')
    save(config_path, configuration)
    for name in (*PREDICTION_SOURCES, 'reanalyze_status_paths.py', 'compare_clock_candidates.py', 'grid_metrics.py'):
        target = args.output_dir / 'source-snapshot' / name
        target.parent.mkdir(exist_ok=True)
        if target.exists() and sha256(target) != sha256(source_root / name):
            target = target.with_name(target.stem + '-' + sha256(source_root / name)[:12] + target.suffix)
        if not target.exists():
            shutil.copyfile(source_root / name, target)
    previous_manifest_path=args.output_dir/'manifest.json'
    previous_predictions=prediction_index(read(previous_manifest_path)) if previous_manifest_path.exists() else {}
    manifest = {'schema_version': 1, 'rows': [], 'complete': False,
        'scope': 'all original audio/model availability; selected compatible cached logits replayed',
        'runtime_failure_evidence': str(args.old_root / 'beat-transformer-frontend-runtime-failure.json')}
    processed_rows=[]
    for asset in inventory['audio']:
        for model in ('beat_this', 'beat_transformer'):
            key = (asset['id'], model); cache = caches.get(key)
            record = {'id': asset['id'], 'cohort': asset['cohort'], 'model': model,
                'input_sha256': asset['input_sha256'], 'reference_tier': asset['reference_tier'],
                'evaluation_admission': ('owner_rejected_reference' if asset['id'] in rejected else
                    'admitted_reference' if asset['id'] in references else 'prediction_only')}
            selected = (not args.track or asset['id'] in args.track) and (not args.model or model in args.model)
            if cache is None:
                record.update(status=('blocked_shared_frontend_runtime' if model == 'beat_transformer' else 'missing_fixed_model_cache'),
                    individually_executed=False)
            elif not selected:
                record.update(status='cached_not_selected_this_invocation', cache_path=cache['result_path'])
            else:
                started = time.perf_counter()
                try:
                    source, beat, downbeat = qualify_cache(asset, cache)
                    record['source'] = source
                    record['cache_result_sha256'] = sha256(cache['result_path'])
                    prediction_path = args.output_dir / 'predictions' / asset['id'] / model / 'predictions.json'
                    if prediction_path.exists():
                        if key not in previous_predictions:
                            raise ValueError('unbound existing prediction; use a new output directory')
                        prediction = read(prediction_path)
                        if prediction['source'] != source or prediction['cache']['result_sha256'] != record['cache_result_sha256']:
                            raise ValueError('saved reconstruction source changed')
                        record['postprocessing_execution'] = 'reused_this_reanalysis_prediction'
                    elif args.inventory_only:
                        record['status'] = 'qualified_cache_ready'
                        prediction = None
                    else:
                        prediction, candidates = build_predictions(asset, cache, source, beat, downbeat, ranking_policy=args.candidate_ranking_policy)
                        save(prediction_path.with_name('candidates.json'), candidates)
                        save(prediction_path, prediction)
                        record['postprocessing_execution'] = 'executed_existing_frozen_paths'
                    if prediction is not None:
                        record.update(status='predictions_saved', candidates_path=str(prediction_path.with_name('candidates.json')),
                            candidates_sha256=sha256(prediction_path.with_name('candidates.json')), prediction_path=str(prediction_path),
                            prediction_sha256=sha256(prediction_path), methods=list(prediction['methods']))
                        checkpoint_rows=merge_prediction_rows([*processed_rows,record],list(previous_predictions.values()))
                        save(args.output_dir/'manifest.json',{**manifest,'rows':checkpoint_rows,'complete':False})
                        # Predictions are on disk before reference event files are consumed.
                        score_path = args.output_dir / 'scores' / asset['id'] / (model + '.json')
                        score = {'id': asset['id'], 'model': model, 'cohort': asset['cohort'],
                            'prediction_path': str(prediction_path), 'prediction_sha256': sha256(prediction_path),
                            'evaluation_admission': record['evaluation_admission'], 'scores': None}
                        if record['evaluation_admission'] == 'admitted_reference':
                            ref = references[asset['id']]
                            if sha256(ref['path']) != ref['sha256']:
                                raise ValueError('reference bytes changed')
                            score.update(reference=ref, scores=score_methods(read(ref['path']), prediction['methods']))
                        else:
                            score['reason'] = record['evaluation_admission']
                        save(score_path, score)
                        record['score_path'] = str(score_path)
                    record['this_invocation_elapsed_seconds'] = time.perf_counter() - started
                except Exception as error:
                    record.update(status='reanalysis_failed', exception_type=type(error).__name__, reason=str(error))
            processed_rows.append(record)
            manifest['rows']=merge_prediction_rows(processed_rows,list(previous_predictions.values()))
            manifest['state_counts'] = dict(Counter(r['status'] for r in manifest['rows']))
            save(args.output_dir / 'manifest.json', manifest)
            print(asset['id'], model, record['status'], flush=True)
    manifest['complete'] = True
    manifest['all_available_selected_caches_completed'] = not any(r['status'] == 'reanalysis_failed' for r in manifest['rows'])
    save(args.output_dir / 'manifest.json', manifest)


if __name__ == '__main__':
    main()
