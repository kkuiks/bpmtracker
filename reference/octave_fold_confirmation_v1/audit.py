"""Required input preservation, same-unit and correction contract checks."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from .common import read, write, guard, digest, stamp


def semantic(pred):
    result = copy.deepcopy(pred)
    for field in ('method', 'policy', 'correction', 'correction_events'):
        result.pop(field, None)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    guard(args.run)
    unchanged = {name: digest(name) == expected for name, expected in read(args.run / 'input-freeze.json')['files'].items()}
    sources = {row['id']: row for row in read(args.run / 'source-inputs.json')['samples']}
    baseline_checks, contract_checks, unit_checks = [], [], []
    for ident, row in sources.items():
        bank = read(row['bank_path'])['expanded']
        for policy, raw_path in row['raw_predictions'].items():
            raw = read(raw_path)
            baseline = read(args.run / 'predictions/B0_RAW' / policy / f'{ident}.json')
            baseline_checks.append({'id': ident, 'policy': policy, 'identical': semantic(raw) == semantic(baseline)})
        for path in (args.run / 'predictions').glob(f'*/*/{ident}.json'):
            pred = read(path)
            raw = read(row['raw_predictions']['none' if pred['policy'] == 'none' else 'proxy100'])
            edges = [(s['start'], s['end']) for s in pred['accepted']]
            expected = [(s['start'], s['end']) for s in raw['accepted']]
            membership = all(any(abs(clock['bpm'] - s['bpm']) < 1e-8 and abs(clock['phase'] - s['phase']) < 1e-8
                                 for clock in bank) for s in pred['accepted'])
            contract_checks.append({'path': str(path.relative_to(args.run)),
                                    'interval_edges_unchanged': edges == expected,
                                    'every_output_clock_was_in_source_bank': membership,
                                    'output_not_muted_or_dropped': len(pred['accepted']) == len(raw['accepted'])})
        primary = read(args.run / 'predictions/F1_FOLD05/proxy100' / f'{ident}.json')
        for policy in ('proxy97', 'proxy103'):
            unit_checks.append({'id': ident, 'policy': policy,
                                'identical': semantic(primary) == semantic(read(args.run / 'predictions/F1_FOLD05' / policy / f'{ident}.json')) and
                                primary['correction_events'] == read(args.run / 'predictions/F1_FOLD05' / policy / f'{ident}.json')['correction_events']})
    workers = [read(path) for path in (args.run / 'worker-audit').glob('*.json')]
    result = {'at_utc': stamp(), 'input_hash_checks': len(unchanged), 'all_inputs_unchanged': all(unchanged.values()),
              'changed_inputs': [name for name, passed in unchanged.items() if not passed],
              'baseline_checks': baseline_checks, 'correction_contract_checks': contract_checks,
              'same_unit_checks': unit_checks, 'source_worker_forbidden_reads': [value for worker in workers for value in worker['forbidden_reads']],
              'source_worker_covered_ids': sorted({ident for worker in workers for ident in worker['ids']})}
    result['all_required_checks_passed'] = (all(unchanged.values()) and all(r['identical'] for r in baseline_checks + unit_checks)
                                           and all(r['interval_edges_unchanged'] and r['every_output_clock_was_in_source_bank'] and r['output_not_muted_or_dropped'] for r in contract_checks)
                                           and not result['source_worker_forbidden_reads'] and result['source_worker_covered_ids'] == sorted(sources))
    write(args.run / 'audit.json', result)
    if not result['all_required_checks_passed']:
        raise RuntimeError('Required preservation/correction contract check failed')
    print('AUDIT PASS', len(unchanged), 'input hashes;', len(contract_checks), 'outputs;', len(unit_checks), 'same-unit pairs', flush=True)


if __name__ == '__main__':
    main()
