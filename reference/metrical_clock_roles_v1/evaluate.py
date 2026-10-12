"""Separate nominal unit, click events, spurious rates and boundary timing."""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment
from experiments.variable_clock_composition_v1.evaluate import score as old_score
from .common import CONFIG,CRITERIA,FOCUS,read,write,guard

def score(pred,row,ref):
    result=old_score(pred,row,ref)
    rates={s['quarter_bpm'] for s in ref['segments']}
    bad=[e for e in pred['accepted'] if e['bpm'] not in rates]
    result['unmatched_nominal_rate_seconds']=sum(e['end']-e['start'] for e in bad)
    result['unmatched_nominal_rate_regions']=bad
    changes=[{'time':b['start'],'left_bpm':a['bpm'],'right_bpm':b['bpm']}
             for a,b in zip(pred['accepted'],pred['accepted'][1:]) if a['bpm']!=b['bpm']]
    truth=ref['transitions'];pairs=[]
    if changes and truth:
        costs=np.full((len(changes),len(truth)),1e6)
        for i,e in enumerate(changes):
            for j,t in enumerate(truth):
                if e['left_bpm']==t['left_bpm'] and e['right_bpm']==t['right_bpm']:
                    costs[i,j]=abs(e['time']-t['time'])
        ri,ci=linear_sum_assignment(costs)
        for i,j in zip(ri,ci):
            if costs[i,j]>=1e6:continue
            pairs.append({'prediction_index':int(i),'reference_index':int(j),
                          'reference_time':truth[j]['time'],'detected_time':changes[i]['time'],
                          'error_seconds':changes[i]['time']-truth[j]['time'],
                          'left_bpm':truth[j]['left_bpm'],'right_bpm':truth[j]['right_bpm']})
    result['pair_matched_boundaries']=pairs
    result['boundaries_within']={str(t):sum(abs(e['error_seconds'])<=t for e in pairs)
                                 for t in CRITERIA['boundary_tolerances_seconds']}
    result['unwanted_changes_4s']=len(changes)-result['boundaries_within']['4.0']
    result['all_transition_count']=len(truth)
    result['octave_error_fraction']=result['half_rate_fraction']+result['double_rate_fraction']
    return result

