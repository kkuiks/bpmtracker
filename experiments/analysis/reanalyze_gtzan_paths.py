"""Replay preserved reconstruction paths on GTZAN feature-only logits.

No model inference, waveform loading, parameter search or reference alignment.
Predictions are saved before label content is opened. This is supplementary
beat/downbeat evidence, never an exact tempo/meter or audio-decoding benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
import time
import traceback

import numpy as np
import torch

from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from replay_integrity import require_file_hash, source_fingerprint
from run_crossed_benchmark import reconstruct_model, load_logits

METHODS = ('official_minimal', 'legacy_dbn', 'legacy_dbn_clock', 'meter_free_clock', 'clock_candidates_selected')
TOLERANCES = {'10ms': .01, '20ms': .02, '30ms': .03, '70ms': .07}
REPLAY_SOURCES = ('reanalyze_gtzan_paths.py', 'run_crossed_benchmark.py', 'ablate_clock_inputs.py',
    'clock_candidates.py', 'decode_pulses.py', 'fit_clock.py', 'legacy_dbn.py', 'run_beat_this.py',
    'compare_clock_candidates.py', 'grid_metrics.py', 'run_corpus_benchmark.py',
    'synthetic_groove.py', 'inspect_inputs.py', 'replay_integrity.py')


def write_json(path, value):
    """Replace a complete JSON document atomically on the destination filesystem."""
    path = Path(path)
    payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.' + path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def validate_completed_row(track, baseline, target, source_report, model_configuration):
    """Revalidate live inputs as well as saved predictions before a resume skip."""
    row = json.loads((target / 'result.json').read_text())
    if (row.get('id') != track['id'] or track['input']['kind'] != 'spectrogram' or
            row.get('feature_sha256') != track['input']['sha256'] or
            baseline.get('input_sha256') != track['input']['sha256'] or
            row.get('reference_sha256') != track['reference']['sha256'] or
            baseline.get('reference_sha256') != track['reference']['sha256']):
        raise ValueError('completed replay identity differs from frozen catalog/source report')
    require_file_hash(track['input']['path'], track['input']['sha256'], 'live source feature')
    require_file_hash(track['reference']['path'], track['reference']['sha256'], 'live reference')
    prediction_path = require_file_hash(target / 'predictions.json', row.get('predictions_sha256'), 'saved prediction')
    prediction = json.loads(prediction_path.read_text())
    provenance = prediction.get('provenance', {})
    if prediction.get('id') != track['id'] or prediction.get('references_used_for_prediction') is not False:
        raise ValueError('saved prediction identity or reference boundary changed')
    if (provenance.get('feature_sha256') != track['input']['sha256'] or
            Path(provenance.get('feature_path', '')).resolve() != Path(track['input']['path']).resolve()):
        raise ValueError('saved prediction feature binding changed')
    logits_path = source_report.parent / track['id'] / 'logits.npz'
    if Path(provenance.get('logits_path', '')).resolve() != logits_path.resolve():
        raise ValueError('saved prediction logits binding changed')
    require_file_hash(logits_path, provenance.get('logits_sha256'), 'live saved logits')
    require_file_hash(source_report.parent / track['id'] / 'result.json',
                      provenance.get('source_result_sha256'), 'live source result')
    if (provenance.get('source_checkpoint_sha256') != model_configuration.get('checkpoint_sha256') or
            provenance.get('fps') != 50. or provenance.get('duration_seconds') != track['duration_seconds'] or
            provenance.get('frame_time_offset_seconds') != 0):
        raise ValueError('saved prediction model or feature-clock binding changed')
    if prediction.get('candidate_count') is not None:
        require_file_hash(target / 'candidates.json', provenance.get('candidates_sha256'), 'saved candidate pool')
    return row


def score(reference, method, name):
    clock = method['clock']
    supported = name in ('legacy_dbn_clock', 'meter_free_clock', 'clock_candidates_selected')
    result = evaluate_times(reference, method['prediction']['beats_seconds'],
                            tempo_events(clock) if clock else None, tempo_map_supported=supported)
    downbeats = reference.get('downbeats_seconds')
    for label, tolerance in TOLERANCES.items():
        if name == 'clock_candidates_selected' or downbeats is None:
            result['downbeat_' + label] = None
        else:
            lo, hi = reference['evaluation_support_seconds']
            result['downbeat_' + label] = nearest_event_diagnostics(
                [v for v in downbeats if lo <= v <= hi],
                [v for v in method['prediction']['downbeats_seconds'] if lo <= v <= hi], tolerance)
    result['downbeat_output_status'] = 'unsupported' if name == 'clock_candidates_selected' else 'implemented'
    result['exact_tempo_meter_reference_status'] = 'unavailable_feature_only_human_event_annotations'
    return result


def summarize(rows, planned):
    result = {'planned_tracks': planned, 'finished_tracks': len(rows),
              'execution_error_tracks': sum(row.get('execution_error') is not None for row in rows),
              'unscored_tracks': sum(row.get('evaluation_status') != 'scored' for row in rows), 'methods': {}}
    for method in METHODS:
        values = [row['methods'][method] for row in rows if row.get('evaluation_status') == 'scored']
        result['methods'][method] = {'planned_tracks': planned, 'scored_tracks': len(values),
            'failed_output_tracks': sum(value['status'].startswith('execution_error') for value in values),
            'empty_prediction_tracks': sum(not value['prediction']['beats_seconds'] for value in values),
            'tempo_maps_produced': sum(value['clock'] is not None for value in values),
            'beat_macro_f1': {label: float(np.mean([v['metrics']['event_' + label]['f1'] for v in values])) if values else None
                              for label in TOLERANCES},
            'downbeat_scored_tracks': sum(v['metrics']['downbeat_20ms'] is not None for v in values),
            'downbeat_macro_f1': {label: float(np.mean([v['metrics']['downbeat_' + label]['f1'] for v in values
                                                      if v['metrics']['downbeat_' + label] is not None]))
                                 if any(v['metrics']['downbeat_' + label] is not None for v in values) else None
                                 for label in TOLERANCES}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--source-report', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--candidate-ranking-policy', choices=('legacy','balanced_evidence'), default='legacy')
    parser.add_argument('--stop-after', type=int, help='bounded execution probe; catalog planned count remains unchanged')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    catalog = json.loads(args.catalog.read_text())
    source = json.loads(args.source_report.read_text())
    saved = {row['id']: row for row in source['tracks']}
    if not source['complete'] or set(saved) != {row['id'] for row in catalog['tracks']}:
        parser.error('source report must completely match the catalog')
    configuration = {'schema_version': 1, 'scope': 'supplementary feature-only beat/downbeat reconstruction replay',
        'catalog': str(args.catalog), 'catalog_sha256': sha256(args.catalog),
        'source_report': str(args.source_report), 'source_report_sha256': sha256(args.source_report),
        'source_model_configuration': source['configuration'],
        'source_hashes': source_fingerprint(REPLAY_SOURCES),
        'threads': args.threads, 'candidate_ranking_policy': args.candidate_ranking_policy, 'methods': METHODS, 'model_inference_performed': False,
        'references_used_for_predictions': False, 'reference_alignment_applied': False,
        'all_methods_use_same_preserved_logits_and_feature_clock': True,
        'limits': ['No local waveform', 'Human event annotation, not exact authored tempo or meter map',
                   'Feature-hash deduplication is not independent musical content deduplication',
                   'Candidate downbeats unsupported; full-map success unmeasured']}
    # JSON round-trip makes tuple/list identity stable for resumption.
    configuration = json.loads(json.dumps(configuration))
    if args.output_dir.exists():
        if not args.resume or json.loads((args.output_dir / 'configuration.json').read_text()) != configuration:
            parser.error('resume requires exactly matching frozen configuration')
    else:
        args.output_dir.mkdir(parents=True)
        write_json(args.output_dir / 'configuration.json', configuration)
    rows = []; started = time.perf_counter(); newly_executed = 0
    for track in catalog['tracks']:
        target = args.output_dir / track['id']; result_path = target / 'result.json'
        if result_path.is_file():
            row = validate_completed_row(track, saved[track['id']], target, args.source_report, source['configuration'])
            rows.append(row)
            continue
        if args.stop_after is not None and newly_executed >= args.stop_after:
            break
        target.mkdir(exist_ok=True); begin = time.perf_counter(); baseline = saved[track['id']]
        if track['input']['kind'] != 'spectrogram': raise ValueError('expected feature-only input')
        if sha256(track['input']['path']) != track['input']['sha256'] or baseline['input_sha256'] != track['input']['sha256']:
            raise ValueError('source feature mismatch: ' + track['id'])
        if baseline['reference_sha256'] != track['reference']['sha256']:
            raise ValueError('reference identity mismatch: ' + track['id'])
        logits_path = args.source_report.parent / track['id'] / 'logits.npz'
        beat, downbeat, fps = load_logits(logits_path, track['duration_seconds'], expected_fps=50.)
        methods = {'official_minimal': {'prediction': baseline['variants']['official_minimal'], 'clock': None,
                                       'status': 'preserved_official_output'},
                   'legacy_dbn': {'prediction': baseline['variants']['legacy_dbn'], 'clock': None,
                                  'status': 'preserved_legacy_dbn_output'},
                   'legacy_dbn_clock': {'prediction': baseline['variants']['clock_pipeline'], 'clock': baseline['clock'],
                                        'status': baseline['clock_status']}}
        execution_error = None; candidate_count = None
        try:
            replay = reconstruct_model(beat, downbeat, fps, baseline['variants']['official_minimal'], track['duration_seconds'],
                candidate_ranking_policy=args.candidate_ranking_policy)
            methods['meter_free_clock'] = replay['clock_current']
            methods['clock_candidates_selected'] = replay['clock_candidates_selected']
            candidate_count = len(replay['candidate_set']['candidates'])
            write_json(target / 'candidates.json', replay['candidate_set'])
        except Exception as error:
            execution_error = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
            for name in ('meter_free_clock', 'clock_candidates_selected'):
                methods[name] = {'prediction': {'beats_seconds': [], 'downbeats_seconds': []},
                                 'clock': None, 'status': 'execution_error_reconstruction'}
        prediction_seconds = time.perf_counter() - begin
        predictions = {'id': track['id'], 'methods': methods, 'candidate_count': candidate_count,
            'provenance': {'feature_path': track['input']['path'], 'feature_sha256': track['input']['sha256'],
                'logits_path': str(logits_path), 'logits_sha256': sha256(logits_path),
                'source_result_sha256': sha256(args.source_report.parent / track['id'] / 'result.json'),
                'candidates_sha256': sha256(target / 'candidates.json') if candidate_count is not None else None,
                'source_checkpoint_sha256': source['configuration']['checkpoint_sha256'],
                'fps': fps, 'duration_seconds': track['duration_seconds'], 'frame_time_offset_seconds': 0},
            'references_used_for_prediction': False, 'execution_error': execution_error}
        write_json(target / 'predictions.json', predictions)
        # Label content is first opened only after the durable predictions above.
        if sha256(track['reference']['path']) != track['reference']['sha256']:
            raise ValueError('reference bytes changed: ' + track['id'])
        reference = json.loads(Path(track['reference']['path']).read_text())
        for name, method in methods.items(): method['metrics'] = score(reference, method, name)
        row = {'id': track['id'], 'genre': track['genre'], 'group_id': track['group_id'],
            'feature_sha256': track['input']['sha256'], 'reference_sha256': track['reference']['sha256'],
            'predictions_sha256': sha256(target / 'predictions.json'), 'methods': methods,
            'execution_error': execution_error, 'candidate_count': candidate_count,
            'evaluation_status': 'scored', 'timing_seconds': {'prediction_and_input_validation': prediction_seconds,
                                                          'total': time.perf_counter() - begin}}
        write_json(result_path, row); rows.append(row); newly_executed += 1
        if newly_executed % 20 == 0:
            print(json.dumps({'finished': len(rows), 'newly_executed': newly_executed,
                'elapsed_seconds_this_invocation': time.perf_counter() - started,
                'candidate_count_last': candidate_count, 'id': track['id']}), flush=True)
        if newly_executed % 20 == 0 or len(rows) == len(catalog['tracks']):
            write_json(args.output_dir / 'report.json', {'configuration': configuration, 'complete': len(rows) == len(catalog['tracks']),
                'summary': summarize(rows, len(catalog['tracks'])), 'tracks': rows,
                'timing': {'saved_case_total_seconds': sum(r['timing_seconds']['total'] for r in rows),
                           'wall_seconds_this_invocation': time.perf_counter() - started,
                           'newly_executed_this_invocation': newly_executed}})
    report = {'configuration': configuration, 'complete': len(rows) == len(catalog['tracks']),
        'summary': summarize(rows, len(catalog['tracks'])), 'genre_summaries': {
            genre: summarize([row for row in rows if row['genre'] == genre], sum(t['genre'] == genre for t in catalog['tracks']))
            for genre in sorted({t['genre'] for t in catalog['tracks']})}, 'tracks': rows,
        'timing': {'saved_case_total_seconds': sum(r['timing_seconds']['total'] for r in rows),
                   'wall_seconds_this_invocation': time.perf_counter() - started,
                   'newly_executed_this_invocation': newly_executed}}
    write_json(args.output_dir / 'report.json', report)
    print(json.dumps({'output_dir': str(args.output_dir), 'complete': report['complete'],
                      'summary': report['summary'], 'timing': report['timing']}), flush=True)


if __name__ == '__main__': main()
