"""Identical native evaluation, explicit parent deltas and inference audit."""
import argparse
from pathlib import Path
import numpy as np
from .common import read, write, digest, guard, stamp, PARENT, POLICIES
from experiments.beat_event_map_v1.native_metrics import score as native_score
from experiments.continuous_beat_map_v1.map import validate, as_legacy_prediction
from experiments.variable_clock_composition_v1.evaluate import score as canonical_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run
    guard(run)
    index = read(run / 'evaluation-index.json')['rows']
    methods = read(run / 'protocol.json')['selected_methods']
    rows, contracts, pairs = [], [], []
    for item in index:
        ident = item['id']
        ref = read(item['reference_path'])
        for method in methods:
            outputs = {}
            for policy in POLICIES:
                prediction = read(run / 'predictions' / method / policy / (ident + '.json'))
                canonical = canonical_score(as_legacy_prediction(prediction), item, ref)
                rows.append({**item, 'method': method, 'policy': policy,
                    **native_score(prediction, ref),
                    'canonical_strict_successful_transitions': canonical['successful_transitions'],
                    'canonical_strict_eligible_transitions': canonical['eligible_transitions']})
                contracts.append({'id': ident, 'method': method, 'policy': policy, **validate(prediction)})
                prediction.pop('policy')
                outputs[policy] = prediction
            for policy in ('proxy97', 'proxy103'):
                same = read(run / 'encoded-units' / policy / (ident + '.json')) == read(
                    run / 'encoded-units/proxy100' / (ident + '.json'))
                pairs.append({'id': ident, 'method': method, 'policy': policy,
                              'same_unit': same, 'identical_prediction': outputs[policy] == outputs['proxy100']})
    baseline = [r for r in read(PARENT / 'metrics.json')['rows']
                if r['policy'] == 'proxy100' and r['method'] == 'E3_SAME_UNIT_GATE'
                and r['id'] in {x['id'] for x in index}]
    # The original common cohort authority is the preceding fixed comparison.
    older = Path(read(PARENT / 'metrics.json')['parent_baseline']).parent
    fixed = {r['id'] for r in read(older / 'historical-fixed-native-comparison.json')['rows']}
    summary = []
    fields = ['native_pulse_coherent_fraction', 'stable_native_map_fraction',
              'bar_period_and_phase_fraction', 'native_coverage_fraction']
    counts = ['unnecessary_native_changes', 'unsupported_native_changes',
              'native_tempo_changes', 'native_meter_changes',
              'canonical_strict_successful_transitions', 'canonical_strict_eligible_transitions']
    for method in ['E3_SAME_UNIT_GATE'] + methods:
        for group in ('all32', 'fixed12', 'fixed16_excluding_Red_Miso', 'fixed17', 'variable10', 'meter5'):
            selected = [r for r in baseline + rows if r['method'] == method
                        and r['policy'] == 'proxy100' and not r['model_seeded_reference_diagnostic_only']
                        and (group == 'all32'
                             or group == 'fixed12' and r['id'] in fixed and r['id'] != 'e005'
                             or group == 'fixed16_excluding_Red_Miso' and r['role'] == 'fixed_control' and r['id'] != 'e005'
                             or group == 'fixed17' and r['role'] == 'fixed_control'
                             or group == 'variable10' and r['role'] == 'variable'
                             or group == 'meter5' and r['role'] == 'meter_control')]
            if not selected:
                continue
            summary.append({'method': method, 'group': group, 'inputs': len(selected),
                **{k: float(np.mean([r[k] for r in selected])) for k in fields},
                **{k: sum(r[k] for r in selected) for k in counts}})
    old = {r['id']: r for r in baseline}
    deltas = [{**{k: r[k] for k in ('id', 'title', 'role', 'method')},
               **{k: {'old': old[r['id']][k], 'new': r[k], 'delta': r[k] - old[r['id']][k]}
                  for k in fields + ['unnecessary_native_changes', 'unsupported_native_changes']}}
              for r in rows if r['policy'] == 'proxy100']
    hashes = read(run / 'input-freeze.json')['files']
    changed = [path for path, sha in hashes.items() if digest(path) != sha]
    audits = [read(p) for p in (run / 'worker-audit').glob('*.json')]
    forbidden = [path for a in audits for path in a['forbidden_reads']]
    read_ids = {ident for a in audits if a['actual_read_hook'] for ident in a['ids']}
    missing = {r['id'] for r in index} - read_ids
    passed = (not changed and not forbidden and not missing
              and all(r['legal'] and r['continuous_source_coverage'] for r in contracts)
              and all(not r['same_unit'] or r['identical_prediction'] for r in pairs))
    write(run / 'metrics.json', {'rows': rows, 'summary': summary, 'parent': str(PARENT)})
    write(run / 'analysis.json', {'per_song_deltas': deltas,
          'no_method_selected_by_song_or_reference_role': True})
    write(run / 'audit.json', {'at_utc': stamp(), 'all_pass': passed,
          'maps': len(contracts), 'map_contracts': contracts, 'same_unit_pairs': pairs,
          'changed_inputs': changed, 'source_forbidden_reads': forbidden,
          'missing_source_worker_audits': sorted(missing), 'source_worker_audits': len(audits),
          'native_windows_audible_playback_tested': False})
    for r in summary:
        print(r['method'], r['group'], r['inputs'],
              round(r['native_pulse_coherent_fraction'] * 100, 3),
              round(r['stable_native_map_fraction'] * 100, 3),
              r['unnecessary_native_changes'], r['unsupported_native_changes'], flush=True)
    if not passed:
        raise RuntimeError('Stability inference contract audit failed')


if __name__ == '__main__':
    main()
