"""Evaluate frozen candidate generation and selection; oracle scores are diagnostic.

No annotation is passed to candidate generation. Existing reports and catalogs
are preserved. Candidate-relative index zero is never aligned to reference zero.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from clock_candidates import CandidateConfig, generate_clock_candidates, tempo_events
from grid_metrics import (indexed_grid_metrics, nearest_event_diagnostics,
                          pulse_level_diagnostics, tempo_change_metrics,
                          temporal_span_coverage)
from inspect_inputs import sha256


def reference_tempo_changes(reference):
    events = reference.get('tempo_events')
    if events is None or not events:
        return None
    lo, hi = reference['evaluation_support_seconds']
    return [{'source_seconds': b['time_seconds'], 'bpm_before': a['bpm_quarter'],
             'bpm_after': b['bpm_quarter'], 'type': 'step'}
            for a, b in zip(events, events[1:]) if lo < b['time_seconds'] < hi
            and abs(a['bpm_quarter'] - b['bpm_quarter']) > 1e-8]


def evaluate_tempo_map(reference, changes=None, *, tempo_map_supported=None):
    """Score map-capable failures without conflating unsupported functionality.

    None preserves the historical caller contract. New comparison callers must
    explicitly declare capability: a capable path that returns no map misses
    every qualified reference change, even if its fallback still returns beats.
    Missing reference labels remain unscored. An empty constant reference does
    not make a missing map successful; tempo_map_status retains the failure.
    """
    if tempo_map_supported not in (None, True, False):
        raise ValueError('tempo_map_supported must be True, False, or None')
    if tempo_map_supported is False and changes is not None:
        raise ValueError('unsupported tempo-map path cannot supply map changes')
    lo, hi = reference['evaluation_support_seconds']
    scored = None if changes is None else [e for e in changes if lo < e['source_seconds'] < hi]
    outside = [] if changes is None else [e for e in changes if not lo < e['source_seconds'] < hi]
    if tempo_map_supported is False:
        status = 'unsupported_tempo_map'
    elif changes is None:
        status = 'failed_no_tempo_map' if tempo_map_supported else 'no_tempo_map'
    else:
        status = 'tempo_map_produced'
    result = {'tempo_map_status': status,
              'tempo_change_evaluation_support': {
                  'seconds': [lo, hi], 'rule': 'strict lower < time < upper for both reference and prediction',
                  'outside_prediction_count': len(outside), 'outside_prediction_events': outside,
                  'full_prediction_map_modified': False}}
    for label, tolerance in (('100ms', .1), ('500ms', .5)):
        if status in ('unsupported_tempo_map', 'no_tempo_map'):
            score = {'status': status}
        else:
            score = tempo_change_metrics(reference_tempo_changes(reference), scored or [],
                                         time_tolerance_seconds=tolerance, rate_tolerance_bpm=.1)
            score['prediction_status'] = status
            if status == 'failed_no_tempo_map' and score['status'] == 'scored':
                score['status'] = 'failed_no_tempo_map'
                if not (score['full_change_scores']['true_positives'] +
                        score['full_change_scores']['false_negatives']):
                    # No change event exists to miss, but no map was delivered.
                    # Avoid presenting a vacuous F1=1 as successful map output.
                    for key in ('precision', 'recall', 'f1'):
                        score['full_change_scores'][key] = None
        result['tempo_changes_' + label] = score
    return result


def evaluate_times(reference, predicted_times, changes=None, candidate=None, *, tempo_map_supported=None):
    lo, hi = reference['evaluation_support_seconds']
    truth = np.asarray(reference['beats_seconds'], dtype=float)
    truth = truth[(truth >= lo) & (truth <= hi)]
    predicted = np.asarray(predicted_times, dtype=float)
    predicted = predicted[(predicted >= lo) & (predicted <= hi)]
    result = {'event_10ms': nearest_event_diagnostics(truth, predicted, .01),
              'event_20ms': nearest_event_diagnostics(truth, predicted, .02),
              'event_30ms': nearest_event_diagnostics(truth, predicted, .03),
              'event_70ms': nearest_event_diagnostics(truth, predicted, .07),
              'pulse_density_diagnostic': pulse_level_diagnostics(truth, predicted),
              'source_span_coverage': temporal_span_coverage(truth, predicted[0], predicted[-1]) if len(predicted) else None,
              **evaluate_tempo_map(reference, changes, tempo_map_supported=tempo_map_supported)}
    candidate_events = [{'index': e['quarter_position'], 'time_seconds': e['source_seconds']}
                        for e in candidate['indexed_grid']] if candidate else []
    result['indexed_grid'] = indexed_grid_metrics(
        [{'index': i, 'time_seconds': float(t)} for i, t in enumerate(truth)], candidate_events,
        origin_status='unanchored')
    result['full_tempo_meter_map_status'] = 'unscored_unanchored_indices_and_unresolved_meter'
    return result


def summarize(rows):
    summary = {}
    for cohort in sorted({r.get('cohort', r['dataset']) for r in rows}):
        selected = [r for r in rows if r.get('cohort', r['dataset']) == cohort]
        values = {}
        for name in ('official_raw', 'current_clock', 'selected_candidate', 'oracle_event_20ms', 'oracle_event_70ms'):
            eligible = [r[name] for r in selected if r.get(name) is not None]
            values[name] = {'track_count': len(eligible),
                           'macro_f1_20ms': float(np.mean([r['event_20ms']['f1'] for r in eligible])) if eligible else None,
                           'macro_f1_70ms': float(np.mean([r['event_70ms']['f1'] for r in eligible])) if eligible else None}
        summary[cohort] = {'tracks': len(selected), 'methods': values,
                            'empty_candidate_tracks': sum(not r['candidate_count'] for r in selected),
                            'warning': 'Oracle chooses with references and is not deployable; no exact-map accuracy established.'}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--catalogs', type=Path, nargs='+', required=True)
    parser.add_argument('--clock-reports', type=Path, nargs='*', default=[])
    parser.add_argument('--track', nargs='*')
    parser.add_argument('--model-results-dir', type=Path)
    parser.add_argument('--model-label', default='beat-this-final0')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('output must be a new directory')
    catalogs = {t['id']: t for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    cohorts = {t['id']: p.parent.name for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    entries = [(t, p.parent / t['id']) for p in args.reports for t in json.loads(p.read_text())['tracks']
               if not args.track or t['id'] in args.track]
    if args.track and set(args.track) != {t['id'] for t, _ in entries}:
        parser.error('some requested tracks are missing')
    current = {t['id']: t['methods']['meter_free_clock'] for p in args.clock_reports
               for t in json.loads(p.read_text())['tracks']}
    args.output_dir.mkdir(parents=True)
    configuration = {'schema_version': 'candidate-comparison-v1', 'model_label': args.model_label,
        'config': CandidateConfig().__dict__,
        'source_hashes': {name: sha256(Path(__file__).with_name(name)) for name in
                          ('clock_candidates.py', 'compare_clock_candidates.py', 'fit_clock.py', 'grid_metrics.py')},
        'source_reports': [{'path': str(p), 'sha256': sha256(p)} for p in args.reports + args.clock_reports],
        'catalogs': [{'path': str(p), 'sha256': sha256(p)} for p in args.catalogs],
        'reference_used_for_prediction_or_ranking': False,
        'oracle_scope': 'per-metric best candidate using references; diagnostic only',
        'meter_and_shared_musical_origin': 'unresolved; full-map success is not measured',
        'qualification_warning': 'BabySlakh is rendered MIDI timing; authored interpretation requires separate qualification. GTZAN is human beat labels on features.'}
    (args.output_dir / 'configuration.json').write_text(json.dumps(configuration, indent=2) + '\n')
    report = {'configuration': configuration, 'tracks': [], 'complete': False}
    for index, (track, location) in enumerate(entries):
        started = time.perf_counter()
        official = track['variants']['official_minimal']
        if args.model_results_dir:
            location = args.model_results_dir / track['id']
            alternate = json.loads((location / 'result.json').read_text())
            official = {'beats_seconds': alternate['beats_seconds'],
                        'downbeats_seconds': alternate.get('downbeats_seconds', [])}
        logits_path = location / 'logits.npz'
        logits = np.load(logits_path)
        # Model runners must declare any nonzero frame origin rather than have
        # the candidate decoder silently realign it to a reference annotation.
        if ('frame_time_offset_seconds' in logits and float(logits['frame_time_offset_seconds']) != 0) or (
                'source_frame_offset' in logits and int(logits['source_frame_offset']) != 0):
            raise ValueError('nonzero model frame origin requires an explicit input adapter')
        candidates = generate_clock_candidates(logits['beat'], logits['downbeat'],
                                                float(logits['fps']),
                                                [v for v in official['beats_seconds'] if 0 <= v < catalogs[track['id']]['duration_seconds']],
                                                source_duration_seconds=catalogs[track['id']]['duration_seconds'])
        prediction_finished = time.perf_counter()
        target = args.output_dir / track['id']
        target.mkdir()
        candidates['input_provenance'] = {'logits_path': str(logits_path), 'logits_sha256': sha256(logits_path),
                                          'model_label': args.model_label}
        (target / 'candidates.json').write_text(json.dumps(candidates, indent=2, allow_nan=False) + '\n')
        record = catalogs[track['id']]['reference']
        if sha256(record['path']) != record['sha256']:
            raise ValueError('reference hash mismatch')
        reference = json.loads(Path(record['path']).read_text())
        previous = current.get(track['id'])
        previous_prediction = previous['prediction'] if previous else track['variants']['clock_pipeline']
        previous_clock = previous['clock'] if previous else track['clock']
        row = {'id': track['id'], 'dataset': track['dataset'], 'cohort': cohorts[track['id']],
               'candidate_count': len(candidates['candidates']),
               'reference_sha256': record['sha256'], 'selected_candidate_id': candidates['selected_candidate_id'],
               'selection_status': candidates['selection_status'],
               'candidate_generation_seconds': prediction_finished - started,
               'official_raw': evaluate_times(reference, official['beats_seconds']),
               'current_clock': evaluate_times(reference, previous_prediction['beats_seconds'],
                                               tempo_events(previous_clock) if previous_clock else None),
               'current_clock_model_label': 'existing-beat-this-final0',
               'selected_candidate': None, 'candidate_scores': {},
               'oracle_event_20ms': None, 'oracle_event_70ms': None,
               'oracle_ids': {}, 'full_map_candidate_recall': None}
        for candidate in candidates['candidates']:
            scores = evaluate_times(reference, [e['source_seconds'] for e in candidate['indexed_grid']],
                                    candidate['tempo_events'], candidate)
            row['candidate_scores'][candidate['id']] = scores
            if candidate['id'] == candidates['selected_candidate_id']:
                row['selected_candidate'] = scores
        for metric in ('event_20ms', 'event_70ms'):
            if row['candidate_scores']:
                best_id = max(row['candidate_scores'], key=lambda key: row['candidate_scores'][key][metric]['f1'])
                row['oracle_ids'][metric] = best_id
                row['oracle_' + metric] = row['candidate_scores'][best_id]
        row['elapsed_seconds'] = time.perf_counter() - started
        report['tracks'].append(row)
        report['summary'] = summarize(report['tracks'])
        report['complete'] = index + 1 == len(entries)
        (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(track['id'], 'candidates', row['candidate_count'], 'selected', row['selected_candidate_id'],
              'seconds', round(row['candidate_generation_seconds'], 2), flush=True)
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
