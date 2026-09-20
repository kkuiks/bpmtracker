"""Cross two frozen acoustic models with the same two reconstruction paths.

Own-model official decoders are separate practical baselines. Both crossed
paths consume native-frame logits; the new path uses a common minimal peak
decoder for its seed events, avoiding a Beat Transformer DBN seed confound.
Ground truth is read only after all four crossed predictions are complete.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import torch
from beat_this.model.postprocessor import Postprocessor

from ablate_clock_inputs import fit_prediction
from clock_candidates import generate_clock_candidates, tempo_events
from compare_clock_candidates import evaluate_times
from decode_pulses import decode_pulses, retain_nearby_downbeats
from inspect_inputs import sha256
from run_beat_this import validate_events


def source_compatibility(catalog_track, beat_this_track, transformer_result):
    record = catalog_track['input']
    if record['kind'] != 'audio':
        raise ValueError('crossed acoustic comparison requires the same canonical audio, not feature-only inputs')
    path = Path(record['path'])
    digest = sha256(path)
    if digest != record['sha256'] or digest != beat_this_track['input_sha256']:
        raise ValueError('Beat This / catalog source audio hash mismatch')
    audio = transformer_result['audio']
    if audio['sha256'] != digest:
        raise ValueError('the two models did not analyze the same source audio bytes')
    info = sf.info(path)
    if (audio['sample_rate'] != info.samplerate or audio['channels'] != info.channels or
            audio['source_frames'] != info.frames or audio['analyzed_frames'] != info.frames):
        raise ValueError('source format or analyzed duration mismatch; prefixes cannot stand in for full songs')
    duration = info.frames / info.samplerate
    if (abs(audio['duration_seconds'] - duration) > 1 / info.samplerate or
            abs(beat_this_track['duration_seconds'] - duration) > 1 / info.samplerate or
            abs(catalog_track['duration_seconds'] - duration) > 1 / info.samplerate):
        raise ValueError('source duration metadata mismatch')
    if audio['source_frame_offset'] != 0 or transformer_result['model']['frame_time_offset_seconds'] != 0:
        raise ValueError('nonzero source/frame origin requires an explicit independently verified adapter')
    return {'path': str(path), 'sha256': digest, 'sample_rate': info.samplerate,
            'channels': info.channels, 'frames': info.frames, 'duration_seconds': duration,
            'source_frame_offset': 0, 'same_canonical_audio_verified': True}


def load_logits(path, duration, expected_fps=None):
    with np.load(path, allow_pickle=False) as saved:
        beat, downbeat = np.asarray(saved['beat']), np.asarray(saved['downbeat'])
        fps = float(saved['fps'])
        if ('source_frame_offset' in saved and int(saved['source_frame_offset']) != 0) or (
                'frame_time_offset_seconds' in saved and float(saved['frame_time_offset_seconds']) != 0):
            raise ValueError('logit source origin is nonzero')
    if (beat.ndim != 1 or downbeat.shape != beat.shape or not len(beat) or
            not np.isfinite(beat).all() or not np.isfinite(downbeat).all() or not np.isfinite(fps) or fps <= 0):
        raise ValueError('invalid native-frame logits')
    if expected_fps is not None and abs(fps - expected_fps) > 1e-10:
        raise ValueError('logit frame rate disagrees with model provenance')
    if len(beat) / fps < duration - 1 / fps:
        raise ValueError('logits do not cover the full source duration')
    return beat, downbeat, fps


def clip_prediction(prediction, duration):
    result, discarded = {}, {}
    for key in ('beats_seconds', 'downbeats_seconds'):
        values = validate_events(prediction.get(key, []))
        kept = values[(values >= 0) & (values < duration)]
        result[key] = kept.tolist()
        discarded[key] = len(values) - len(kept)
    return result, discarded


def common_minimal(beat_logits, downbeat_logits, fps, duration):
    decoder = Postprocessor(type='minimal', fps=fps)
    beats, downbeats = decoder(torch.as_tensor(beat_logits), torch.as_tensor(downbeat_logits))
    return clip_prediction({'beats_seconds': beats.tolist(), 'downbeats_seconds': downbeats.tolist()}, duration)[0]


def reconstruct_model(beat_logits, downbeat_logits, fps, official, duration):
    """Pure prediction stage: no references, reference paths, or score inputs."""
    official, official_clipped = clip_prediction(official, duration)
    minimal = common_minimal(beat_logits, downbeat_logits, fps, duration)
    pulses = decode_pulses(beat_logits, fps=fps)
    pulses = pulses[(pulses >= 0) & (pulses < duration)]
    downbeats = retain_nearby_downbeats(pulses, minimal['downbeats_seconds'])
    proposal, fitted, status = fit_prediction({'beats_seconds': pulses.tolist(), 'downbeats_seconds': downbeats.tolist()})
    fitted, current_clipped = clip_prediction(fitted, duration)
    candidates = generate_clock_candidates(beat_logits, downbeat_logits, fps, minimal['beats_seconds'])
    by_id = {c['id']: c for c in candidates['candidates']}
    selected = by_id.get(candidates['selected_candidate_id'])
    chosen = {'beats_seconds': [e['source_seconds'] for e in selected['indexed_grid']],
              'downbeats_seconds': []} if selected else {'beats_seconds': [], 'downbeats_seconds': []}
    chosen, selected_clipped = clip_prediction(chosen, duration)
    return {'official': {'prediction': official, 'clock': None, 'status': 'own_model_official_decoder',
                         'discarded_outside_source': official_clipped},
            'common_minimal': {'prediction': minimal, 'clock': None, 'status': 'shared_minimal_seed_decoder'},
            'clock_current': {'prediction': fitted, 'clock': proposal, 'status': status,
                              'discarded_outside_source': current_clipped},
            'clock_candidates_selected': {'prediction': chosen, 'clock': selected['clock'] if selected else None,
                    'status': candidates['selection_status'], 'selected_candidate_id': candidates['selected_candidate_id'],
                    'discarded_outside_source': selected_clipped},
            'candidate_set': candidates,
            'native_frame_rate': fps,
            'decoder_control': {'minimal_peak_window_frames': 7, 'minimal_threshold_logit': 0,
                'current_pulse_range_per_minute': [55, 215],
                'native_frame_period_discretization_retained': True,
                'source_time_offset_seconds': 0,
                'candidate_seed': 'same minimal decoder for both models; own official DBN not used as seed'}}


def score_model(reference, predictions):
    """Labels enter only here, after reconstruction has completed for both models."""
    metrics = {}
    for name in ('official', 'common_minimal', 'clock_current', 'clock_candidates_selected'):
        method = predictions[name]
        metrics[name] = evaluate_times(reference, method['prediction']['beats_seconds'],
                                        tempo_events(method['clock']) if method['clock'] else None)
    candidate_metrics = {}
    for candidate in predictions['candidate_set']['candidates']:
        candidate_metrics[candidate['id']] = evaluate_times(reference,
            [e['source_seconds'] for e in candidate['indexed_grid']], candidate['tempo_events'], candidate)
    oracle = {'diagnostic_only': True, 'reference_used_for_candidate_choice': True,
              'full_map_candidate_recall': None,
              'reason': 'candidate relative quarter origins and meter are unresolved',
              'candidate_scores': candidate_metrics}
    for metric in ('event_20ms', 'event_70ms'):
        key = max(candidate_metrics, key=lambda k: candidate_metrics[k][metric]['f1']) if candidate_metrics else None
        oracle[metric] = {'candidate_id': key, 'scores': candidate_metrics[key] if key else None}
    return metrics, oracle


def summarize(rows):
    result = {}
    for cohort in sorted({r['cohort'] for r in rows}):
        subset = [r for r in rows if r['cohort'] == cohort]
        methods = {}
        for name in subset[0]['methods']:
            methods[name] = {'count': len(subset), 'macro_event_f1': {
                threshold: float(np.mean([r['methods'][name]['metrics'][threshold]['f1'] for r in subset]))
                for threshold in ('event_20ms', 'event_70ms')}}
        result[cohort] = {'track_count': len(subset), 'methods': methods,
                         'scope': 'event metrics, not exact authored-map success; oracle results kept outside this table'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--beat-this-reports', type=Path, nargs='+', required=True)
    parser.add_argument('--catalogs', type=Path, nargs='+', required=True)
    parser.add_argument('--beat-transformer-results-dir', type=Path, required=True)
    parser.add_argument('--track', nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('output must be a new directory')
    catalog_entries = {t['id']: (t, p.parent.name) for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    baseline = {}
    for path in args.beat_this_reports:
        report = json.loads(path.read_text())
        for track in report['tracks']:
            baseline[track['id']] = (track, path.parent / track['id'], report['configuration'])
    if not set(args.track) <= baseline.keys() & catalog_entries.keys():
        parser.error('requested tracks missing from reports or catalogs')
    # Verify all input pairs before creating an incomplete output directory.
    inputs = []
    for track_id in args.track:
        track, location, model_config = baseline[track_id]
        record, cohort = catalog_entries[track_id]
        bt_location = args.beat_transformer_results_dir / track_id
        bt = json.loads((bt_location / 'result.json').read_text())
        source = source_compatibility(record, track, bt)
        inputs.append((track_id, record, cohort, track, location, model_config, bt_location, bt, source))
    args.output_dir.mkdir(parents=True)
    files = ('run_crossed_benchmark.py', 'clock_candidates.py', 'decode_pulses.py', 'fit_clock.py',
             'ablate_clock_inputs.py', 'grid_metrics.py', 'compare_clock_candidates.py', 'legacy_dbn.py')
    configuration = {'schema_version': 'crossed-clock-benchmark-v1',
        'source_hashes': {f: sha256(Path(__file__).with_name(f)) for f in files},
        'reports': [{'path': str(p), 'sha256': sha256(p)} for p in args.beat_this_reports],
        'catalogs': [{'path': str(p), 'sha256': sha256(p)} for p in args.catalogs],
        'models': ['beat_this', 'beat_transformer'], 'reconstructors': ['clock_current', 'clock_candidates_selected'],
        'references_used_for_prediction': False, 'automatic_reference_alignment': False,
        'seed_decoder_control': 'common minimal on native-frame logits; each own official result is separate',
        'scope': 'same-audio event and tempo diagnostics; final authored meter/origin still requires qualification'}
    output = {'configuration': configuration, 'tracks': [], 'complete': False}
    for track_id, record, cohort, track, location, model_config, bt_location, bt, source in inputs:
        started = time.perf_counter()
        model_inputs = {
            'beat_this': {'location': location, 'official': track['variants']['official_minimal'],
                         'expected_fps': 50., 'model_provenance': model_config},
            'beat_transformer': {'location': bt_location,
                                'official': {'beats_seconds': bt['beats_seconds'], 'downbeats_seconds': bt['downbeats_seconds']},
                                'expected_fps': bt['model']['frame_rate'],
                                'model_provenance': {'model': bt['model'], 'frontend': bt['frontend'], 'execution': bt['execution']}}}
        predictions, provenance = {}, {}
        target = args.output_dir / track_id
        for name, values in model_inputs.items():
            logits_path = values['location'] / 'logits.npz'
            beat, downbeat, fps = load_logits(logits_path, source['duration_seconds'], values['expected_fps'])
            inference_started = time.perf_counter()
            predictions[name] = reconstruct_model(beat, downbeat, fps, values['official'], source['duration_seconds'])
            model_target = target / name
            model_target.mkdir(parents=True)
            provenance[name] = {'logits_path': str(logits_path), 'logits_sha256': sha256(logits_path),
                                'result_sha256': sha256(values['location'] / 'result.json'),
                                'model_provenance': values['model_provenance'],
                                'reconstruction_seconds': time.perf_counter() - inference_started}
            candidates = predictions[name]['candidate_set']
            candidates['input_provenance'] = {'audio': source, **provenance[name]}
            (model_target / 'candidates.json').write_text(json.dumps(candidates, indent=2, allow_nan=False) + '\n')
            slim = {k: v for k, v in predictions[name].items() if k != 'candidate_set'}
            (model_target / 'predictions.json').write_text(json.dumps(slim, indent=2, allow_nan=False) + '\n')
        reference_record = record['reference']
        if sha256(reference_record['path']) != reference_record['sha256']:
            raise ValueError('reference changed')
        reference = json.loads(Path(reference_record['path']).read_text())
        row = {'id': track_id, 'dataset': track['dataset'], 'cohort': cohort, 'source': source,
               'reference_sha256': reference_record['sha256'], 'methods': {}, 'oracle_diagnostics': {},
               'model_provenance': provenance, 'candidate_sets': {name: str(target / name / 'candidates.json') for name in predictions}}
        for name, model_predictions in predictions.items():
            scores, oracle = score_model(reference, model_predictions)
            row['oracle_diagnostics'][name] = oracle
            for method, metrics in scores.items():
                row['methods'][name + '__' + method] = {**model_predictions[method], 'metrics': metrics}
        row['elapsed_seconds'] = time.perf_counter() - started
        output['tracks'].append(row)
        output['summary'] = summarize(output['tracks'])
        output['complete'] = len(output['tracks']) == len(inputs)
        (args.output_dir / 'report.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n')
        print(track_id, {name: round(v['metrics']['event_70ms']['f1'], 4) for name, v in row['methods'].items()}, flush=True)
    print(json.dumps(output['summary'], indent=2))


if __name__ == '__main__':
    main()
