"""Score unit discrimination after all validation predictions are serialized."""
import argparse
from collections import defaultdict
from pathlib import Path
import numpy as np
from .common import CONFIG,CRITERIA,VALIDATION,FACTORS,read,write,digest,guard
from .worker import arrays
from .labels import label

def score(pred,feat,ref,original=None):
    labels=label(feat,ref);support=labels['in_support'];chosen=np.array([r['unit_index'] for r in pred['rows']])
    correct=(chosen>=0)&(chosen==labels['unit_index']);available=feat['source_available'];family=labels['family_representable']
    if not support.any():raise RuntimeError('Empty supported unit evaluation')
    n=int(support.sum());segments=[]
    for s in ref['segments']:
        mask=support&(feat['time']>=s['start_seconds'])&(feat['time']<s['end_seconds'])
        segments.append({**s,'windows':int(mask.sum()),'accuracy':float(correct[mask].mean()) if mask.any() else None})
    transitions=[]
    for tr in ref['transitions']:
        t=tr['time'];before=np.flatnonzero(support&(feat['time']>=tr['left_start'])&(feat['time']<t)&(feat['time']>=t-20))
        after=np.flatnonzero(support&(feat['time']>=t)&(feat['time']<tr['right_end'])&(feat['time']<=t+20))
        eligible=len(before)>0 and len(after)>0
        transitions.append({**tr,'eligible_source_centers_both_sides':bool(eligible),
                            'before_unit_correct':bool(correct[before[-1]]) if len(before) else None,
                            'after_unit_correct':bool(correct[after[0]]) if len(after) else None,
                            'both_unit_correct':bool(correct[before[-1]] and correct[after[0]]) if eligible else False,
                            'not_boundary_or_fine_clock_recovery':True})
    sensor=[]
    for i in range(1,len(chosen)):
        if not support[i-1:i+1].all():continue
        a,b=feat['neural_median_bpm'][i-1:i+1]
        if min(a,b)<=0 or max(a,b)/min(a,b)<1.25:continue
        x,y=labels['truth_bpm'][i-1:i+1]
        if abs(x/y-1)>.05:continue
        typ='SENSOR_LEVEL_ONLY' if abs(x-y)<1e-8 else 'SENSOR_LEVEL_WITH_SMALL_TRUE_TEMPO_CHANGE'
        sensor.append({'left_time':float(feat['time'][i-1]),'right_time':float(feat['time'][i]),
                       'type':typ,'true_left_bpm':float(x),'true_right_bpm':float(y),
                       'native_median_left':float(a),'native_median_right':float(b),
                       'both_unit_correct':bool(correct[i-1] and correct[i])})
    meters=[]
    if original:
        states=original.get('meter_events',original.get('signature_events',[]));last=None
        for e in states:
            meter=(e.get('numerator'),e.get('denominator'));t=e.get('time_seconds',e.get('master_seconds'))
            if t is None:continue
            if last is not None and meter!=last and float(t)>0:
                m=support&(abs(feat['time']-float(t))<=12)
                meters.append({'time':float(t),'meter':list(meter),'windows':int(m.sum()),
                               'unit_accuracy_near_change':float(correct[m].mean()) if m.any() else None})
            last=meter
    def fraction(mask):return float(correct[mask].mean()) if mask.any() else None
    true_double=[]
    for tr in ref['transitions']:
        ratio=tr['right_bpm']/tr['left_bpm']
        if not (abs(ratio-2)<1e-8 or abs(ratio-.5)<1e-8):continue
        mask=support&(feat['time']>=tr['time'])&(feat['time']<tr['right_end'])
        true_double.append({**tr,'post_windows':int(mask.sum()),'post_unit_accuracy':fraction(mask)})
    return {'windows_in_support':n,'correct_unit_windows':int((correct&support).sum()),
            'unit_accuracy':float(correct[support].mean()),
            'source_coverage':float(available[support].mean()),'family_coverage':float(family[support].mean()),
            'conditional_unit_accuracy':fraction(support&available&family),
            'unavailable_windows':int((support&~available).sum()),'unrepresentable_windows':int((support&~family).sum()),
            'segments':segments,'tempo_transitions':transitions,'true_double_transitions':true_double,
            'sensor_level_pairs':sensor,'sensor_level_pairs_correct':sum(r['both_unit_correct'] for r in sensor),
            'sensor_level_pair_count':len(sensor),'meter_changes':meters}

def bootstrap_gain(primary,baseline):
    delta=np.array([p['unit_accuracy']-b['unit_accuracy'] for p,b in zip(primary,baseline)])
    rng=np.random.default_rng(CONFIG['bootstrap_seed']);sample=rng.integers(0,len(delta),(CONFIG['bootstrap_repetitions'],len(delta)))
    values=delta[sample].mean(axis=1)
    return {'macro_gain':float(delta.mean()),'lower_95':float(np.quantile(values,.025)),
            'upper_95':float(np.quantile(values,.975)),'song_cluster_bootstrap':True,'songs':len(delta)}

