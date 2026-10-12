"""Score serialized maps separately; preserve every song and true transition."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import numpy as np

from experiments.variable_clock_composition_v1.evaluate import score, arrays
from .common import CONFIG, METHODS, GATES, read, write, guard, stamp
from .correct import family


def average(rows, field):
    values = [row[field] for row in rows if row[field] is not None]
    return float(np.mean(values)) if values else None


def transition_contexts(pred, row, ref):
    times, support, truth, rates, error, correct_rate, selected = arrays(pred, ref, row['duration_seconds'])
    correct = correct_rate & (error <= .07)
    output = []
    for transition in ref['transitions']:
        before = support & (times >= max(transition['left_start'], transition['time'] - CONFIG['transition_context_seconds'])) & (times < transition['time'])
        after = support & (times >= transition['time']) & (times < min(transition['right_end'], transition['time'] + CONFIG['transition_context_seconds']))
        region = support & (times >= transition['time']) & (times < transition['right_end'])
        ratio = transition['right_bpm'] / transition['left_bpm']
        output.append({**transition, 'small_true_change': abs(ratio - 1.) <= CONFIG['small_true_change_max_relative'] + 1e-12,
                       'genuine_octave_change': family(transition['right_bpm'], transition['left_bpm'], .05) is not None,
                       'pre_rate_fraction': float(correct_rate[before].mean()) if before.any() else None,
                       'post_rate_fraction': float(correct_rate[after].mean()) if after.any() else None,
                       'pre_clock_fraction': float(correct[before].mean()) if before.any() else None,
                       'post_clock_fraction': float(correct[after].mean()) if after.any() else None,
                       'entire_post_region_rate_fraction': float(correct_rate[region].mean()) if region.any() else None,
                       'entire_post_region_clock_fraction': float(correct[region].mean()) if region.any() else None})
    return output


def change_effects(old, new, row, ref):
    times, support, truth, old_rate, old_error, old_correct_rate, old_selected = arrays(old, ref, row['duration_seconds'])
    _, _, _, new_rate, new_error, new_correct_rate, new_selected = arrays(new, ref, row['duration_seconds'])
    old_correct = old_correct_rate & (old_error <= .07)
    new_correct = new_correct_rate & (new_error <= .07)
    events = []
    for event in new['correction_events']:
        use = support & (times >= event['start']) & (times < event['end'])
        if use.any():
            events.append({**event, 'evaluated_seconds': float(use.sum() * .02),
                           'reference_rates': sorted(set(truth[use].tolist())),
                           'old_correct_rate_fraction': float(old_correct_rate[use].mean()),
                           'new_correct_rate_fraction': float(new_correct_rate[use].mean()),
                           'old_correct_clock_fraction': float(old_correct[use].mean()),
                           'new_correct_clock_fraction': float(new_correct[use].mean())})
    return {'rescued_clock_seconds': float((support & ~old_correct & new_correct).sum() * .02),
            'spoiled_clock_seconds': float((support & old_correct & ~new_correct).sum() * .02),
            'rescued_rate_seconds': float((support & ~old_correct_rate & new_correct_rate).sum() * .02),
            'spoiled_rate_seconds': float((support & old_correct_rate & ~new_correct_rate).sum() * .02),
            'scored_correction_events': events}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    guard(args.run)
    evaluation = read(args.run / 'evaluation-index.json')['rows']
    sources = {row['id']: row for row in read(args.run / 'source-inputs.json')['samples']}
    rows, summaries = [], []
    groups = defaultdict(list)
    availability = []
    for row in evaluation:
        ident = row['id']
        ref = read(row['reference_path'])
        bank = read(sources[ident]['bank_path'])['expanded']
        availability.append({'id': ident, 'title': row['title'], 'segments': [
            {**segment, 'retained_exact_rate_candidates': sum(abs(clock['bpm'] - segment['quarter_bpm']) < 1e-8 for clock in bank)}
            for segment in ref['segments']], 'reference_informed_diagnostic_not_a_prediction': True})
        for method in METHODS:
            policies = ['none', 'proxy100'] + (['proxy97', 'proxy103'] if method == 'F1_FOLD05' else [])
            for policy in policies:
                pred = read(args.run / 'predictions' / method / policy / f'{ident}.json')
                baseline = read(args.run / 'predictions/B0_RAW' / ('none' if policy == 'none' else 'proxy100') / f'{ident}.json')
                result = score(pred, row, ref)
                contexts = transition_contexts(pred, row, ref)
                record = {'id': ident, 'title': row['title'], 'role': row['role'], 'method': method, 'policy': policy,
                          **result, 'alias_error_fraction': result['half_rate_fraction'] + result['double_rate_fraction'],
                          'click_f1': result['quarter_f1_70']['f1'], 'contexts': contexts,
                          'correction_count': len(pred['correction_events']),
                          'fold_count': sum(e['action'] == 'FOLD' for e in pred['correction_events']),
                          'fallback_hold_count': sum(e['action'] == 'HOLD' for e in pred['correction_events']),
                          **change_effects(baseline, pred, row, ref)}
                rows.append(record)
                groups[(method, policy, row['role'])].append(record)
    fields = ['correct_clock_fraction', 'correct_rate_fraction', 'wrong_clock_fraction', 'unknown_fraction',
              'wrong_rate_fraction', 'wrong_phase_only_fraction', 'alias_error_fraction', 'click_f1']
    for (method, policy, role), records in groups.items():
        summaries.append({'method': method, 'policy': policy, 'role': role, 'inputs': len(records),
                          **{field: average(records, field) for field in fields},
                          'correction_count': sum(r['correction_count'] for r in records),
                          'fold_count': sum(r['fold_count'] for r in records),
                          'fallback_hold_count': sum(r['fallback_hold_count'] for r in records),
                          'strict_successful_transitions': sum(r['successful_transitions'] for r in records),
                          'strict_eligible_transitions': sum(r['eligible_transitions'] for r in records),
                          'unwanted_rate_edges': sum(r['false_tempo_changes'] for r in records)})
    primary = [r for r in rows if r['method'] == 'F1_FOLD05' and r['policy'] == 'proxy100']
    baseline = [r for r in rows if r['method'] == 'B0_RAW' and r['policy'] == 'proxy100']
    old_by_id = {r['id']: r for r in baseline}
    variable = [r for r in primary if r['role'] == 'variable']
    old_variable = [old_by_id[r['id']] for r in variable]
    controls = [r for r in primary if r['role'] != 'variable']
    old_controls = [old_by_id[r['id']] for r in controls]
    small = [c for r in variable for c in r['contexts'] if c['small_true_change']]
    old_small = [c for r in old_variable for c in r['contexts'] if c['small_true_change']]
    genuine = [{**c, 'id': r['id'], 'title': r['title']} for r in variable for c in r['contexts'] if c['genuine_octave_change']]
    old_genuine = [{**c, 'id': r['id'], 'title': r['title']} for r in old_variable for c in r['contexts'] if c['genuine_octave_change']]
    alias_old, alias_new = average(old_variable, 'alias_error_fraction'), average(variable, 'alias_error_fraction')
    decision = {'created_at_utc': stamp(), 'gates': GATES,
                'variable_correct_clock_gain': average(variable, 'correct_clock_fraction') - average(old_variable, 'correct_clock_fraction'),
                'variable_alias_error_relative_reduction': (alias_old - alias_new) / alias_old if alias_old else None,
                'variable_click_f1_gain': average(variable, 'click_f1') - average(old_variable, 'click_f1'),
                'control_correct_clock_gain': average(controls, 'correct_clock_fraction') - average(old_controls, 'correct_clock_fraction'),
                'small_change_post_rate_gain': average(small, 'post_rate_fraction') - average(old_small, 'post_rate_fraction') if small else None,
                'small_true_change_count': len(small), 'genuine_octave_changes': genuine, 'baseline_genuine_octave_changes': old_genuine,
                'individual_variable_deltas': {r['id']: r['correct_clock_fraction'] - old_by_id[r['id']]['correct_clock_fraction'] for r in variable},
                'unseen_song_generalization': False, 'complete_selector_or_boundary_solution': False}
    checks = {
        'correct_clock_gain': decision['variable_correct_clock_gain'] >= GATES['variable_correct_clock_gain_min'],
        'alias_error_reduction': decision['variable_alias_error_relative_reduction'] is not None and decision['variable_alias_error_relative_reduction'] >= GATES['variable_alias_error_relative_reduction_min'],
        'click_f1_nonregression': decision['variable_click_f1_gain'] >= -GATES['variable_click_f1_decline_max'],
        'controls_nonregression': decision['control_correct_clock_gain'] >= -GATES['control_correct_clock_decline_max'],
        'small_change_rate_nonregression': decision['small_change_post_rate_gain'] is not None and decision['small_change_post_rate_gain'] >= -GATES['small_change_post_rate_decline_max'],
    }
    decision['component_checks'] = checks
    decision['component_direction_criteria_met'] = all(checks.values())
    decision['all_song_loss_checks'] = {
        'individual_variable_nonregression': min(decision['individual_variable_deltas'].values()) >= -GATES['individual_variable_decline_max'],
        'genuine_octave_nonregression': bool(genuine) and all(
            new['entire_post_region_clock_fraction'] >= old['entire_post_region_clock_fraction'] - GATES['genuine_octave_post_decline_max']
            for new, old in zip(genuine, old_genuine)),
    }
    decision['all_song_loss_checks_met'] = all(decision['all_song_loss_checks'].values())
    diagnostic_group = [r for r in variable if not any(c['genuine_octave_change'] for c in r['contexts'])]
    decision['non_octave_variable_diagnostic'] = {
        'count': len(diagnostic_group), 'not_removed_from_primary_denominator': True,
        'correct_clock_before': average([old_by_id[r['id']] for r in diagnostic_group], 'correct_clock_fraction'),
        'correct_clock_after': average(diagnostic_group, 'correct_clock_fraction'),
    }
    write(args.run / 'metrics.json', {'rows': rows, 'summary': summaries})
    write(args.run / 'candidate-rate-availability.json', {'rows': availability})
    write(args.run / 'decision.json', decision)
    print('SCORED', len(rows), 'component', decision['component_direction_criteria_met'],
          'all-song loss checks', decision['all_song_loss_checks_met'], flush=True)
    print({key: decision[key] for key in ('variable_correct_clock_gain', 'variable_alias_error_relative_reduction',
                                         'variable_click_f1_gain', 'small_change_post_rate_gain')}, flush=True)


if __name__ == '__main__':
    main()
