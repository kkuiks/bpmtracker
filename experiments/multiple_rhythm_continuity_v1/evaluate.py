from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import numpy as np

from experiments.variable_clock_composition_v1.evaluate import score as exact_score
from .common import CONFIG, METHODS, GATES, read, write, guard, stamp
from .metrics import score


def average(rows, key):
    return float(np.mean([row[key] for row in rows])) if rows else None


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); guard(args.run)
    rows, groups = [], defaultdict(list)
    for item in read(args.run / 'evaluation-index.json')['rows']:
        ident = item['id']; reference = read(item['reference_path'])
        for method in METHODS:
            policies = ['none','proxy100'] + (['proxy97','proxy103'] if method == 'F1_FOLD05' else [])
            for policy in policies:
                prediction = read(args.run / 'predictions' / method / policy / f'{ident}.json')
                primary = score(prediction, reference); broad = score(prediction, reference, True)
                canonical = exact_score(prediction, item, reference)
                record = {**{key:item[key] for key in ('id','title','role','partition','model_seeded_reference_diagnostic_only')},
                          'method':method,'policy':policy,**primary,
                          'broad_stable_valid_fraction':broad['stable_valid_fraction'],
                          'broad_frame_permissive_fraction':broad['frame_permissive_fraction'],
                          'broad_unnecessary_changes':broad['unnecessary_changes'],
                          'canonical_correct_clock_fraction':canonical['correct_clock_fraction'],
                          'canonical_correct_rate_fraction':canonical['correct_rate_fraction'],
                          'canonical_quarter_f1':canonical['quarter_f1_70']['f1'],
                          'canonical_strict_successful_transitions':canonical['successful_transitions'],
                          'canonical_strict_eligible_transitions':canonical['eligible_transitions']}
                record['useful_stable_song'] = (record['stable_valid_fraction'] >= GATES['useful_song_stable_fraction_min']
                                                and record['coverage_fraction'] >= GATES['useful_song_coverage_min']
                                                and record['unnecessary_changes'] == 0)
                rows.append(record)
                for group in ['all33',item['partition'],item['role']]:
                    groups[(method,policy,group,False)].append(record)
                    if not item['model_seeded_reference_diagnostic_only']:
                        groups[(method,policy,group,True)].append(record)
    summary = []
    fields = ['stable_valid_fraction','region_coherent_fraction','frame_permissive_fraction','single_song_reading_fraction',
              'coverage_fraction','unnecessary_changes_per_minute','broad_stable_valid_fraction','broad_frame_permissive_fraction',
              'canonical_correct_clock_fraction','canonical_correct_rate_fraction','canonical_quarter_f1']
    for (method,policy,group,exclude_seeded), records in groups.items():
        summary.append({'method':method,'policy':policy,'group':group,'exclude_model_seeded':exclude_seeded,
                        'inputs':len(records),**{key:average(records,key) for key in fields},
                        'unnecessary_changes':sum(row['unnecessary_changes'] for row in records),
                        'raw_rate_changes':sum(row['raw_rate_changes'] for row in records),
                        'raw_phase_adjustments':sum(row['raw_phase_adjustments'] for row in records),
                        'unsupported_changes':sum(row['unsupported_changes'] for row in records),
                        'useful_stable_songs':sum(row['useful_stable_song'] for row in records)})
    def selected(method,group):
        return next(row for row in summary if row['method']==method and row['policy']=='proxy100'
                    and row['group']==group and row['exclude_model_seeded'])
    original_before,original_after = selected('B0_RAW','original21'),selected('F1_FOLD05','original21')
    new_before,new_after = selected('B0_RAW','expanded12'),selected('F1_FOLD05','expanded12')
    variable_before,variable_after = selected('B0_RAW','variable'),selected('F1_FOLD05','variable')
    reduction = ((original_before['unnecessary_changes']-original_after['unnecessary_changes'])/original_before['unnecessary_changes']
                 if original_before['unnecessary_changes'] else None)
    decision = {'at_utc':stamp(),'gates':GATES,
                'original21_stable_gain':original_after['stable_valid_fraction']-original_before['stable_valid_fraction'],
                'original21_unnecessary_change_relative_reduction':reduction,
                'expanded11_stable_gain':new_after['stable_valid_fraction']-new_before['stable_valid_fraction'],
                'variable10_stable_gain':variable_after['stable_valid_fraction']-variable_before['stable_valid_fraction'],
                'variable_real_song_count_not_increased':True,'algorithm_meter_not_predicted':True,
                'alternate_listening_acceptance_not_claimed':True,'new_unseen_generalization_not_claimed':True}
    decision['checks'] = {
        'original21_stable_gain':decision['original21_stable_gain']>=GATES['original21_stable_gain_min'],
        'original21_unnecessary_reduction':reduction is not None and reduction>=GATES['original21_unnecessary_change_reduction_min'],
        'expanded11_nonregression':decision['expanded11_stable_gain']>=-GATES['expanded11_stable_decline_max'],
        'variable10_nonregression':decision['variable10_stable_gain']>=-GATES['variable10_stable_decline_max'],
    }
    decision['component_direction_criteria_met']=all(decision['checks'].values())
    # Descriptive song-paired uncertainty, not an unseen validation claim.
    bootstrap=[]; rng=np.random.default_rng(1403)
    for group in ['original21','expanded12','variable','all33']:
        before=[r for r in rows if r['method']=='B0_RAW' and r['policy']=='proxy100'
                and not r['model_seeded_reference_diagnostic_only'] and (group=='all33' or r.get('partition')==group or r['role']==group)]
        for method in ['B1_VETO05','F1_FOLD05']:
            after={r['id']:r for r in rows if r['method']==method and r['policy']=='proxy100'}
            deltas=np.array([after[r['id']]['stable_valid_fraction']-r['stable_valid_fraction'] for r in before])
            draws=deltas[rng.integers(0,len(deltas),size=(5000,len(deltas)))].mean(axis=1)
            bootstrap.append({'group':group,'method':method,'songs':len(deltas),'mean_delta':float(deltas.mean()),
                              'percentile95':np.quantile(draws,[.025,.975]).tolist(),
                              'known_material_descriptive_not_unseen_certification':True})
    write(args.run/'metrics.json',{'rows':rows,'summary':summary})
    write(args.run/'decision.json',decision)
    write(args.run/'paired-bootstrap.json',{'rows':bootstrap,'seed':1403,'draws':5000,'not_a_pass_criterion':True})
    print('SCORED',len(rows),'component',decision['component_direction_criteria_met'],flush=True)
    print({key:decision[key] for key in ('original21_stable_gain','original21_unnecessary_change_relative_reduction',
                                        'expanded11_stable_gain','variable10_stable_gain')},flush=True)


if __name__ == '__main__':
    main()
