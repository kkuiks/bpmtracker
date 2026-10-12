"""Independent current-reference evaluation after source workers have stopped."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import math
from pathlib import Path
import numpy as np

from experiments.metronome_benchmark_v1.metrics import event_f1
from experiments.variable_tempo_interval_consensus_v0.core import quantize
from .common import ARMS, POLICIES, CONFIG, read, write, frozen_guard


def inside(times, intervals):
    result=np.zeros(len(times),dtype=bool)
    for a,b in intervals: result|=(times>=a)&(times<b)
    return result


def nearest(value, events):
    if not len(events): return np.full(len(value),np.inf)
    k=np.searchsorted(events,value)
    return np.minimum(abs(value-events[np.clip(k-1,0,len(events)-1)]),abs(value-events[np.clip(k,0,len(events)-1)]))


def emitted(prediction):
    result=[]
    for r in prediction.get('accepted',[]):
        p=r.get('period',60./r['bpm']);phase=r['phase']
        first=math.ceil((r['start']-phase)/p);last=math.ceil((r['end']-phase)/p)
        result.extend((phase+np.arange(first,last)*p).tolist())
    return np.array(sorted(set(result)))


def match_indices(predicted, reference, tolerance=.07):
    i=j=0;pairs=[]
    while i<len(predicted) and j<len(reference):
        delta=predicted[i]-reference[j]
        if delta < -tolerance-1e-12: i+=1
        elif delta > tolerance+1e-12: j+=1
        else: pairs.append((i,j));i+=1;j+=1
    return pairs


def continuous(prediction,start,end):
    cursor=start
    for r in prediction.get('accepted',[]):
        if r['end']<=cursor: continue
        if r['start']>cursor+1e-10: return False
        cursor=max(cursor,r['end'])
        if cursor>=end-1e-10: return True
    return end<=start


def rate_at(prediction,t):
    for r in prediction.get('accepted',[]):
        if r['start']<=t<r['end']: return r['bpm']
    return None


def arrays(prediction,ref,duration):
    t=np.arange(.01,duration,.02);support=inside(t,ref['support']);truth=np.full(len(t),np.nan)
    for s in ref['segments']:
        truth[(t>=s['start_seconds'])&(t<s['end_seconds'])]=quantize(s['quarter_bpm'])
    support&=np.isfinite(truth);quarters=np.array(ref['quarters'])
    selected=np.zeros(len(t),dtype=bool);rate=np.full(len(t),np.nan);error=np.full(len(t),np.inf)
    for r in prediction.get('accepted',[]):
        use=(t>=r['start'])&(t<r['end']);selected|=use;rate[use]=r['bpm']
        p=r.get('period',60./r['bpm']);q=r['phase']+np.rint((t[use]-r['phase'])/p)*p
        error[use]=nearest(q,quarters)
    correct_rate=selected&(abs(rate-truth)<1e-8)
    ambiguous=inside(t,[(r['start'],r['end']) for r in prediction.get('ambiguous',[])])&~selected
    labels={'correct_clock_70ms':correct_rate&(error<=.07),
            'wrong_rate':selected&~correct_rate,'wrong_phase_only':correct_rate&(error>.07),
            'ambiguous':ambiguous,'unknown':~selected&~ambiguous}
    return t,support,truth,rate,error,labels


def availability(row,ref,t,support,truth,run):
    bank=read(run/'candidate-banks'/f"{row['id']}.json")['pools']['final']
    quarters=np.array(ref['quarters']);raw=np.zeros(len(t),dtype=bool);qualified=np.zeros(len(t),dtype=bool)
    with np.load(run/'evidence-tables'/f"{row['id']}.npz") as table:
        order=sorted(bank,key=lambda h:h['key']);index={h['key']:i for i,h in enumerate(order)}
        steps=np.maximum(0,np.minimum(len(table['time'])-1,np.floor(t/CONFIG['step']).astype(int)))
        for h in bank:
            use=support&(abs(truth-h['bpm'])<1e-8)
            if not use.any(): continue
            p=60./h['bpm'];q=h['phase']+np.rint((t[use]-h['phase'])/p)*p
            clock_ok=nearest(q,quarters)<=.07
            j=index[h['key']];indices=steps[use]
            local=(table['G'][indices,j]>=CONFIG['keep_G']-1e-12)&(table['count'][indices,j]>=CONFIG['keep_count'])
            local&=table['freshness'][indices,j]<=CONFIG['fresh_periods']*p+1e-12
            positions=np.flatnonzero(use)
            raw[positions]|=clock_ok;qualified[positions]|=clock_ok&local
    n=int(support.sum())
    return {'raw_bank_correct_clock_fraction':float(raw.sum()/n),'locally_qualified_correct_clock_fraction':float(qualified.sum()/n)}


def failure_events(prediction,ref):
    result=[];accepted=prediction.get('accepted',[])
    if accepted:
        initial=ref['initial_bpm'];ratio=accepted[0]['bpm']/initial
        if abs(ratio-1)>1e-8:
            result.append({'kind':'WRONG_INITIAL_UNIT' if min(abs(ratio-.5),abs(ratio-2))<.02 else 'WRONG_INITIAL_RATE',
                           'time':accepted[0]['start'],'initial_output_bpm':accepted[0]['bpm'],'truth_bpm':initial})
    for previous,current in zip(accepted,accepted[1:]):
        if previous['bpm']==current['bpm'] and previous['phase']==current['phase']: continue
        ratio=current['bpm']/previous['bpm'];gap=current['start']-previous['end']
        if previous['bpm']==current['bpm']: kind='PHASE_REANCHOR'
        elif min(abs(ratio-.5),abs(ratio-2))<=1e-8:
            kind='OCTAVE_RESTART_AFTER_GAP' if gap>1e-10 else 'DIRECT_OCTAVE_FLIP'
        else: kind='NONHARMONIC_BPM_CHANGE'
        # A delayed change matching a true rate pair is scored as adaptation,
        # rather than as a false change merely because it occurs after the boundary.
        genuine=any(tr['time']-.07<=current['start']<tr['end'] and
                    previous['bpm']==tr['left_bpm'] and current['bpm']==tr['right_bpm'] for tr in ref['transitions'])
        result.append({'kind':kind,'time':current['start'],'gap_seconds':gap,'before_bpm':previous['bpm'],
                       'after_bpm':current['bpm'],'false_nonharmonic_change':kind=='NONHARMONIC_BPM_CHANGE' and not genuine})
    return result


def transition_metrics(prediction,ref,run,row,t,support,labels):
    events=emitted(prediction);true=np.array(ref['quarters']);result=[]
    bank_rates={h['bpm'] for h in read(run/'candidate-banks'/f"{row['id']}.json")['pools']['final']}
    for tr in ref['transitions']:
        if not tr['eligible']: continue
        boundary=tr['time'];old=true[true<boundary][-8:]
        old_pred=np.array([x for x in events if len(old) and old[0]-.07<=x<boundary and rate_at(prediction,float(x))==tr['left_bpm']])
        old_pairs=match_indices(old_pred,old)
        old_ok=len(old)==8 and len(old_pairs)==8 and continuous(prediction,float(old_pred[old_pairs[0][0]]),float(old_pred[old_pairs[-1][0]]))
        new=true[(true>=boundary)&(true<tr['end'])]
        new_pred=np.array([x for x in events if boundary-.07<=x<tr['end'] and rate_at(prediction,float(x))==tr['right_bpm']])
        matched=match_indices(new_pred,new);first=None
        for k in range(len(matched)-7):
            group=matched[k:k+8];refs=[j for i,j in group]
            predicted=[float(new_pred[i]) for i,j in group]
            if refs==list(range(refs[0],refs[0]+8)) and continuous(prediction,predicted[0],predicted[-1]):
                first=predicted[0];break
        delay=first-boundary if first is not None else None
        until=boundary if delay is not None and delay<0 else (first if first is not None else tr['end'])
        before_recovery=support&(t>=boundary)&(t<until)
        reason=('NO_SEED' if prediction.get('status')=='NO_SEED' else
                'NEW_RATE_ABSENT_FROM_FINAL_BANK' if tr['right_bpm'] not in bank_rates else
                'OLD_CLOCK_NOT_CORRECT' if not old_ok else
                'POLICY_DID_NOT_RECOVER' if first is None else 'RECOVERED')
        result.append(dict(tr,old_last_8_correct=bool(old_ok),recovered_after=first is not None,
                           successful_transition=bool(old_ok and first is not None),adaptation_delay=delay,
                           new_rate_available=tr['right_bpm'] in bank_rates,failure_or_recovery_reason=reason,
                           anticipatory=delay is not None and delay<0,
                           bootstrap_status=prediction.get('status'),
                           pre_recovery_seconds={key:float((mask&before_recovery).sum()*.02) for key,mask in labels.items()}))
    return result


def score(prediction,row,ref,run,available=None,legacy=None):
    duration=row['duration_seconds'];t,support,truth,rate,error,labels=arrays(prediction,ref,duration)
    n=int(support.sum())
    if not n: raise ValueError('Approved support has empty evaluation denominator')
    seconds={key:float((mask&support).sum()*.02) for key,mask in labels.items()}
    fractions={key:float((mask&support).sum()/n) for key,mask in labels.items()}
    if abs(sum(fractions.values())-1)>1e-10: raise ValueError('Nonexclusive scoring categories')
    selected=np.isfinite(rate);wrong=labels['wrong_rate']&support
    half=wrong&(abs(rate-truth*.5)<1e-8);double=wrong&(abs(rate-truth*2)<1e-8)
    near_octave=wrong&((abs((rate/truth)/.5-1)<=.01)|(abs((rate/truth)/2-1)<=.01))
    events=emitted(prediction);p=events[inside(events,ref['support'])];r=np.array(ref['quarters'])
    pairs=match_indices(p,r);errors=np.array([abs(p[i]-r[j]) for i,j in pairs])
    old_support=np.zeros(len(t),dtype=bool)
    if legacy:
        for episode in legacy.get('episodes',[]):
            use=support&(t>=episode['start'])&(t<episode['end'])&(abs(truth-episode['bpm'])<1e-8)
            period=episode.get('period',60./episode['bpm']);q=episode['phase']+np.rint((t[use]-episode['phase'])/period)*period
            positions=np.flatnonzero(use);old_support[positions]|=nearest(q,r)<=.07
    result={'status':prediction.get('status'),'reference_seconds':n*.02,'support_points':n,
            'fractions':fractions,'seconds':seconds,'half_rate_fraction':float(half.sum()/n),
            'double_rate_fraction':float(double.sum()/n),'other_wrong_rate_fraction':float((wrong&~half&~double).sum()/n),
            'octave_family_within_1_percent_fraction':float(near_octave.sum()/n),
            'correct_clock_20ms':float((labels['correct_clock_70ms']&support&(error<=.02)).sum()/n),
            'correct_clock_30ms':float((labels['correct_clock_70ms']&support&(error<=.03)).sum()/n),
            'rate_within_1_percent':float((selected&support&(abs(rate/truth-1)<=.01)).sum()/n),
            'quarter_events':{str(ms):event_f1(p,r,ms/1000) for ms in [20,30,70]},
            'matched_phase_median_ms':float(np.median(errors)*1000) if len(errors) else None,
            'matched_phase_p95_ms':float(np.quantile(errors,.95)*1000) if len(errors) else None,
            'matched_phase_conditioned_on_70ms_match':True,'unmatched_prediction_count':len(p)-len(pairs),
            'unmatched_reference_count':len(r)-len(pairs),
            'no_grid_extra_clicks':int(inside(events,ref['no_grid']).sum()),
            'outside_support_clicks':int((~inside(events,ref['support'])).sum()),
            'outside_support_output_seconds':float((selected&~support).sum()*.02),
            'wrong_rate_with_correct_old_episode_seconds':float((wrong&old_support).sum()*.02),
            'wrong_rate_without_correct_old_episode_seconds':float((wrong&~old_support).sum()*.02),
            'availability':available,'failure_events':failure_events(prediction,ref)}
    result['transitions']=transition_metrics(prediction,ref,run,row,t,support,labels)
    result['false_nonharmonic_changes']=sum(e.get('false_nonharmonic_change',False) for e in result['failure_events'])
    result['transition_failure_count']=sum(not tr['successful_transition'] for tr in result['transitions'])
    return result


def aggregate(rows):
    n=len(rows);seconds=sum(r['score']['reference_seconds'] for r in rows)
    fields={'correct_clock_70ms':lambda s:s['fractions']['correct_clock_70ms'],
            'wrong_rate':lambda s:s['fractions']['wrong_rate'],'wrong_phase_only':lambda s:s['fractions']['wrong_phase_only'],
            'unknown':lambda s:s['fractions']['unknown'],'ambiguous':lambda s:s['fractions']['ambiguous'],
            'half_double':lambda s:s['half_rate_fraction']+s['double_rate_fraction'],
            'octave_family_within_1_percent':lambda s:s['octave_family_within_1_percent_fraction'],
            'quarter_f1_70ms':lambda s:s['quarter_events']['70']['f1'],
            'rate_within_1_percent':lambda s:s['rate_within_1_percent'],
            'correct_clock_20ms':lambda s:s['correct_clock_20ms'],'correct_clock_30ms':lambda s:s['correct_clock_30ms']}
    return {'inputs':n,'reference_seconds':seconds,
            'macro':{key:sum(fn(r['score']) for r in rows)/n for key,fn in fields.items()} if n else {},
            'micro_time':{key:sum(fn(r['score'])*r['score']['reference_seconds'] for r in rows)/seconds
                          for key,fn in fields.items() if 'f1' not in key} if seconds else {}}


def gates(rows,aggregates,policy):
    chosen={(r['id'],r['arm']):r['score'] for r in rows if r['policy']==policy or
            r['arm']=='C0_LEGACY_A' and r['policy']=='initial_exact'}
    fixed=[r for r in rows if r['arm']=='C1_STATELESS' and r['policy']==policy and r['role']=='fixed']
    ids=[r['id'] for r in fixed]
    a=aggregates[f'C1_STATELESS/{policy}/fixed']['macro'];b=aggregates[f'C2_CONTINUITY/{policy}/fixed']['macro']
    c0=aggregates['C0_LEGACY_A/initial_exact/fixed']['macro']
    tolerance=sum(1/chosen[(ident,'C1_STATELESS')]['support_points'] for ident in ids)/len(ids)
    checks=[]
    def add(name,value,detail): checks.append({'name':name,'status':'N/A' if value is None else 'PASS' if value else 'FAIL','details':detail})
    add('macro_octave_error_reduction_50_percent',None if a['half_double']==0 else b['half_double']<=a['half_double']*.5+tolerance,{'C1':a['half_double'],'C2':b['half_double']})
    for ident in ['src0106','src0095']:
        x,y,z=chosen[(ident,'C1_STATELESS')],chosen[(ident,'C2_CONTINUITY')],chosen[(ident,'C0_LEGACY_A')]
        old=x['half_rate_fraction']+x['double_rate_fraction'];new=y['half_rate_fraction']+y['double_rate_fraction'];eps=1/x['support_points']
        add(ident+'_octave_error_reduction_50_percent',None if old==0 else new<=old*.5+eps,{'C1':old,'C2':new})
        add(ident+'_C0_correct_gain_10pp',y['fractions']['correct_clock_70ms']>=z['fractions']['correct_clock_70ms']+.10-eps,
            {'C0':z['fractions']['correct_clock_70ms'],'C2':y['fractions']['correct_clock_70ms']})
    add('macro_C1_correct_gain_10pp',b['correct_clock_70ms']>=a['correct_clock_70ms']+.10-tolerance,{'C1':a['correct_clock_70ms'],'C2':b['correct_clock_70ms']})
    add('macro_C0_correct_nonregression',b['correct_clock_70ms']>=c0['correct_clock_70ms']-tolerance,{'C0':c0['correct_clock_70ms'],'C2':b['correct_clock_70ms']})
    drops={ident:chosen[(ident,'C2_CONTINUITY')]['fractions']['correct_clock_70ms']-chosen[(ident,'C1_STATELESS')]['fractions']['correct_clock_70ms'] for ident in ids}
    add('each_fixed_correct_drop_at_most_5pp',all(drops[ident]>=-.05-1/chosen[(ident,'C1_STATELESS')]['support_points'] for ident in ids),drops)
    add('macro_wrong_rate_nonincrease',b['wrong_rate']<=a['wrong_rate']+tolerance,{'C1':a['wrong_rate'],'C2':b['wrong_rate']})
    add('macro_wrong_phase_nonincrease',b['wrong_phase_only']<=a['wrong_phase_only']+tolerance,{'C1':a['wrong_phase_only'],'C2':b['wrong_phase_only']})
    add('fixed_no_grid_clicks_nonincrease',all(chosen[(i,'C2_CONTINUITY')]['no_grid_extra_clicks']<=chosen[(i,'C1_STATELESS')]['no_grid_extra_clicks'] for i in ids),None)
    add('actual_quarter_F1_nonregression',b['quarter_f1_70ms']>=a['quarter_f1_70ms']-1e-12,{'C1':a['quarter_f1_70ms'],'C2':b['quarter_f1_70ms']})
    inconclusive=any(c['status']=='N/A' and 'octave_error' in c['name'] for c in checks) or a['correct_clock_70ms']>.90
    fixed_status='FIXED_INCONCLUSIVE' if inconclusive else 'FIXED_PASS' if all(c['status']=='PASS' for c in checks) else 'FIXED_FAILED'
    variables=[r['id'] for r in rows if r['arm']=='C1_STATELESS' and r['policy']==policy and r['role']=='variable']
    variable=[]
    def vadd(name,passed,details):variable.append({'name':name,'status':'PASS' if passed else 'FAIL','details':details})
    recovered=[{'id':i,**tr} for i in variables for tr in chosen[(i,'C2_CONTINUITY')]['transitions'] if tr['successful_transition'] and tr['adaptation_delay']<=8]
    vadd('one_real_transition_before_and_after_8quarters_within_8s',bool(recovered),recovered)
    vadd('recovery_failures_nonincrease',sum(chosen[(i,'C2_CONTINUITY')]['transition_failure_count'] for i in variables)<=sum(chosen[(i,'C1_STATELESS')]['transition_failure_count'] for i in variables),None)
    vadd('false_changes_nonincrease',sum(chosen[(i,'C2_CONTINUITY')]['false_nonharmonic_changes'] for i in variables)<=sum(chosen[(i,'C1_STATELESS')]['false_nonharmonic_changes'] for i in variables),None)
    vadd('each_variable_correct_drop_at_most_5pp',all(chosen[(i,'C2_CONTINUITY')]['fractions']['correct_clock_70ms']>=chosen[(i,'C1_STATELESS')]['fractions']['correct_clock_70ms']-.05-1/chosen[(i,'C1_STATELESS')]['support_points'] for i in variables),None)
    vadd('variable_no_grid_clicks_nonincrease',all(chosen[(i,'C2_CONTINUITY')]['no_grid_extra_clicks']<=chosen[(i,'C1_STATELESS')]['no_grid_extra_clicks'] for i in variables),None)
    variable_status='VARIABLE_CHECK_PASS' if all(c['status']=='PASS' for c in variable) else 'VARIABLE_UNVERIFIED' if not recovered else 'VARIABLE_REGRESSED'
    conclusion=fixed_status
    if fixed_status=='FIXED_PASS':
        conclusion={'VARIABLE_CHECK_PASS':'RESEARCH_GO','VARIABLE_UNVERIFIED':'FIXED_IMPROVED_VARIABLE_UNVERIFIED',
                    'VARIABLE_REGRESSED':'FIXED_IMPROVED_VARIABLE_REGRESSED'}[variable_status]
    return {'policy':policy,'fixed_status':fixed_status,'variable_status':variable_status,'conclusion':conclusion,
            'fixed_checks':checks,'variable_checks':variable,'research_not_product_gate':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve();frozen_guard(run)
    if not read(run/'receipts/predict.json')['completed']: raise RuntimeError('Source prediction stage incomplete')
    rows=[];failure=[]
    for row in read(run/'evaluation-manifest.json')['samples']:
        ref=read(row['reference_path']);dummy={'accepted':[],'ambiguous':[]}
        t,support,truth,*rest=arrays(dummy,ref,row['duration_seconds'])
        avail=availability(row,ref,t,support,truth,run)
        old_path=run/'legacy-predictions/initial_exact'/f"{row['id']}.json"
        legacy=read(old_path) if old_path.exists() else None
        for arm,policies in [('C0_LEGACY_A',('none','initial_unit','initial_exact'))]+[(a,POLICIES) for a in ARMS]:
            for policy in policies:
                path=(run/'legacy-predictions'/policy if arm=='C0_LEGACY_A' else run/'predictions'/arm/policy)/f"{row['id']}.json"
                if not path.exists():
                    failure.append({'id':row['id'],'arm':arm,'policy':policy,'status':'UNAVAILABLE'})
                    continue
                s=score(read(path),row,ref,run,avail,legacy)
                rows.append({'id':row['id'],'title':row['title'],'role':row['role'],'arm':arm,'policy':policy,'score':s})
    grouped=defaultdict(list)
    for r in rows:grouped[f"{r['arm']}/{r['policy']}/{r['role']}"].append(r)
    aggregates={key:aggregate(rs) for key,rs in grouped.items()}
    gate_rows=[gates(rows,aggregates,p) for p in POLICIES]
    write(run/'metrics.json',{'rows':rows,'aggregates':aggregates,'unavailable':failure,
                             'clock_time_metric_includes_grid_compatibility_not_event_count':True,'evaluation_dt':.02})
    write(run/'failure-events.json',{'rows':[{'id':r['id'],'arm':r['arm'],'policy':r['policy'],
                                            'events':r['score']['failure_events'],'transitions':r['score']['transitions']} for r in rows]})
    write(run/'run-result.json',{'conclusion':gate_rows[0]['conclusion'],'gates':gate_rows,
                                'input_status':'PROXY_COMPLETE','actual_human_taps_collected':False,
                                'human_tap_evaluation':'NOT_IN_SCOPE','unavailable':failure,
                                'Opeth_initial_rate_missing_preserved':True})
    with (run/'metrics.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','title','role','arm','policy','status','correct_clock_70ms','wrong_rate','wrong_phase_only','ambiguous','unknown','half_rate','double_rate','quarter_f1_70ms'])
        writer.writeheader()
        for r in rows:
            s=r['score'];writer.writerow({k:r[k] for k in ['id','title','role','arm','policy']}|
                                        {'status':s['status'],**s['fractions'],'half_rate':s['half_rate_fraction'],
                                         'double_rate':s['double_rate_fraction'],'quarter_f1_70ms':s['quarter_events']['70']['f1']})
    print('EVALUATION_COMPLETE',gate_rows[0]['conclusion'],flush=True)


if __name__=='__main__': main()
