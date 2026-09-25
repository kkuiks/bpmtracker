"""Re-score preserved bounded experiments without rerunning their algorithms.

Retains full/partial, assisted, and oracle scopes, original comparison windows,
and original prediction files. Owner-rejected references remain diagnostics.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import time

import numpy as np

from bar_metrics import score_bar_changes
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from fit_clock import clock_time
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256

ROOT = Path('data/runs')
CATALOGS = [Path('data/corpus/public/babyslakh-development/catalog-rendered-clock.json'),
            Path('data/corpus/public/forestry-pilot-v1/catalog.json'),
            Path('data/corpus/public/gtzan-development/catalog.json')]
PRIOR_PATHS = [('0.5', ROOT / 'tempo-prior/ablation-strength05-v1/report.json'),
               ('1', ROOT / 'tempo-prior/ablation-v1/report.json'),
               ('2', ROOT / 'tempo-prior/ablation-strength2-v1/report.json')]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def summary(rows):
    groups = {}
    for row in rows:
        key = '/'.join(str(row[k]) for k in ('experiment', 'setting', 'scope', 'cohort', 'model', 'method'))
        groups.setdefault(key, []).append(row)
    result = {}
    for key, values in groups.items():
        metric = {'case_count': len(values), 'distinct_tracks': len({r['track_id'] for r in values}),
            'beat_macro_f1': {label: float(np.mean([r['metrics']['event_' + label]['f1'] for r in values]))
                              for label in ('10ms', '20ms', '30ms', '70ms')},
            'tempo_map_failures': sum(r['metrics']['tempo_map_status'] == 'failed_no_tempo_map' for r in values)}
        for label in ('100ms', '500ms'):
            scores = [r['metrics']['tempo_changes_' + label].get('full_change_scores') for r in values]
            scores = [v for v in scores if v is not None]
            metric['tempo_changes_' + label] = ({
                **{k: sum(v[k] for v in scores) for k in ('true_positives', 'false_positives', 'false_negatives')},
                'eligible_cases': len(scores)} if scores else None)
        bars = [r['metrics'].get('bar_change_500ms') for r in values]
        bars = [v for v in bars if v is not None]
        if bars:
            metric['bar_changes_500ms'] = {k: sum(v[k] for v in bars)
                for k in ('reference_change_count', 'predicted_change_count', 'matched_count')}
        result[key] = metric
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--owner-decisions', type=Path, default=ROOT / 'status-audit/2026-09-25-v1/reference-review-batch1-v2/owner-decisions.json')
    args = parser.parse_args()
    if args.output_dir.exists(): parser.error('output must be new')
    started = time.perf_counter(); sources = {}; rows = []
    def read(path):
        path = Path(path); sources[str(path)] = sha256(path)
        return json.loads(path.read_text())
    records = {t['id']: t for path in CATALOGS for t in read(path)['tracks']}
    decisions = read(args.owner_decisions)
    rejected = set()
    for item in decisions['items']:
        if item['decision'] != 'reject_current_reference_for_accuracy_scoring': continue
        record = records[item['id']]
        if item['audio_sha256'] != record['input']['sha256'] or item['reference_sha256'] != record['reference']['sha256']:
            raise ValueError('owner decision identity changed')
        rejected.add(item['id'])
    references = {}
    def reference_for(track_id, expected_hash):
        record = records[track_id]['reference']
        if record['sha256'] != expected_hash: raise ValueError('historical reference mismatch: ' + track_id)
        if track_id not in references:
            value = read(record['path'])
            if sources[record['path']] != expected_hash: raise ValueError('reference file changed')
            references[track_id] = value
        return references[track_id]
    def append(track_id, reference, prediction, clock, old_metrics, *, experiment, setting,
               scope, cohort, model, method, source_path, capable=True, bars=None):
        metrics = evaluate_times(reference, prediction, tempo_events(clock) if clock else None,
                                 tempo_map_supported=capable)
        if old_metrics and 'indexed_grid' in old_metrics:
            metrics['original_indexed_grid_diagnostic'] = old_metrics['indexed_grid']
        if old_metrics and 'indexed_oracle_grid' in old_metrics:
            metrics['original_indexed_oracle_grid_diagnostic'] = old_metrics['indexed_oracle_grid']
        if bars is not None:
            lo, hi = reference['evaluation_support_seconds']; truth = reference.get('downbeats_seconds')
            for label, tolerance in (('10ms', .01), ('20ms', .02), ('30ms', .03), ('70ms', .07)):
                metrics['downbeat_' + label] = (nearest_event_diagnostics(
                    [t for t in truth if lo <= t <= hi], [t for t in bars['downbeats_seconds'] if lo <= t <= hi], tolerance)
                    if truth is not None else None)
            metrics['bar_change_500ms'] = score_bar_changes(reference, bars)
        difference = {}
        for label in ('10ms', '20ms', '30ms', '70ms'):
            old = (old_metrics or {}).get('event_' + label)
            if old is not None: difference['event_f1_' + label] = metrics['event_' + label]['f1'] - old['f1']
        for label in ('100ms', '500ms'):
            old = (old_metrics or {}).get('tempo_changes_' + label, {})
            difference['old_tempo_changes_' + label] = old.get('full_change_scores')
        rows.append({'track_id': track_id, 'experiment': experiment, 'setting': setting, 'scope': scope,
            'cohort': cohort, 'model': model, 'method': method, 'source_path': str(source_path),
            'reference_status': 'owner_rejected_diagnostic_only' if track_id in rejected else 'retained_declared_reference',
            'evaluation_support_seconds': reference['evaluation_support_seconds'],
            'metrics': metrics, 'original_metric_comparison': difference,
            'prediction_recomputed': False, 'automatic_accuracy_claim': scope not in ('oracle_pulses', 'creator_assisted', 'reference_control')})
    for strength, path in PRIOR_PATHS:
        report = read(path)
        for row in report['rows']:
            reference = reference_for(row['track_id'], row['reference_sha256'])
            if sha256(row['prediction_path']) != row['prediction_sha256_before_reference']:
                raise ValueError('historical prior prediction changed')
            sources[row['prediction_path']] = row['prediction_sha256_before_reference']
            if row['scope'] == 'partial_region':
                a,b = reference['evaluation_support_seconds']; lo,hi = row['fixed_evaluation_window']
                reference = {**reference, 'evaluation_support_seconds': [max(a,lo), min(b,hi)]}
            for method, value in row['methods'].items():
                append(row['track_id'], reference, value['prediction'], value['clock'], value['metrics'],
                       experiment='tempo_prior', setting=strength, scope=row['scope'], cohort=row['cohort'],
                       model=row['model'], method=method, source_path=path)
    path = ROOT / 'phase-alignment/benchmark-v1/report.json'; report = read(path)
    for row in report['rows']:
        reference = reference_for(row['track_id'], row['reference_sha256'])
        if sha256(row['prediction_path']) != row['prediction_sha256_before_reference']:
            raise ValueError('historical phase prediction changed')
        sources[row['prediction_path']] = row['prediction_sha256_before_reference']
        if row['scope'] == 'partial_region':
            a,b = reference['evaluation_support_seconds']; lo,hi = row['fixed_evaluation_window']
            reference = {**reference, 'evaluation_support_seconds': [max(a,lo), min(b,hi)]}
        for method, value in row['methods'].items():
            append(row['track_id'], reference, value['prediction'], value['clock'], value['metrics'],
                   experiment='phase_alignment', setting='prior_strength_2', scope=row['scope'], cohort=row['cohort'],
                   model=row['model'], method=method, source_path=path)
    path = ROOT / 'one-song/light-completion-v4/report.json'; report = read(path)
    reference = reference_for('forestry_light-has-come', report['reference_sha256'])
    for method, old in report['metrics'].items():
        clock = read(path.parent / (method + '-map.json'))
        scope = {'assisted': 'creator_assisted', 'reference': 'reference_control'}.get(method, 'conditional_full_completion')
        append('forestry_light-has-come', reference, clock['beats_seconds'], clock, old,
               experiment='light_completion', setting='preserved', scope=scope, cohort='forestry_producer_pilot',
               model='combined', method=method, source_path=path)
    path = ROOT / 'clock-ablation/short-change-v2b/report.json'; report = read(path)
    for row in report['tracks']:
        reference = reference_for(row['id'], row['reference_sha256'])
        full = np.asarray(reference['beats_seconds']); quarters = np.asarray(reference.get('quarter_indices', np.arange(len(full))))
        lo,hi = reference['evaluation_support_seconds']; quarters = quarters[(full >= lo) & (full <= hi)]
        relative = quarters - quarters[0]
        for condition, case in row['conditions'].items():
            for method, value in case['variants'].items():
                clock = value['proposal']; prediction = clock_time(relative, clock['knot_pulse_indices'], clock['coefficients']).tolist()
                append(row['id'], reference, prediction, clock, value['metrics'], experiment='short_change_oracle',
                       setting=condition, scope='oracle_pulses', cohort=row['dataset'], model='reference_input', method=method, source_path=path)
    path = ROOT / 'clock-ablation/bar70-v2/report.json'; report = read(path)
    clock_path = ROOT / 'clock-ablation/meter-free70-v1/report.json'; clock_report = read(clock_path)
    if sources[str(clock_path)] != report['clock_report_sha256']: raise ValueError('historical bar source changed')
    reference_hashes = {row['id']: row['reference_sha256'] for row in clock_report['tracks']}
    for row in report['tracks']:
        reference = reference_for(row['id'], reference_hashes[row['id']])
        for method, value in row['methods'].items():
            append(row['id'], reference, value['prediction']['beats_seconds'], None, None,
                   experiment='bar_structure', setting='preserved', scope='bar_grouping_quarter_hypothesis', cohort=row['dataset'],
                   model='beat_this', method=method, source_path=path, capable=False, bars=value['bars'])
    retained = [row for row in rows if row['track_id'] not in rejected]
    rejected_rows = [row for row in rows if row['track_id'] in rejected]
    all_changes = [value for row in rows for key,value in row['original_metric_comparison'].items()
                   if key.startswith('event_f1_')]
    output = {'schema_version': 1, 'scope': 'historical bounded saved-prediction rescoring, not new inference',
        'configuration': {'source_hashes': {name: sha256(Path(__file__).with_name(name)) for name in
            ('rescore_historical_status.py', 'compare_clock_candidates.py', 'grid_metrics.py', 'bar_metrics.py')},
            'owner_rejected_ids': sorted(rejected), 'original_prediction_files_changed': False,
            'models_or_fits_rerun': False, 'partial_windows_preserved': True},
        'complete': True, 'source_artifacts': [{'path': path, 'sha256': digest} for path,digest in sources.items()],
        'summary': summary(retained), 'retained_rows': retained,
        'rejected_reference_diagnostics': rejected_rows,
        'checks': {'all_comparable_original_event_f1_unchanged': all(abs(value) < 1e-12 for value in all_changes),
                   'compared_original_event_f1_count': len(all_changes),
                   'retained_method_cases': len(retained), 'rejected_method_cases': len(rejected_rows)},
        'timing_seconds': time.perf_counter() - started}
    args.output_dir.mkdir(parents=True); write_json(args.output_dir / 'report.json', output)
    print(json.dumps({'output': str(args.output_dir), 'checks': output['checks'], 'seconds': output['timing_seconds']}))


if __name__ == '__main__': main()