def decision(rows,method):
    baseline=CRITERIA['baseline'];table={(r['method'],r['policy'],r['id']):r for r in rows}
    ids=[r['id'] for r in rows if r['method']==method and r['policy']=='proxy100' and r['partition']=='validation' and r['role']=='variable']
    ids=sorted(set(ids));p=[table[(method,'proxy100',i)] for i in ids];b=[table[(baseline,'proxy100',i)] for i in ids]
    gain=bootstrap_gain(p,b);acc=float(np.mean([r['unit_accuracy'] for r in p]));old=float(np.mean([r['unit_accuracy'] for r in b]))
    positive=[i for i,x,y in zip(ids,p,b) if x['unit_accuracy']-y['unit_accuracy']>=CRITERIA['positive_song_gain_min']]
    stable=[i for i,x,y in zip(ids,p,b) if x['unit_accuracy']-y['unit_accuracy']>=-CRITERIA['song_max_regression']]
    control_ids=sorted(set(r['id'] for r in rows if r['method']==method and r['policy']=='proxy100' and r['partition']=='validation' and r['role'] in ['fixed_control','meter_control']))
    cp=[table[(method,'proxy100',i)] for i in control_ids];cb=[table[(baseline,'proxy100',i)] for i in control_ids]
    cd=float(np.mean([x['unit_accuracy']-y['unit_accuracy'] for x,y in zip(cp,cb)]))
    jp=table[(method,'proxy100','r005')]['true_double_transitions'];jb=table[(baseline,'proxy100','r005')]['true_double_transitions']
    double=jp[0]['post_unit_accuracy'] if jp else None;double_old=jb[0]['post_unit_accuracy'] if jb else None
    sn=sum(r['sensor_level_pair_count'] for r in p);sp=sum(r['sensor_level_pairs_correct'] for r in p);sb=sum(r['sensor_level_pairs_correct'] for r in b)
    sensor_delta=(sp-sb)/sn if sn else None
    reduction=(acc-old)/max(1-old,1e-9)
    checks={'accuracy':acc>=CRITERIA['validation_variable_accuracy_min'],
            'gain':gain['macro_gain']>=CRITERIA['validation_variable_gain_min'],
            'error_reduction':reduction>=CRITERIA['relative_unit_error_reduction_min'],
            'positive_songs':len(positive)>=CRITERIA['positive_songs_required'],
            'nonregressed_songs':len(stable)>=CRITERIA['nonregressed_songs_required'],
            'bootstrap_lower_positive':gain['lower_95']>CRITERIA['bootstrap_gain_lower_min'],
            'control_nonregression':cd>=-CRITERIA['control_accuracy_max_decline'],
            'true_double':double is not None and double>=CRITERIA['true_double_post_accuracy_min'] and double>=double_old,
            'sensor_level_nonregression':sensor_delta is not None and sensor_delta>=-CRITERIA['sensor_level_pair_max_decline']}
    return {'method':method,'baseline':baseline,'variable_accuracy':acc,'baseline_variable_accuracy':old,
            'bootstrap_gain':gain,'relative_unit_error_reduction':reduction,'positive_songs':positive,
            'nonregressed_songs':stable,'control_accuracy_delta':cd,
            'Juno_true_double_post_accuracy':double,'Juno_baseline_true_double_post_accuracy':double_old,
            'sensor_level_pairs':sn,'sensor_pair_accuracy_delta':sensor_delta,
            'checks':checks,'pass':all(checks.values()),'not_full_map_success':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    models=read(run/'model-freeze.json');required=CRITERIA['confirmatory_audio_methods']+[CRITERIA['baseline']]
    for method in required:
        if any(not (run/'predictions'/method/'proxy100'/f'{i}.json').exists() for i in VALIDATION):raise RuntimeError('Validation predictions incomplete')
    table={r['id']:r for r in read(run/'evaluation-index.json')['rows']};rows=[];groups=defaultdict(list)
    for path in sorted((run/'predictions').glob('*/*/*.json')):
        method,policy=path.parts[-3:-1];ident=path.stem;row=table[ident];ref=read(run/'references'/f'{ident}.json')
        op=run/'references'/f'{ident}.original.json';original=read(op) if op.exists() else None
        result=score(read(path),arrays(run/'features'/f'{ident}.npz'),ref,original)
        record={k:row[k] for k in ['id','title','role','partition']};record.update({'method':method,'policy':policy,**result})
        rows.append(record);groups[(method,policy,row['partition'],row['role'])].append(record)
    summary=[]
    for (method,policy,partition,role),rs in sorted(groups.items()):
        summary.append({'method':method,'policy':policy,'partition':partition,'role':role,'songs':len(rs),
                        'unit_accuracy_macro':float(np.mean([r['unit_accuracy'] for r in rs])),
                        'unit_accuracy_micro':sum(r['correct_unit_windows'] for r in rs)/sum(r['windows_in_support'] for r in rs),
                        'family_coverage_macro':float(np.mean([r['family_coverage'] for r in rs])),
                        'source_coverage_macro':float(np.mean([r['source_coverage'] for r in rs]))})
    decisions=[decision(rows,m) for m in CRITERIA['confirmatory_audio_methods']]
    write(run/'metrics.json',{'rows':rows,'summary':summary})
    write(run/'decision.json',{'hypotheses':decisions,'criteria':CRITERIA,
                              'audio_discriminator_validated':any(d['pass'] for d in decisions),
                              'two_prespecified_audio_hypotheses_not_posthoc_arm_promotion':True,
                              'not_app_or_full_map_acceptance':True})
    for d in decisions:print('DECISION',d,flush=True)
    print('SCORED',len(rows),flush=True)

if __name__=='__main__':main()
