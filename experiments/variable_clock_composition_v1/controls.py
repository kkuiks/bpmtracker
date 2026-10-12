"""Mechanics controls independent of target songs and their references."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .common import CONFIG,read,write
from .compose import predict
from .evidence import table
from .proposals import unique_clocks


def make_events(regions,missing=None):
    times=[]
    for a,b,bpm,phase in regions:
        p=60/bpm;k=np.arange(np.ceil((a-phase)/p),np.ceil((b-phase)/p));times.extend((phase+k*p).tolist())
    t=np.array(sorted(times));duration=regions[-1][1]
    if missing:t=t[(t<missing[0])|(t>=missing[1])]
    return {'times':t,'weights':np.ones(len(t))*.95,'duration':duration,
            'pcm_times':t.copy(),'pcm_weights':np.ones(len(t))*.9}


def run_controls(run):
    rows=[]
    def check(name,passed,detail=None):rows.append({'name':name,'passed':bool(passed),'detail':detail})
    h={'bpm':128.5,'phase':.137,'provenance':'logical_fixture'}
    bank=unique_clocks([h,{'bpm':126.,'phase':.137},{'bpm':128.5,'phase':.27}],10)
    ev=make_events([(0,90,128.5,.137)],missing=(30,44));tab=table(ev,bank)
    p=predict(tab,'M3_REGION_HOLD')
    check('weak_gap_retains_rate_and_phase',bool(p['accepted']) and all(x['bpm']==128.5 and abs(x['phase']-.137)<1e-9 for x in p['accepted']))
    check('weak_gap_does_not_mute',sum(x['end']-x['start'] for x in p['accepted'])>=89.9)
    check('weak_gap_diagnostic_is_recorded',any(x['status']=='HELD_WEAK_EVIDENCE' for x in p['diagnostic']))
    delayed=make_events([(40,100,128.5,.137)]);dt=table(delayed,bank)
    region=predict(dt,'M3_REGION_HOLD');initial=predict(dt,'M2_INITIAL_FORWARD',{'anchor':'initial'})
    check('anywhere_seed_recovers_when_initial_deadline_fails',region['status']=='COMPOSED' and initial['status']=='NO_SEED')
    empty={**ev,'times':np.array([]),'weights':np.array([]),'pcm_times':np.array([]),'pcm_weights':np.array([])}
    check('no_evidence_cannot_create_clock',predict(table(empty,bank),'M3_REGION_HOLD')['status']=='NO_SEED')
    for bpm in [50.,93.75,140.25,189+2/3,390.]:
        hh=unique_clocks([{'bpm':bpm,'phase':.111}],5);tt=table(make_events([(0,70,bpm,.111)]),hh)
        pp=predict(tt,'M3_REGION_HOLD')
        check('constant_fraction_'+str(bpm),pp['status']=='COMPOSED' and all(x['bpm']==bpm for x in pp['accepted']))
    regions=[(0,30,120.,.13),(30,60,132.,.13),(60,95,120.,.29)]
    hh=unique_clocks([{'bpm':b,'phase':phi} for _,_,b,phi in regions],10)
    pp=predict(table(make_events(regions),hh),'M3_REGION_HOLD')
    def at(t):return next((x for x in pp['accepted'] if x['start']<=t<x['end']),None)
    check('nonharmonic_change_and_return_are_possible',all(at(t) is not None and at(t)['bpm']==b for t,b in [(15,120.),(45,132.),(80,120.)]),pp['accepted'])
    check('returning_bpm_can_have_new_phase',at(80) is not None and abs(at(80)['phase']-.29)<1e-8)
    check('physical_source_coordinates_preserved',all(0<=x['start']<x['end']<=95 for x in pp['accepted']))
    shifted=make_events([(0,90,128.5,.537)],missing=(30.4,44.4))
    pp=predict(table(shifted,unique_clocks([{'bpm':128.5,'phase':.537}],5)),'M3_REGION_HOLD')
    check('shifted_phase_not_reset_to_zero',pp['status']=='COMPOSED' and all(abs((x['phase']-.537)%(60/128.5))<1e-8 or abs((x['phase']-.537)%(60/128.5)-60/128.5)<1e-8 for x in pp['accepted']))
    write(run/'logical-controls.json',{'rows':rows,'passed':all(r['passed'] for r in rows),
        'musical_accuracy_or_generalization_claim':False,'target_data_read':False})
    print('LOGICAL_CONTROLS',sum(r['passed'] for r in rows),'/',len(rows),flush=True)
    if not all(r['passed'] for r in rows):raise RuntimeError('Mechanics control failed before target freeze')


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run_controls(a.run)


if __name__=='__main__':main()
