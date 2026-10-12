"""Unchanged native map metric plus coarse event diagnostics; no selection repair."""
import argparse
from pathlib import Path
from collections import Counter
import numpy as np
from experiments.beat_event_map_v1.native_metrics import score as native_score
from experiments.continuous_beat_map_v1.map import grid, validate
from experiments.metronome_benchmark_v1.metrics import event_f1
from .common import read, write, digest, guard, stamp, POLICIES, PRIMARY, candidate_hashes, CANDIDATE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run
    guard(run)
    index = read(run / 'evaluation-index.json')['rows']
    rows, contracts, pairs = [], [], []
    methods = [PRIMARY, 'ORIGINAL_FIXED_UNIT']
    for item in index:
        ref = read(item['reference_path'])
        for method in methods:
            predictions = {}
            for policy in POLICIES:
                pred = read(run / 'predictions' / method / policy / (item['id'] + '.json'))
                returned = pred.get('status') == 'map'
                if returned:
                    metrics = native_score(pred, ref)
                    pulse = grid(pred, 'quarter')
                    bars = grid(pred, 'bar')
                    def supported(values):
                        return values[np.logical_or.reduce([(values >= a) & (values < b)
                                                           for a, b in ref['support']])]
                    beat_events = event_f1(supported(pulse), np.asarray(ref['quarters']), .07)
                    bar_events = event_f1(supported(bars), np.asarray(ref['bars']), .07)
                else:
                    metrics = {key: 0. for key in ('native_pulse_coherent_fraction', 'stable_native_map_fraction',
                               'bar_period_and_phase_fraction', 'native_coverage_fraction')}
                    metrics.update(unnecessary_native_changes=0, unsupported_native_changes=0,
                                   native_tempo_changes=0, native_meter_changes=0, native_changes=[])
                    beat_events = event_f1([], ref['quarters'], .07)
                    bar_events = event_f1([], ref['bars'], .07)
                rows.append({**item, 'method': method, 'policy': policy, 'returned_map': returned,
                             **metrics, 'canonical_beat_event_f1_70': beat_events,
                             'bar_event_f1_70': bar_events})
                contracts.append({'id': item['id'], 'method': method, 'policy': policy,
                                  'returned_map': returned, **validate(pred)})
                pred.pop('policy')
                predictions[policy] = pred
            folder = 'encoded-units' if method == PRIMARY else 'encoded-fixed-units'
            for policy in ('proxy97', 'proxy103'):
                same = read(run / folder / policy / (item['id'] + '.json')) == read(
                    run / folder / 'proxy100' / (item['id'] + '.json'))
                pairs.append({'id': item['id'], 'method': method, 'policy': policy,
                              'same_unit': same, 'identical_prediction': predictions[policy] == predictions['proxy100']})
    summaries = []
    for method in methods:
        for policy in POLICIES:
            for cohort in sorted({r['cohort'] for r in index}):
                selected = [r for r in rows if r['method'] == method and r['policy'] == policy and r['cohort'] == cohort]
                summaries.append({'method': method, 'policy': policy, 'cohort': cohort, 'inputs': len(selected),
                    'returned_maps': sum(r['returned_map'] for r in selected),
                    **{k: float(np.mean([r[k] for r in selected])) for k in (
                        'native_pulse_coherent_fraction', 'stable_native_map_fraction',
                        'bar_period_and_phase_fraction', 'native_coverage_fraction')},
                    **{k: sum(r[k] for r in selected) for k in (
                        'unnecessary_native_changes', 'unsupported_native_changes',
                        'native_tempo_changes', 'native_meter_changes')},
                    'perfect_joint_maps': sum(r['stable_native_map_fraction'] == 1 and r['unnecessary_native_changes'] == 0 for r in selected),
                    'joint_maps_at_least_98_percent': sum(r['stable_native_map_fraction'] >= .98 for r in selected),
                    'mean_canonical_beat_f1_70': float(np.mean([r['canonical_beat_event_f1_70']['f1'] for r in selected])),
                    'mean_bar_event_f1_70': float(np.mean([r['bar_event_f1_70']['f1'] for r in selected]))})
    by_genre = []
    for method in methods:
        for genre in sorted({r['genre'] for r in index if r['cohort'] == 'reserved_features'}):
            selected = [r for r in rows if r['method'] == method and r['policy'] == 'proxy100'
                        and r['cohort'] == 'reserved_features' and r['genre'] == genre]
            by_genre.append({'method': method, 'genre': genre, 'inputs': len(selected),
                'joint': float(np.mean([r['stable_native_map_fraction'] for r in selected])),
                'pulse': float(np.mean([r['native_pulse_coherent_fraction'] for r in selected])),
                'bar_f1_70': float(np.mean([r['bar_event_f1_70']['f1'] for r in selected]))})
    hashes = dict(read(run / 'input-freeze.json')['files'])
    for path in (run / 'source-before-tap-freeze').glob('*.json'):
        hashes.update(read(path)['files'])
    changed = [path for path, sha in hashes.items() if digest(path) != sha]
    audits = [read(path) for path in (run / 'worker-audit').glob('*.json')]
    forbidden = [path for a in audits for path in a['forbidden_reads']]
    map_checks = [r for r in contracts if r['returned_map']]
    audited_prepare = {ident for path in (run / 'worker-audit').glob('prepare-*.json')
                       for ident in read(path)['ids']}
    audited_predict = {ident for path in (run / 'worker-audit').glob('predict-*.json')
                       for ident in read(path)['ids']}
    ids = {r['id'] for r in index}
    passed = (not changed and not forbidden and audited_prepare == ids and audited_predict == ids
              and all(r['legal'] and r['continuous_source_coverage'] for r in map_checks)
              and all(not r['same_unit'] or r['identical_prediction'] for r in pairs))
    write(run / 'metrics.json', {'rows': rows, 'summary': summaries, 'genre_summary': by_genre,
          'failed_predictions_remain_in_denominators': True,
          'source_types_not_merged_for_approval': True})
    write(run / 'audit.json', {'at_utc': stamp(), 'all_pass': passed, 'maps': len(contracts),
          'returned_maps': len(map_checks), 'contracts': contracts, 'same_unit_pairs': pairs,
          'changed_inputs': changed, 'forbidden_reads': forbidden,
          'candidate_code_matches_original_freeze': read(CANDIDATE / 'freeze.json')['code_hashes'] == candidate_hashes(),
          'actual_prepare_and_predict_read_hooks_cover_selected_scope': audited_prepare == ids and audited_predict == ids,
          'no_tuning_after_validation': True, 'windows_audio_playback_tested': False})
    for r in summaries:
        if r['policy'] == 'proxy100':
            print(r['method'], r['cohort'], r['inputs'], 'pulse', round(r['native_pulse_coherent_fraction'] * 100, 3),
                  'joint', round(r['stable_native_map_fraction'] * 100, 3), 'unneeded', r['unnecessary_native_changes'], flush=True)
    if not passed:
        raise RuntimeError('Frozen validation execution audit failed')


if __name__ == '__main__':
    main()
