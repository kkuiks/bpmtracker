from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from .native_metrics import score as native_score
from experiments.continuous_beat_map_v1.map import validate,as_legacy_prediction
from experiments.multiple_rhythm_continuity_v1.metrics import score as quarter_score
from experiments.variable_clock_composition_v1.evaluate import score as canonical_score
from .common import PARENT,METHODS,POLICIES,read,write,guard,digest,stamp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--partial',action='store_true')
    args=parser.parse_args();run=args.run;guard(run)
    index=read(run/'evaluation-index.json')['rows'];rows=[];contracts=[];pairs=[]
    methods=read(run/'protocol.json').get('selected_methods',list(METHODS))
    for item in index:
        ident=item['id'];ref=read(item['reference_path'])
        for method in methods:
            primary=None
            for policy in POLICIES:
                path=run/'predictions'/method/policy/(ident+'.json')
                if not path.exists():
                    if args.partial:continue
                    raise RuntimeError('Missing prediction '+str(path))
                prediction=read(path);legacy=as_legacy_prediction(prediction)
                canonical=canonical_score(legacy,item,ref);quarters=quarter_score(legacy,ref)
                rows.append({**item,'method':method,'policy':policy,**native_score(prediction,ref),
                    'comparable_quarter_pulse_stable_fraction':quarters['stable_valid_fraction'],
                    'canonical_strict_successful_transitions':canonical['successful_transitions'],
                    'canonical_strict_eligible_transitions':canonical['eligible_transitions'],
                    'canonical_transition_details':canonical['transitions']})
                contracts.append({'id':ident,'method':method,'policy':policy,**validate(prediction)})
                if policy=='proxy100':primary=prediction.copy();primary.pop('policy')
            if primary is not None:
                for policy in ['proxy97','proxy103']:
                    path=run/'predictions'/method/policy/(ident+'.json')
                    if not path.exists():continue
                    other=read(path);other.pop('policy')
                    same=read(run/'encoded-units'/policy/(ident+'.json'))==read(run/'encoded-units/proxy100'/(ident+'.json'))
                    pairs.append({'id':ident,'method':method,'policy':policy,'same_unit':same,'identical_prediction':other==primary})
    common={r['id'] for r in read(PARENT/'historical-fixed-native-comparison.json')['rows']}
    summary=[]
    for method in methods:
        for policy in POLICIES:
            for group in ['all32','fixed13','fixed12_excluding_Red_Miso','fixed17','variable10','meter5']:
                selected=[r for r in rows if r['method']==method and r['policy']==policy and not r['model_seeded_reference_diagnostic_only'] and
                    (group=='all32' or group=='fixed13' and r['id'] in common or group=='fixed12_excluding_Red_Miso' and r['id'] in common and r['id']!='e005' or
                     group=='fixed17' and r['role']=='fixed_control' or group=='variable10' and r['role']=='variable' or group=='meter5' and r['role']=='meter_control')]
                if not selected:continue
                fields=['native_pulse_coherent_fraction','stable_native_map_fraction','bar_period_and_phase_fraction','native_coverage_fraction','comparable_quarter_pulse_stable_fraction']
                totals=['unnecessary_native_changes','unsupported_native_changes','native_tempo_changes','native_meter_changes','native_successful_boundaries','native_eligible_boundaries','canonical_strict_successful_transitions','canonical_strict_eligible_transitions']
                summary.append({'method':method,'policy':policy,'group':group,'inputs':len(selected),
                     **{f:float(np.mean([r[f] for r in selected])) for f in fields},**{f:sum(r[f] for r in selected) for f in totals}})
    hashes=dict(read(run/'input-freeze.json')['files'])
    for p in (run/'source-before-tap-freeze').glob('*.json'):hashes.update(read(p)['files'])
    changed=[p for p,sha in hashes.items() if digest(p)!=sha]
    audits=[read(p) for p in (run/'worker-audit').glob('*.json')];forbidden=sum(len(a['forbidden_reads']) for a in audits)
    source_ids={ident for a in audits if a.get('actual_read_hook') for ident in a['ids']}
    missing_source_audits=sorted({r['id'] for r in rows}-source_ids)
    expected=len(index)*len(methods)*len(POLICIES)
    passed=not changed and not forbidden and not missing_source_audits and (args.partial or len(rows)==expected) and all(c['legal'] and c['continuous_source_coverage'] for c in contracts) and all(not p['same_unit'] or p['identical_prediction'] for p in pairs)
    write(run/'metrics.json',{'rows':rows,'summary':summary,'parent_baseline':str(PARENT/'metrics.json'),'partial':args.partial})
    baseline=[]
    for item in index:
        ref=read(item['reference_path'])
        for method in ['C0_CONSTANT_MAP','C1_CONTINUOUS_MAP']:
            pred=read(PARENT/'predictions'/method/'proxy100'/(item['id']+'.json'))
            baseline.append({**item,'method':method,'policy':'proxy100',**native_score(pred,ref)})
    write(run/'baseline-native-rescored.json',{'rows':baseline,'same_equivalence_aware_event_rule':True,
        'literal_kind_scores_also_retained':True,'source_predictions_unchanged':True})
    write(run/'audit.json',{'at_utc':stamp(),'all_pass':passed,'maps':len(contracts),'map_contracts':contracts,'same_unit_pairs':pairs,
                          'changed_inputs':changed,'source_forbidden_reads':forbidden,'source_worker_audits':len(audits),
                          'expected_maps':expected,'complete_selected_scope':len(rows)==expected,
                          'missing_source_read_audits':missing_source_audits,
                          'native_windows_audible_playback_tested':False})
    for s in summary:
        if s['policy']=='proxy100':print(s,flush=True)
    if not passed:raise RuntimeError('Beat-event map audit failed')
    print('EVALUATED',len(rows),'AUDIT',passed,flush=True)

if __name__=='__main__':main()
