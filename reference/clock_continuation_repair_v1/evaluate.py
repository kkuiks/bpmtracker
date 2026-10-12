from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np

from experiments.multiple_rhythm_continuity_v1.metrics import score
from experiments.variable_clock_composition_v1.evaluate import score as canonical_score
from .common import SOURCE, FIXED_COMPARISON, METHODS, read, write, guard, digest, stamp


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); run = args.run; guard(run)
    index = read(run/'evaluation-index.json')['rows']; item_by_id = {x['id']: x for x in index}
    sources = {x['id']: x for x in read(run/'source-inputs.json')['samples']}
    rows, contracts = [], []
    for item in index:
        ident = item['id']; ref = read(item['reference_path'])
        bank = read(sources[ident]['bank_path'])['expanded']
        for method in METHODS:
            policies = ['none', 'proxy100'] + (['proxy97','proxy103'] if method == 'R1_FOLD_CONTINUE' else [])
            for policy in policies:
                prediction = read(run/'predictions'/method/policy/(ident+'.json'))
                result = score(prediction, ref); broad = score(prediction, ref, True)
                canonical = canonical_score(prediction, item, ref)
                record = {**{k:item[k] for k in ['id','original_id','title','role','partition','model_seeded_reference_diagnostic_only']},
                          'method': method, 'policy': policy, **result,
                          'broad_stable_valid_fraction': broad['stable_valid_fraction'],
                          'canonical_correct_clock_fraction': canonical['correct_clock_fraction'],
                          'canonical_strict_successful_transitions': canonical['successful_transitions'],
                          'canonical_strict_eligible_transitions': canonical['eligible_transitions']}
                record['useful_stable_song'] = result['stable_valid_fraction'] >= .85 and result['coverage_fraction'] >= .95 and result['unnecessary_changes'] == 0
                rows.append(record)
                segments = prediction['accepted']
                continuous = bool(segments) and segments[0]['start'] == 0. and segments[-1]['end'] == sources[ident]['duration_seconds'] and all(a['end'] == b['start'] for a,b in zip(segments, segments[1:]))
                members = all(s['bpm'] == bank[s['clock_index']]['bpm'] and s['phase'] == bank[s['clock_index']]['phase'] for s in segments)
                raw_spans_preserved = True
                if method == 'R0_RAW_CONTINUE':
                    original = read(sources[ident]['raw_paths'][policy])['accepted']
                    raw_spans_preserved = [s for s in segments if not s.get('continuation_gap')] == original
                contracts.append({'id':ident,'method':method,'policy':policy,'complete_source_coverage':continuous,
                                  'source_clock_membership':members,'raw_existing_spans_preserved_when_unfolded':raw_spans_preserved})
        print('SCORED', ident, flush=True)
    baseline = read(SOURCE/'metrics.json')['rows']
    baseline = [{**x, 'original_id': item_by_id[x['id']]['original_id']} for x in baseline if x['method'] == 'F1_FOLD05']
    fixed = read(FIXED_COMPARISON/'metrics.json')['rows']
    fixed = [{**x,'role':'fixed_control','partition':'historical_fixed13','model_seeded_reference_diagnostic_only':False}
             for x in fixed if x['method'] == 'FIXED_ORIGINAL']
    common_ids = {x['id'] for x in read(FIXED_COMPARISON/'selection.json')['primary_common_complete_recordings']}
    all_rows = rows + baseline + fixed
    summary = []
    for method in ['FIXED_ORIGINAL','F1_FOLD05',*METHODS]:
        for policy in ['none','proxy100']:
            for group in ['fixed13','all32','variable10','fixed17','meter5']:
                if method == 'FIXED_ORIGINAL' and group != 'fixed13': continue
                part = [x for x in all_rows if x['method']==method and x['policy']==policy and not x['model_seeded_reference_diagnostic_only']]
                if group=='fixed13': part=[x for x in part if x['id'] in common_ids]
                elif group=='variable10': part=[x for x in part if x['role']=='variable']
                elif group=='fixed17': part=[x for x in part if x['role']=='fixed_control']
                elif group=='meter5': part=[x for x in part if x['role']=='meter_control']
                if not part: continue
                fields=['stable_valid_fraction','frame_permissive_fraction','region_coherent_fraction','coverage_fraction','broad_stable_valid_fraction']
                summary.append({'method':method,'policy':policy,'group':group,'inputs':len(part),
                    **{k:float(np.mean([x[k] for x in part])) for k in fields},
                    'unnecessary_changes':sum(x['unnecessary_changes'] for x in part),
                    'raw_rate_changes':sum(x['raw_rate_changes'] for x in part),
                    'raw_phase_adjustments':sum(x['raw_phase_adjustments'] for x in part),
                    'useful_stable_songs':sum(x['useful_stable_song'] for x in part)})
    pairs=[]
    for item in index:
        expected = read(run/'predictions/R1_FOLD_CONTINUE/proxy100'/(item['id']+'.json'))
        for policy in ['proxy97','proxy103']:
            other=read(run/'predictions/R1_FOLD_CONTINUE'/policy/(item['id']+'.json'))
            for prediction in [expected,other]: prediction.pop('policy',None)
            pairs.append({'id':item['id'],'policy':policy,'identical':other==expected})
    frozen=read(run/'input-freeze.json')['files']
    changed=[path for path,sha in frozen.items() if digest(path)!=sha]
    worker_audits=[read(p) for p in sorted((run/'worker-audit').glob('*.json'))]
    forbidden=sum(len(x['forbidden_reads']) for x in worker_audits)
    passed=(all(all(x[k] for k in ['complete_source_coverage','source_clock_membership','raw_existing_spans_preserved_when_unfolded']) for x in contracts)
            and all(x['identical'] for x in pairs) and not changed and not forbidden)
    write(run/'metrics.json',{'new_rows':rows,'baseline_rows':baseline,'fixed_rows':fixed,'summary':summary})
    write(run/'audit.json',{'at_utc':stamp(),'new_outputs_scored':len(rows),'output_contracts':contracts,
                          'same_unit_pairs':pairs,'input_hash_checks':len(frozen),'changed_inputs':changed,
                          'source_forbidden_reads':forbidden,'worker_audit_count':len(worker_audits),'all_pass':passed})
    def select(method, group):return next(s for s in summary if s['method']==method and s['group']==group and s['policy']=='proxy100')
    old=select('F1_FOLD05','fixed13');new=select('R1_FOLD_CONTINUE','fixed13')
    ov=select('F1_FOLD05','variable10');nv=select('R1_FOLD_CONTINUE','variable10')
    write(run/'decision.json',{'at_utc':stamp(),'continuity_contract_passed':passed,
                             'fixed13_stable_gain':new['stable_valid_fraction']-old['stable_valid_fraction'],
                             'remaining_fixed13_gap_to_fixed_algorithm':1.-new['stable_valid_fraction'],
                             'variable10_stable_delta':nv['stable_valid_fraction']-ov['stable_valid_fraction'],
                             'variable10_unnecessary_changes_before':ov['unnecessary_changes'],
                             'variable10_unnecessary_changes_after':nv['unnecessary_changes'],
                             'no_product_or_general_variable_solution_claim':True})
    print('AUDIT',passed,'NEW_OUTPUTS',len(rows),'SAME_UNIT_PAIRS',len(pairs),flush=True)
    if not passed:raise RuntimeError('Continuation output contract failed')


if __name__ == '__main__': main()
