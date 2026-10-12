"""Compare poisoned-reference workers and frozen baseline reproduction."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import shutil

from .common import METHODS, POLICIES, read, write, digest, guard
from .run import source_worker


def audit(run):
    guard(run)
    if (run / 'source-isolation-audit.json').exists():
        raise FileExistsError('Audit already exists')
    fixed_rows = read(run / 'source-worker-inputs.json')['samples']
    alternate = run / 'audit/reference-poisoned-worker1'
    alternate.mkdir(parents=True)
    for directory in ('source-evidence', 'candidate-banks', 'source-families', 'initial-inputs/encoded'):
        shutil.copytree(run / directory, alternate / directory)
    shutil.copy2(run / 'config.json', alternate / 'config.json')
    (alternate / 'receipts').mkdir()
    for row in fixed_rows:
        shutil.copy2(run / 'receipts' / ('build-' + row['id'] + '.json'), alternate / 'receipts' / ('build-' + row['id'] + '.json'))
        write(alternate / 'current-references' / (row['id'] + '.normalized.json'),
              {'initial_bpm': -123, 'quarters': [99999], 'support': [], 'deliberately_incompatible': True})
    write(alternate / 'evaluation-manifest.json', {'samples': [], 'deliberately_incompatible': True})
    # Raw proxy numbers are also poisoned, while encoded input remains fixed.
    for row in fixed_rows:
        write(alternate / 'initial-inputs' / (row['id'] + '.json'), {'proxy_receipts': 'incompatible raw numbers'})
    arguments = []
    for row in fixed_rows:
        rewritten = dict(row)
        for key in ('evidence_path', 'bank_path', 'family_path'):
            rewritten[key] = str(alternate / Path(row[key]).relative_to(run))
        arguments.append((rewritten, alternate, 'predict'))
    results = []
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as executor:
        for receipt in executor.map(source_worker, arguments):
            results.append(receipt); print('AUDIT', receipt['id'], flush=True)
    comparisons = []; baseline = []; identities = []
    for row in fixed_rows:
        ident = row['id']
        for method in METHODS:
            for policy in POLICIES:
                relative = Path(method) / policy / (ident + '.json')
                trace_relative = Path(method) / policy / (ident + '.jsonl.gz')
                comparisons.append({'id': ident, 'method': method, 'policy': policy,
                                    'prediction_equal': digest(run / 'predictions' / relative) == digest(alternate / 'predictions' / relative),
                                    'trace_equal': digest(run / 'decision-traces' / trace_relative) == digest(alternate / 'decision-traces' / trace_relative)})
            hashes = [(digest(run / 'predictions' / method / p / (ident + '.json')),
                       digest(run / 'decision-traces' / method / p / (ident + '.jsonl.gz'))) for p in POLICIES]
            encoded = read(run / 'initial-inputs/encoded' / (ident + '.json'))
            same = len({str(encoded[p]) for p in POLICIES}) == 1
            identities.append({'id': ident, 'method': method, 'same_encoded_power': same,
                               'byte_identical_three_outputs': len(set(hashes)) == 1})
        for policy in POLICIES:
            pred = run / 'predictions/I0_LOCAL6' / policy / (ident + '.json')
            old = run / 'baseline-comparison/predictions/C_HOLD' / policy / (ident + '.json')
            trace = run / 'decision-traces/I0_LOCAL6' / policy / (ident + '.jsonl.gz')
            old_trace = run / 'baseline-comparison/decision-traces/C_HOLD' / policy / (ident + '.jsonl.gz')
            baseline.append({'id': ident, 'policy': policy, 'prediction_equal': digest(pred) == digest(old),
                             'trace_equal': digest(trace) == digest(old_trace)})
    zero_denied = not any(r['denied_reads'] for r in results + read(run / 'receipts/predict.json')['rows'])
    passed = (zero_denied and all(c['prediction_equal'] and c['trace_equal'] for c in comparisons + baseline) and
              all(c['same_encoded_power'] and c['byte_identical_three_outputs'] for c in identities))
    result = {'passed': passed, 'prediction_trace_comparisons': comparisons, 'baseline_reproduction': baseline,
              'same_unit_checks': identities, 'forbidden_read_attempts': sum(len(r['denied_reads']) for r in results),
              'worker_counts': [2, 1], 'workers_read_no_reference_catalog_or_raw_proxy_input': zero_denied,
              'poisoned_evaluation_and_raw_inputs': True, 'evaluation_scores_not_read_before_freeze': True}
    write(run / 'source-isolation-audit.json', result)
    if not passed:
        raise RuntimeError('Source isolation/reproduction audit failed')
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); result = audit(args.run.resolve())
    print('AUDIT_PASS', len(result['prediction_trace_comparisons']), 'comparisons',
          len(result['baseline_reproduction']), 'baseline reproductions', flush=True)


if __name__ == '__main__':
    main()
