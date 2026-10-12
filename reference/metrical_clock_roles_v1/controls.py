"""Authored observation-level controls, not independently recorded music."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from .common import CONFIG,METHODS,read,write
from .evidence import build
from .decode import predict,layer
from .evaluate import score

def make(segments,role_events=None,meter_events=None,missing=None,duration=36.):
    q=[];bt=[];dt=[];clocks=[];pieces=[]
    role_events=role_events or [(0.,1.)];meter_events=meter_events or [(0.,4.)]
    def state(events,t):return [v for x,v in events if x<=t][-1]
    for n,(start,bpm,phase) in enumerate(segments):
        end=segments[n+1][0] if n+1<len(segments) else duration;p=60/bpm
        pieces.append({'start_seconds':start,'end_seconds':end,'quarter_bpm':bpm})
        q.extend((phase+np.arange(np.ceil((start-phase)/p),np.ceil((end-phase)/p))*p).tolist())
        boundaries=sorted(set([start,end]+[x for x,_ in role_events+meter_events if start<x<end]))
        for a,z in zip(boundaries[:-1],boundaries[1:]):
            g=state(role_events,a);m=state(meter_events,a)
            for target,period in [(bt,p*g),(dt,p*m)]:
                target.extend((phase+np.arange(np.ceil((a-phase)/period),np.ceil((z-phase)/period))*period).tolist())
        for factor in [.5,1.,1.5,2.]:
            if 30<=bpm*factor<=400:clocks.append({'bpm':bpm*factor,'phase':phase%(p/factor),'source_quality':1.})
        for g in [state(role_events,start),state(role_events,end-1e-6)]:
            native=bpm/g
            if 30<=native<=400:clocks.append({'bpm':native,'phase':phase%(60/native),'source_quality':1.})
    bt=np.array(sorted(set(bt)));dt=np.array(sorted(set(dt)));q=np.array(sorted(set(q)))
    if missing:
        for a,z in missing:bt=bt[(bt<a)|(bt>=z)];dt=dt[(dt<a)|(dt>=z)]
    fps=50.;t=np.arange(int(duration*fps))/fps
    def logits(events):
        prob=np.full(len(t),.001)
        for e in events:prob=np.maximum(prob,.999*np.exp(-.5*((t-e)/.018)**2))
        prob=np.clip(prob,.0001,.9999);return np.log(prob/(1-prob)).astype(np.float32)
    ev={'times':bt,'weights':np.full(len(bt),.999),'downbeat_times':dt,
        'downbeat_weights':np.full(len(dt),.999),'duration':duration}
    sensor={'beat_logits':logits(bt),'downbeat_logits':logits(dt),'fps':fps}
    trans=[{'time':b['start_seconds'],'left_bpm':a['quarter_bpm'],'right_bpm':b['quarter_bpm'],
            'left_start':a['start_seconds'],'right_end':b['end_seconds']} for a,b in zip(pieces,pieces[1:]) if a['quarter_bpm']!=b['quarter_bpm']]
    ref={'support':[[0.,duration]],'segments':pieces,'quarters':q.tolist(),
         'transitions':trans,'initial_bpm':pieces[0]['quarter_bpm']}
    return ev,sensor,clocks,ref

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();rows=[]
    cases=[
      ('fixed_dense',[(0.,120.,0.)],None,None,None),
      ('fixed_half_observed',[(0.,240.,0.)],[(0.,2.)],None,None),
      ('neural_half_change',[(0.,120.,0.)],[(0.,1.),(12.,2.),(24.,1.)],None,None),
      ('neural_subdivision_change',[(0.,120.,0.)],[(0.,1.),(12.,.5),(24.,1.)],None,None),
      ('triplet_role',[(0.,190.,0.)],[(0.,1.5)],None,None),
      ('nonharmonic_changes',[(0.,120.,0.),(12.,180.,0.),(24.,120.,0.)],None,None,None),
      ('real_double_change',[(0.,90.,0.),(12.,180.,0.),(24.,90.,0.)],None,None,None),
      ('meter_changes_only',[(0.,120.,0.)],None,[(0.,4.),(12.,3.),(24.,4.)],None),
      ('missing_middle_hold',[(0.,120.,0.)],None,None,[(8.,16.)]),
      ('same_rate_new_phase',[(0.,120.,0.),(12.,180.,0.),(24.,120.,.17)],None,None,None),
      ('ambiguous_role_and_meter_change',[(0.,90.,0.)],[(0.,1.),(12.,.5),(24.,1.)],[(0.,4.),(12.,2.),(24.,4.)],None),
    ]
    for name,segments,roles,meters,missing in cases:
        ev,sensor,clocks,ref=make(segments,roles,meters,missing)
        tab=build(ev,sensor,clocks,{**CONFIG,'state_budget':256,'source_candidate_budget':64})
        unit=tab['source_unit'];packet={**unit,'unit_index':int(layer(ref['initial_bpm'],unit['base_bpm'],CONFIG)) if unit['available'] else None}
        pred=predict(tab,'R2_ROLES_BARS',METHODS['R2_ROLES_BARS'],packet)
        metric=score(pred,{'duration_seconds':36.},ref)
        write(a.run/'observation-controls'/name/'prediction.json',pred);write(a.run/'observation-controls'/name/'reference.json',ref)
        rows.append({'name':name,**metric,'mechanism_control_not_real_music':True,
                     'underdetermined_pair':name in ['real_double_change','ambiguous_role_and_meter_change']})
        print('CONTROL',name,round(metric['correct_clock_fraction'],4),metric['tempo_changes'],flush=True)
    ev,sensor,clocks,ref=make([(0.,120.,0.)],missing=[(0.,36.)])
    tab=build(ev,sensor,clocks,{**CONFIG,'state_budget':256});pred=predict(tab,'R2_ROLES_BARS',METHODS['R2_ROLES_BARS'])
    rows.append({'name':'no_observation_no_clock','status':pred['status'],'accepted':pred['accepted'],
                 'mechanism_control_not_real_music':True})
    one=make([(0.,90.,0.),(12.,180.,0.),(24.,90.,0.)])
    two=make([(0.,90.,0.)],[(0.,1.),(12.,.5),(24.,1.)],[(0.,4.),(12.,2.),(24.,4.)])
    identical=all(np.array_equal(one[0][k],two[0][k]) for k in ['times','weights','downbeat_times','downbeat_weights']) and all(np.array_equal(one[1][k],two[1][k]) for k in ['beat_logits','downbeat_logits'])
    shared=[];keys=set()
    for c in one[2]+two[2]:
        key=(c['bpm'],c['phase'])
        if key not in keys:shared.append(c);keys.add(key)
    tab=build(one[0],one[1],shared,{**CONFIG,'state_budget':256})
    unit=tab['source_unit'];packet={**unit,'unit_index':int(layer(90.,unit['base_bpm'],CONFIG))}
    shared_prediction=predict(tab,'R2_ROLES_BARS',METHODS['R2_ROLES_BARS'],packet)
    write(a.run/'ambiguous-pair/prediction.json',shared_prediction)
    write(a.run/'ambiguous-pair/reference-tempo-change.json',one[3])
    write(a.run/'ambiguous-pair/reference-role-meter-change.json',two[3])
    pair_metrics=[score(shared_prediction,{'duration_seconds':36.},r) for r in [one[3],two[3]]]
    write(a.run/'ambiguous-pair/metrics.json',{'rows':pair_metrics,'same_candidate_bank_and_same_prediction':True,
                                            'known_clock_component_control':True})
    write(a.run/'observation-controls.json',{'rows':rows,'actual_music_or_neural_generalization':False,
          'identical_observation_pair':identical,
          'pair_has_different_quarter_references':one[3]['segments']!=two[3]['segments'],
          'paired_quarter_interpretations_cannot_both_be_identified_from_these_observations':True,
          'pair_same_bank_single_prediction':True,
          'determinate_controls_pass':all(r.get('correct_clock_fraction',1.)>=.90 for r in rows if not r.get('underdetermined_pair')) and not pred['accepted']})

if __name__=='__main__':main()