def focus_gate(rows):
    primary={r['id']:r for r in rows if r['method']=='R2_ROLES_BARS' and r['policy']=='proxy100'}
    baseline={r['id']:r for r in rows if r['method']=='BASELINE_M3' and r['policy']=='proxy100'}
    decisions=[]
    for ident in FOCUS:
        r,b=primary[ident],baseline[ident];gain=r['correct_clock_fraction']-b['correct_clock_fraction']
        f1delta=r['quarter_f1_70']['f1']-b['quarter_f1_70']['f1']
        if ident=='r002':
            good=(r['correct_clock_fraction']>=CRITERIA['focus_underoath_correct_min'] and
                  r['quarter_f1_70']['f1']>=CRITERIA['focus_underoath_f1_min'] and
                  r['unmatched_nominal_rate_seconds']<CRITERIA['focus_underoath_unmatched_rate_seconds_max'] and
                  len(r['pair_matched_boundaries'])==r['all_transition_count'] and
                  all(abs(e['error_seconds'])<=CRITERIA['focus_underoath_boundary_tolerance_seconds'] for e in r['pair_matched_boundaries']))
        else:good=gain>=CRITERIA['focus_octave_correct_gain_min'] and f1delta>=-CRITERIA['focus_quarter_f1_max_loss']
        decisions.append({'id':ident,'title':r['title'],'improved':bool(good),
                          'correct_clock_gain':gain,'quarter_f1_delta':f1delta,
                          'correct_clock_fraction':r['correct_clock_fraction'],
                          'unmatched_rate_seconds':r['unmatched_nominal_rate_seconds'],
                          'boundaries':r['pair_matched_boundaries']})
    proceed=sum(d['improved'] for d in decisions)>=CRITERIA['focus_cases_improved_required'] and all(d['quarter_f1_delta']>=-CRITERIA['focus_quarter_f1_max_loss'] for d in decisions)
    return {'rows':decisions,'proceed_to_broad':bool(proceed),'criteria_frozen_before_predictions':True,
            'applies_to_primary_only_no_best_arm_substitution':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['focus','broad'],required=True);a=p.parse_args();run=a.run;guard(run)
    index={r['id']:r for r in read(run/'evaluation-index.json')['rows']};rows=[]
    for path in sorted((run/'predictions').glob('*/*/*.json')):
        ident=path.stem
        if a.stage=='focus' and ident not in FOCUS:continue
        method,policy=path.parts[-3:-1];row=index[ident];ref=read(run/'references'/f'{ident}.json')
        rows.append({**{k:row[k] for k in ['id','title','role','original_id','partition']},
                     'method':method,'policy':policy,**score(read(path),row,ref)})
    ids=set(r['id'] for r in rows)
    for ident in sorted(ids):
        row=index[ident];ref=read(run/'references'/f'{ident}.json')
        for policy in ['none','proxy100']:
            rows.append({**{k:row[k] for k in ['id','title','role','original_id','partition']},
                         'method':'BASELINE_M3','policy':policy,
                         **score(read(run/'baseline'/policy/f'{ident}.json'),row,ref)})
    groups=defaultdict(list)
    for r in rows:groups[(r['method'],r['policy'],r['role'])].append(r)
    summary=[]
    for (method,policy,role),rs in sorted(groups.items()):
        summary.append({'method':method,'policy':policy,'role':role,'inputs':len(rs),
            'correct_clock_macro':float(np.mean([r['correct_clock_fraction'] for r in rs])),
            'correct_rate_macro':float(np.mean([r['correct_rate_fraction'] for r in rs])),
            'wrong_clock_macro':float(np.mean([r['wrong_clock_fraction'] for r in rs])),
            'unknown_macro':float(np.mean([r['unknown_fraction'] for r in rs])),
            'octave_error_macro':float(np.mean([r['octave_error_fraction'] for r in rs])),
            'quarter_f1_macro':float(np.mean([r['quarter_f1_70']['f1'] for r in rs])),
            'strict_successful_transitions':sum(r['successful_transitions'] for r in rs),
            'strict_eligible_transitions':sum(r['eligible_transitions'] for r in rs),
            'all_transitions':sum(r['all_transition_count'] for r in rs),
            'boundaries_within':{str(t):sum(r['boundaries_within'][str(t)] for r in rs) for t in CRITERIA['boundary_tolerances_seconds']},
            'unwanted_changes_4s':sum(r['unwanted_changes_4s'] for r in rs),
            'unmatched_rate_seconds':sum(r['unmatched_nominal_rate_seconds'] for r in rs)})
    write(run/f'{a.stage}-metrics.json',{'rows':rows,'summary':summary})
    if a.stage=='focus':
        gate=focus_gate(rows);write(run/'focus-decision.json',gate);print('FOCUS',gate,flush=True)
    else:
        primary=[r for r in rows if r['method']=='R2_ROLES_BARS' and r['policy']=='proxy100' and r['role']=='variable']
        baseline=[r for r in rows if r['method']=='BASELINE_M3' and r['policy']=='proxy100' and r['role']=='variable']
        control=[r for r in rows if r['method']=='R2_ROLES_BARS' and r['policy']=='proxy100' and r['role'] in ['fixed_control','meter_control']]
        oldcontrol=[r for r in rows if r['method']=='BASELINE_M3' and r['policy']=='proxy100' and r['role'] in ['fixed_control','meter_control']]
        def avg(rs,key):return float(np.mean([r[key] for r in rs]))
        d={'correct_clock_gain':avg(primary,'correct_clock_fraction')-avg(baseline,'correct_clock_fraction'),
           'octave_error_reduction':avg(baseline,'octave_error_fraction')-avg(primary,'octave_error_fraction'),
           'control_wrong_increase':avg(control,'wrong_clock_fraction')-avg(oldcontrol,'wrong_clock_fraction'),
           'variable_songs_correct_85':[r['id'] for r in primary if r['correct_clock_fraction']>=.85],
           'criteria':CRITERIA,'not_product_acceptance':True}
        d['direction_criteria_met']=d['correct_clock_gain']>=CRITERIA['broad_correct_gain_min'] and d['octave_error_reduction']>=CRITERIA['broad_octave_error_reduction_min'] and d['control_wrong_increase']<=CRITERIA['broad_control_wrong_increase_max'] and len(d['variable_songs_correct_85'])>=CRITERIA['broad_songs_correct_85_required']
        write(run/'broad-decision.json',d);print('BROAD',d,flush=True)
    print('SCORED',len(rows),flush=True)

if __name__=='__main__':main()
