"""Independent scoring after every source prediction is serialized."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import math
from pathlib import Path

import numpy as np

from experiments.metronome_benchmark_v1.metrics import event_f1
from .common import CONFIG,GATES,read,write,guard


def inside(times,intervals):
    mask=np.zeros(len(times),dtype=bool)
    for a,b in intervals:mask|=(times>=a)&(times<b)
    return mask


def nearest(values,events):
    if not len(events):return np.full(len(values),np.inf)
    i=np.searchsorted(events,values)
    return np.minimum(abs(values-events[np.clip(i-1,0,len(events)-1)]),abs(values-events[np.clip(i,0,len(events)-1)]))


def emitted(pred):
    q=[];bpm=[]
    for e in pred['accepted']:
        p=60/e['bpm'];first=math.ceil((e['start']-e['phase'])/p);last=math.ceil((e['end']-e['phase'])/p)
        events=e['phase']+np.arange(first,last)*p
        q.extend(events.tolist());bpm.extend([e['bpm']]*len(events))
    order=np.argsort(q);return np.asarray(q)[order],np.asarray(bpm)[order]


def arrays(pred,ref,duration):
    time=np.arange(.01,duration,.02);support=inside(time,ref['support']);truth=np.full(len(time),np.nan)
    for s in ref['segments']:
        truth[(time>=s['start_seconds'])&(time<s['end_seconds'])]=s['quarter_bpm']
    support &= np.isfinite(truth);rate=np.full(len(time),np.nan);error=np.full(len(time),np.inf)
    quarters=np.array(ref['quarters'])
    for e in pred['accepted']:
        use=(time>=e['start'])&(time<e['end']);rate[use]=e['bpm'];p=60/e['bpm']
        ticks=e['phase']+np.rint((time[use]-e['phase'])/p)*p
        error[use]=nearest(ticks,quarters)
    correct_rate=abs(rate-truth)<1e-8;selected=np.isfinite(rate)
    return time,support,truth,rate,error,correct_rate,selected


def transition_score(pred,ref,events,rates):
    q=np.array(ref['quarters']);result=[];changes=[]
    for a,b in zip(pred['accepted'],pred['accepted'][1:]):
        if a['bpm']!=b['bpm']:
            changes.append({'time':b['start'],'left_bpm':a['bpm'],'right_bpm':b['bpm']})
    for tr in ref['transitions']:
        boundary=tr['time'];old=q[(q>=tr['left_start'])&(q<boundary)][-8:]
        new=q[(q>=boundary)&(q<tr['right_end'])]
        old_pred=events[(rates==tr['left_bpm'])&(events>=tr['left_start'])&(events<boundary+.07)]
        new_pred=events[(rates==tr['right_bpm'])&(events>=boundary-.07)&(events<tr['right_end'])]
        old_ok=nearest(old,old_pred)<=.07;new_ok=nearest(new,new_pred)<=.07
        eligible=len(old)==8 and len(new)>=8
        recovered=None
        for i in range(max(0,len(new)-7)):
            if new[i]-boundary>GATES['transition_maximum_recovery_delay_seconds']:break
            if new_ok[i:i+8].mean()>=GATES['transition_matching_fraction']:
                recovered=float(new[i]);break
        edges=[e for e in changes if e['left_bpm']==tr['left_bpm'] and e['right_bpm']==tr['right_bpm']]
        edge=min(edges,key=lambda e:abs(e['time']-boundary)) if edges else None
        near=edge is not None and abs(edge['time']-boundary)<=GATES['transition_boundary_tolerance_seconds']+1e-9
        old_fraction=float(old_ok.mean()) if len(old) else 0.
        success=eligible and old_fraction>=GATES['transition_matching_fraction'] and recovered is not None and near
        result.append({**tr,'eligible_eight_quarters_each_side':eligible,'old_quarter_recall':old_fraction,
                       'new_quarter_recall':float(new_ok.mean()) if len(new) else 0.,
                       'first_recovered_eight_quarter_group':recovered,
                       'recovery_delay_seconds':recovered-boundary if recovered is not None else None,
                       'detected_boundary_seconds':edge['time'] if edge else None,
                       'boundary_error_seconds':edge['time']-boundary if edge else None,
                       'successful_transition':bool(success)})
    false=[]
    for e in changes:
        genuine=any(e['left_bpm']==t['left_bpm'] and e['right_bpm']==t['right_bpm'] and
                    abs(e['time']-t['time'])<=GATES['transition_boundary_tolerance_seconds'] for t in ref['transitions'])
        if not genuine:false.append(e)
    return result,false


def score(pred,row,ref):
    time,support,truth,rate,error,correct_rate,selected=arrays(pred,ref,row['duration_seconds']);n=int(support.sum())
    if not n:raise ValueError('Empty approved support')
    correct=correct_rate&(error<=.07);wrong=selected&~correct;unknown=~selected
    event,erate=emitted(pred);use=inside(event,ref['support']);p=event[use];r=np.array(ref['quarters'])
    trans,false=transition_score(pred,ref,event,erate)
    segments=[]
    for s in ref['segments']:
        m=support&(time>=s['start_seconds'])&(time<s['end_seconds']);nn=int(m.sum())
        segments.append({**s,'duration':s['end_seconds']-s['start_seconds'],
            'correct_clock_fraction':float((correct&m).sum()/nn) if nn else 0.,
            'correct_rate_fraction':float((correct_rate&m).sum()/nn) if nn else 0.,
            'wrong_clock_fraction':float((wrong&m).sum()/nn) if nn else 0.,
            'unknown_fraction':float((unknown&m).sum()/nn) if nn else 0.})
    half=selected&(abs(rate/truth/.5-1)<=.01);double=selected&(abs(rate/truth/2-1)<=.01)
    weak=inside(time,[[d['start'],d['end']] for d in pred.get('diagnostic',[]) if d['status']=='HELD_WEAK_EVIDENCE'])
    scope=pred.get('initial_unit_scope')
    initial_overrun=0.
    if scope:
        initial_overrun=max(0.,scope['end']-max(scope['start'],ref['segments'][0]['end_seconds']))
    return {'status':pred['status'],'support_seconds':n*.02,
        'correct_clock_fraction':float((correct&support).sum()/n),'correct_rate_fraction':float((correct_rate&support).sum()/n),
        'wrong_clock_fraction':float((wrong&support).sum()/n),'unknown_fraction':float((unknown&support).sum()/n),
        'wrong_rate_fraction':float((selected&~correct_rate&support).sum()/n),
        'wrong_phase_only_fraction':float((correct_rate&(error>.07)&support).sum()/n),
        'half_rate_fraction':float((half&support).sum()/n),'double_rate_fraction':float((double&support).sum()/n),
        'correct_clock_20_fraction':float((correct_rate&(error<=.02)&support).sum()/n),
        'correct_clock_30_fraction':float((correct_rate&(error<=.03)&support).sum()/n),
        'held_weak_fraction':float((weak&support).sum()/n),'held_weak_correct_fraction':float((weak&correct&support).sum()/n),
        'initial_assistance_scope_overrun_seconds':initial_overrun,
        'quarter_f1_20':event_f1(p,r,.02),'quarter_f1_30':event_f1(p,r,.03),'quarter_f1_70':event_f1(p,r,.07),
        'reference_quarters':len(r),'emitted_quarters_in_support':len(p),
        'tempo_changes':sum(a['bpm']!=b['bpm'] for a,b in zip(pred['accepted'],pred['accepted'][1:])),
        'phase_reanchors':sum(a['bpm']==b['bpm'] and a['phase']!=b['phase'] for a,b in zip(pred['accepted'],pred['accepted'][1:])),
        'false_tempo_changes':len(false),'false_change_events':false,'transitions':trans,'segments':segments,
        'successful_transitions':sum(t['successful_transition'] for t in trans),
        'eligible_transitions':sum(t['eligible_eight_quarters_each_side'] for t in trans),
        'all_reference_transitions':len(trans),'long_regions_recovered':sum(s['duration']>=GATES['long_region_min_seconds'] and
             s['correct_clock_fraction']>=GATES['long_region_correct_min'] for s in segments),
        'long_reference_regions':sum(s['duration']>=GATES['long_region_min_seconds'] for s in segments)}


def availability(run,row,ref,bank_name):
    bank=read(run/'banks'/f"{row['id']}.json")[bank_name]
    with np.load(run/'tables'/bank_name/f"{row['id']}.npz",allow_pickle=False) as d:
        quality=d['quality'];count=d['seed_count']
    q=np.array(ref['quarters']);result=[]
    for s in ref['segments']:
        t=np.arange(s['start_seconds']+.01,s['end_seconds'],.02)
        truth_q=q[(q>=s['start_seconds'])&(q<s['end_seconds'])]
        raw=np.zeros(len(t),dtype=bool);supported=raw.copy();best_fraction=0.;rates=[]
        si=np.clip((t/CONFIG['step']).astype(int),0,len(quality)-1)
        for j,h in enumerate(bank):
            if abs(h['bpm']-s['quarter_bpm'])>1e-8:continue
            rates.append(j);p=60/h['bpm'];tick=h['phase']+np.rint((t-h['phase'])/p)*p
            ok=nearest(tick,q)<=.07;raw|=ok
            supported |= ok&(quality[si,j]>=CONFIG['quality_threshold'])&(count[si,j]>=CONFIG['minimum_seed_quarters'])
            if len(truth_q):
                err=abs((truth_q-h['phase']+p/2)%p-p/2)
                best_fraction=max(best_fraction,float((err<=.07).mean()))
        result.append({**s,'nominal_rate_present':bool(rates),'exact_rate_clock_count':len(rates),
                       'best_single_clock_quarter_coverage':best_fraction,
                       'raw_correct_clock_fraction':float(raw.mean()) if len(raw) else 0.,
                       'qualified_correct_clock_fraction':float(supported.mean()) if len(supported) else 0.})
    total=sum(s['end_seconds']-s['start_seconds'] for s in result)
    return {'segments':result,'correct_clock_bank_fraction':sum((s['end_seconds']-s['start_seconds'])*s['raw_correct_clock_fraction'] for s in result)/total,
            'qualified_correct_clock_bank_fraction':sum((s['end_seconds']-s['start_seconds'])*s['qualified_correct_clock_fraction'] for s in result)/total,
            'reference_informed_diagnostic_not_prediction':True,'bank':bank_name}


def viable(r):
    return (r['correct_clock_fraction']>=GATES['song_correct_clock_min'] and
            r['quarter_f1_70']['f1']>=GATES['song_quarter_f1_min'] and
            r['wrong_clock_fraction']<=GATES['song_wrong_clock_max'] and
            r['successful_transitions']>=GATES['successful_transitions_per_song_min'] and
            r['long_regions_recovered']>=GATES['long_regions_per_song_min'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    rows=read(run/'evaluation-index.json')['rows'];by_id={r['id']:r for r in rows};metrics=[];groups=defaultdict(list)
    for tree in ['predictions','oracle-predictions']:
        for path in sorted((run/tree).glob('*/*/*.json')):
            method,policy=path.parts[-3:-1];ident=path.stem;row=by_id[ident];ref=read(run/'references'/f'{ident}.json')
            result=score(read(path),row,ref)
            record={'id':ident,'title':row['title'],'original_id':row['original_id'],'role':row['role'],
                    'partition':row['partition'],'method':method,'policy':policy,'tree':tree,**result}
            metrics.append(record);groups[(tree,method,policy,row['role'])].append(record)
    summary=[]
    for (tree,method,policy,role),rs in sorted(groups.items()):
        summary.append({'tree':tree,'method':method,'policy':policy,'role':role,'inputs':len(rs),
            'correct_clock_macro':float(np.mean([r['correct_clock_fraction'] for r in rs])),
            'correct_rate_macro':float(np.mean([r['correct_rate_fraction'] for r in rs])),
            'wrong_clock_macro':float(np.mean([r['wrong_clock_fraction'] for r in rs])),
            'unknown_macro':float(np.mean([r['unknown_fraction'] for r in rs])),
            'quarter_f1_macro':float(np.mean([r['quarter_f1_70']['f1'] for r in rs])),
            'successful_transitions':sum(r['successful_transitions'] for r in rs),
            'eligible_transitions':sum(r['eligible_transitions'] for r in rs),
            'false_tempo_changes':sum(r['false_tempo_changes'] for r in rs),
            'no_seed':sum(r['status']=='NO_SEED' for r in rs)})
    diagnostics=[]
    for row in rows:
        ref=read(run/'references'/f"{row['id']}.json")
        diagnostics.append({'id':row['id'],'role':row['role'],
                            'banks':{b:availability(run,row,ref,b) for b in ['final','small','expanded','unrefined']}})
    gates=[]
    for tree,methods in [('predictions',['M3_REGION_HOLD']),('oracle-predictions',['O_REGION_HOLD'])]:
        for method in methods:
            policies=['none','proxy100'] if tree=='predictions' else ['none']
            for policy in policies:
                rs=[r for r in metrics if r['tree']==tree and r['method']==method and r['policy']==policy and r['role']=='variable']
                passed=[r for r in rs if viable(r)];confirmation=[r for r in passed if r['partition']=='confirmation']
                controls=[r for r in metrics if r['tree']=='predictions' and r['method']==method and r['policy']==policy and r['role'] in ['fixed_control','meter_control']]
                baseline=[r for r in metrics if r['tree']=='predictions' and r['method']=='M1_NARROW_HOLD' and r['policy']==policy and r['role'] in ['fixed_control','meter_control']]
                delta=float(np.mean([r['wrong_clock_fraction'] for r in controls])-np.mean([r['wrong_clock_fraction'] for r in baseline])) if controls else None
                musical=len(passed)>=GATES['viable_real_songs_required'] and len(confirmation)>=GATES['confirmation_songs_required']
                control_ok=delta is None or delta<=GATES['control_wrong_clock_increase_max']
                gates.append({'tree':tree,'method':method,'policy':policy,'viable_songs':[r['id'] for r in passed],
                    'viable_confirmation_songs':[r['id'] for r in confirmation],'variable_viability_pass':musical,
                    'control_wrong_clock_increase':delta,'control_nonregression_pass':control_ok,
                    'overall_pass':musical and control_ok})
    write(run/'metrics.json',{'rows':metrics,'summary':summary})
    write(run/'candidate-availability.json',{'rows':diagnostics})
    write(run/'decision-gate.json',{'gates':gates,'criteria':GATES,'no_post_result_parameter_tuning':True})
    fields=['id','title','role','partition','tree','method','policy','status','correct_clock_fraction','wrong_clock_fraction','unknown_fraction','successful_transitions','eligible_transitions','false_tempo_changes']
    with (run/'metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows({k:r[k] for k in fields} for r in metrics)
    print('EVALUATED',len(metrics),'files',flush=True)


if __name__=='__main__':main()
