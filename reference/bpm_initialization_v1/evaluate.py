"""Score frozen outputs only after source workers and isolation audit finish."""
import argparse
import csv
from pathlib import Path

import numpy as np
from experiments.bpm_continuity_v1.evaluate import arrays, score, availability, aggregate, nearest
from .common import METHODS, POLICIES, read, write, object_hash, guard


def evaluate(run):
    guard(run)
    if (run / 'metrics.json').exists():
        raise FileExistsError('No silent metric overwrite')
    if not read(run / 'source-isolation-audit.json')['passed']:
        raise RuntimeError('Source isolation audit did not pass')
    manifest = read(run / 'evaluation-manifest.json')['samples']; rows = []; source_diagnostics = []
    comparisons = []; per_song = []
    for row in manifest:
        ident = row['id']; ref = read(row['reference_path']); predictions = {}; masks = {}; scores = {}
        baseline_path = run / 'predictions/I0_LOCAL6/proxy_unit_zero' / (ident + '.json')
        t, support, truth, _, _, _ = arrays(read(baseline_path), ref, row['duration_seconds'])
        bank_availability = availability(row, ref, t, support, truth, run)
        for method in METHODS:
            for policy in POLICIES:
                pred = read(run / 'predictions' / method / policy / (ident + '.json'))
                boot = read(run / 'bootstrap' / method / policy / (ident + '.json'))
                diagnostic = read(run / 'seed-diagnostics' / method / policy / (ident + '.json'))
                result = score(pred, row, ref, run, bank_availability)
                _, _, _, _, _, labels = arrays(pred, ref, row['duration_seconds'])
                seed = boot['seed']; seed_time = seed['time'] if seed else None
                before = support & (t < seed_time) if seed else np.zeros(len(t), dtype=bool)
                after = support & (t >= seed_time) if seed else np.zeros(len(t), dtype=bool)
                phase_errors = []
                if seed:
                    clock = seed['clock']; period = 60. / clock['bpm']
                    q = clock['phase'] + np.arange(np.ceil((seed_time - clock['phase']) / period),
                                                  np.ceil((seed_time + 4. - clock['phase']) / period)) * period
                    q = q[(q >= ref['support'][0][0]) & (q < ref['support'][-1][1])]
                    phase_errors = nearest(q, np.array(ref['quarters'])).tolist()
                result['seed'] = {'status': boot['status'], 'time': seed_time,
                                  'bpm': seed['clock']['bpm'] if seed else None,
                                  'phase': seed['clock']['phase'] if seed else None,
                                  'exact_nominal_rate': abs(seed['clock']['bpm'] - ref['initial_bpm']) <= 1e-8 if seed else False,
                                  'first_4s_projected_phase_median_ms': float(np.median(phase_errors) * 1000) if phase_errors else None,
                                  'reported_group_margin': seed['margin'] if seed else None}
                result['support_loss'] = {'waiting_seconds': float(before.sum() * .02),
                                          'waiting_fraction': float(before.sum() / support.sum()),
                                          'no_seed_seconds': result['reference_seconds'] if seed is None else 0.,
                                          'post_seed_reference_seconds': float(after.sum() * .02),
                                          'post_seed_unknown_seconds': float((after & labels['unknown']).sum() * .02),
                                          'post_seed_wrong_rate_seconds': float((after & labels['wrong_rate']).sum() * .02),
                                          'post_seed_correct_fraction': float((after & labels['correct_clock_70ms']).sum() / after.sum()) if after.any() else None}
                record = dict(id=ident, title=row['title'], role='fixed', method=method, policy=policy, score=result)
                rows.append(record)
                if policy == 'proxy_unit_zero':
                    predictions[method] = pred; masks[method] = labels; scores[method] = result
                    source_diagnostics.append(dict(id=ident, method=method, truth_initial_bpm=ref['initial_bpm'],
                                                   seed_diagnostic=diagnostic, whole_rate_choice=boot.get('whole_rate_choice')))
        for name, arm, policy in [('STATELESS_PROXY', 'C1_STATELESS', 'proxy_unit_zero'),
                                  ('EXACT_RATE_HOLD', 'C_HOLD', 'oracle_start')]:
            pred = read(run / 'baseline-comparison/predictions' / arm / policy / (ident + '.json'))
            result = score(pred, row, ref, run, bank_availability)
            comparisons.append(dict(id=ident, title=row['title'], role='fixed', method=name, policy=policy, score=result))
        baseline = scores[METHODS[0]]
        per_song.append({'id': ident, 'title': row['title'], 'nominal_bpm': ref['initial_bpm'],
                         'availability': bank_availability, 'methods': {m: scores[m] for m in METHODS}})
        for method in METHODS[1:]:
            gain = support & masks[method]['correct_clock_70ms'] & ~masks[METHODS[0]]['correct_clock_70ms']
            lost = support & ~masks[method]['correct_clock_70ms'] & masks[METHODS[0]]['correct_clock_70ms']
            source_diagnostics.append({'id': ident, 'method': method, 'difference_vs_I0': {
                'correct_gain_seconds': float(gain.sum() * .02), 'correct_loss_seconds': float(lost.sum() * .02),
                'correct_delta_pp': (scores[method]['fractions']['correct_clock_70ms'] - baseline['fractions']['correct_clock_70ms']) * 100,
                'quarter_f1_delta_pp': (scores[method]['quarter_events']['70']['f1'] - baseline['quarter_events']['70']['f1']) * 100,
                'seed_delay_delta_seconds': scores[method]['seed']['time'] - baseline['seed']['time']
                                           if scores[method]['seed']['time'] is not None and baseline['seed']['time'] is not None else None}})
    aggregates = {method + '/' + policy: aggregate([r for r in rows if r['method'] == method and r['policy'] == policy])
                  for method in METHODS for policy in POLICIES}
    comparison_aggregates = {name: aggregate([r for r in comparisons if r['method'] == name])
                            for name in ('STATELESS_PROXY', 'EXACT_RATE_HOLD')}
    f1_threshold = comparison_aggregates['STATELESS_PROXY']['macro']['quarter_f1_70ms']
    protocol = read(run / 'protocol.json'); limits = protocol['gates']; decisions = {}
    for method in METHODS:
        chosen = [r for r in rows if r['method'] == method and r['policy'] == 'proxy_unit_zero']
        macro = aggregates[method + '/proxy_unit_zero']['macro']
        drops = {r['id']: r['score']['fractions']['correct_clock_70ms'] -
                 next(s for s in per_song if s['id'] == r['id'])['methods'][METHODS[0]]['fractions']['correct_clock_70ms'] for r in chosen}
        checks = {'macro_clock_at_least_80pct': macro['correct_clock_70ms'] >= limits['macro_clock_correct_min'] - 1e-12,
                  'macro_actual_quarter_F1_at_least_stateless': macro['quarter_f1_70ms'] >= f1_threshold - 1e-12,
                  'each_song_drop_at_most_5pp_vs_current_hold': all(value >= -limits['each_song_clock_drop_max_vs_I0'] - 1e-12 for value in drops.values())}
        times = [r['score']['seed']['time'] for r in chosen if r['score']['seed']['time'] is not None]
        decisions[method] = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
                             'correct_deltas_by_song': drops, 'exact_rate_seeds': sum(r['score']['seed']['exact_nominal_rate'] for r in chosen),
                             'no_seed_inputs': sum(r['score']['seed']['status'] == 'NO_SEED' for r in chosen),
                             'median_seed_time_seconds': float(np.median(times)) if times else None,
                             'mean_waiting_support_fraction': float(np.mean([r['score']['support_loss']['waiting_fraction'] for r in chosen])),
                             'passing_seed_time_denominator': len(times), 'f1_threshold_rescored': f1_threshold}
    result = {'rows': rows, 'aggregates': aggregates, 'comparisons': comparisons,
              'comparison_aggregates': comparison_aggregates, 'decisions': decisions,
              'primary_policy': 'proxy_unit_zero', 'fixed_input_denominator': len(manifest),
              'quarter_F1_threshold': f1_threshold, 'actual_human_taps_collected': False,
              'variable_tempo_experiment_run': False}
    write(run / 'metrics.json', result)
    write(run / 'analysis.json', {'per_song': per_song, 'source_diagnostics': source_diagnostics,
                                 'analysis_uses_references_only_after_frozen_predictions': True,
                                 'no_parameters_changed_after_scoring': True,
                                 'repeated_proxy_policies_are_not_independent_replicates': True})
    columns = ['id', 'title', 'method', 'policy', 'correct_clock_70ms', 'wrong_rate', 'wrong_phase_only',
               'unknown', 'ambiguous', 'quarter_f1_70ms', 'seed_bpm', 'seed_time', 'seed_exact_rate',
               'waiting_seconds', 'post_seed_unknown_seconds']
    with (run / 'metrics.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
        for row in rows:
            s = row['score']
            writer.writerow(dict(id=row['id'], title=row['title'], method=row['method'], policy=row['policy'],
                                  **s['fractions'], quarter_f1_70ms=s['quarter_events']['70']['f1'],
                                  seed_bpm=s['seed']['bpm'], seed_time=s['seed']['time'], seed_exact_rate=s['seed']['exact_nominal_rate'],
                                  waiting_seconds=s['support_loss']['waiting_seconds'],
                                  post_seed_unknown_seconds=s['support_loss']['post_seed_unknown_seconds']))
    print('SCORED', len(rows), 'predictions;', len(manifest), 'fixed recordings', flush=True)
    for method in METHODS:
        m = aggregates[method + '/proxy_unit_zero']['macro']
        print(method, decisions[method]['status'], 'correct', round(m['correct_clock_70ms'] * 100, 3),
              'quarter_F1', round(m['quarter_f1_70ms'] * 100, 3), 'NO_SEED', decisions[method]['no_seed_inputs'], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); evaluate(args.run.resolve())


if __name__ == '__main__':
    main()
