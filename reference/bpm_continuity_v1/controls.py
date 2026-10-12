"""Small deterministic source fixtures; not enrolled songs or music scores."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import numpy as np

from experiments.metronome_reconstruction_v1.hinted import encode_tap_level
from experiments.variable_tempo_interval_consensus_v0.candidates import pool
from .common import CONFIG, read, write, object_hash
from .core import bootstrap, predict
from .evidence import Evidence


def fixture(sections=((160.,64),), density=None, silence=None, shift=None):
    cursor=.137; clocks=[]; peaks=[]; boundaries=[]
    for bpm,count in sections:
        p=60./bpm; phase=cursor%p
        clocks.append({'bpm':bpm,'phase':phase,'bars':[phase],'source_score':1.,'provenance':'source_fixture'})
        boundaries.append({'time':cursor,'bpm':bpm,'phase':phase})
        for k in range(count):
            t=cursor+k*p
            if density=='half' and 12<=t<28 and k%2: continue
            if shift is not None and t>=12: t+=shift
            peaks.append(t)
            if density=='double' and 12<=t<28: peaks.append(t+p/2)
        cursor+=count*p
    if shift is not None:
        clocks.append(dict(clocks[0],phase=(clocks[0]['phase']+shift)%(60./clocks[0]['bpm'])))
    if density or silence:
        h=clocks[0]
        for rate in (h['bpm']/2,h['bpm']*2):
            if 30<=rate<=400:
                clocks.append(dict(h,bpm=rate,phase=h['phase']%(60./rate)))
    duration=cursor+.4; n=math.ceil(duration*50)
    beat=np.full(n,-16.);down=np.full(n,-16.)
    for t in peaks:
        if silence and silence[0]<=t<silence[1]: continue
        index=round(t*50)
        if index<n: beat[index]=9.
    mask=np.zeros(n,dtype=bool)
    if silence:
        times=np.arange(n)/50;mask[(times>=silence[0])&(times<silence[1])]=True
    bank,_=pool(clocks)
    return {'beat_logits':beat,'downbeat_logits':down,'fps':np.array(50),
            'duration_seconds':np.array(duration),'silent_frame_mask':mask},bank,boundaries


def recovery(prediction,boundary,end):
    # Logical check of eight consecutive rendered quarters without unknown gaps.
    for r in prediction['accepted']:
        if r['end']<=boundary['time'] or r['start']>=end or r['bpm']!=boundary['bpm']: continue
        p=r['period'];start=max(r['start'],boundary['time'])
        q=r['phase']+math.ceil((start-r['phase'])/p)*p
        if q+7*p<min(r['end'],end)-1e-9:
            phase_error=abs((q-boundary['phase']+p/2)%p-p/2)
            if phase_error<=.07: return q-boundary['time']
    return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve()
    cfg=read(run/'config.json');rows=[]
    def check(name,passed,details=None,kind='logical'):
        rows.append({'name':name,'passed':bool(passed),'details':details,'kind':kind})
        print('CONTROL',name,'PASS' if passed else 'FAIL',flush=True)
    for name,kwargs in [('DENSITY_HALF',{'density':'half'}),('DENSITY_DOUBLE',{'density':'double'}),
                        ('SILENCE_GAP',{'silence':(12.,20.)}),('PHASE_SHIFT',{'shift':.07})]:
        data,bank,bounds=fixture(((160.,128),),**kwargs)
        ev=Evidence(data,bank,cfg);boot=bootstrap(ev,{'kind':'oracle','initial_bpm':160.})
        pred,trace=predict(ev,boot,'C2_CONTINUITY')
        check(name+'_NO_WRONG_RATE',bool(pred['accepted']) and all(r['bpm']==160 for r in pred['accepted']),
              {'bootstrap':boot['status'],'accepted_spans':len(pred['accepted'])})
        if name=='SILENCE_GAP':
            check('SILENCE_OUTPUT_EMPTY',not any(r['start']<20 and r['end']>12 for r in pred['accepted']))
            check('SILENCE_MEMORY_RETAINED',all(t['remembered'] and t['remembered']['bpm']==160 for t in trace if 12<=t['t']<20))
            check('SILENCE_RECOVERY',any(r['bpm']==160 and r['end']>24 for r in pred['accepted']))
        if name=='PHASE_SHIFT':
            check('PHASE_REANCHOR_SEPARATE',any(c['kind']=='PHASE_REANCHOR' for c in pred['changes']) and
                  not any(c['kind']=='BPM_CHANGE' for c in pred['changes']))
        # Independent, direct matching reconstruction checks the optimized table.
        for i in [min(13,len(ev.time)-1),min(60,len(ev.time)-1),len(ev.time)-3]:
            for j in range(len(bank)):
                matches=ev.matches(i,j)
                times=ev.obs['beat']['times'];weights=ev.obs['beat']['weights']
                mass=float(weights[(times>=ev.start[i])&(times<ev.time[i])].sum())
                reward=sum(m['weight']*math.exp(-.5*(m['residual']/cfg['epsilon'])**2) for m in matches)
                direct=reward/mass if mass else 0.
                primary=[m for m in matches if m['primary']]
                check(f'MATCH_TABLE_{name}_{i}_{j}',abs(direct-ev.G[i,j])<1e-9 and len(primary)==ev.count[i,j])
        if name=='DENSITY_HALF':
            unit=[encode_tap_level(160,number)['power'] for number in (152,160,168)]
            boots=[bootstrap(ev,{'kind':'proxy','power':power}) for power in unit]
            outputs=[predict(ev,b,'C2_CONTINUITY') for b in boots]
            check('PROXY_95_100_105_EQUIVALENCE',len(set(unit))==1 and len({object_hash(o) for o in outputs})==1)
            p2,t2=predict(ev,boot,'C2_CONTINUITY')
            check('DETERMINISM',object_hash((pred,trace))==object_hash((p2,t2)))
            missing=bootstrap(ev,{'kind':'oracle','initial_bpm':137})
            check('MISSING_CANDIDATE_NO_SEED',missing['status']=='NO_SEED' and missing['seed'] is None)
    data,bank,bounds=fixture(((160.,64),(150.,64),(160.,64)))
    ev=Evidence(data,bank,cfg);boot=bootstrap(ev,{'kind':'oracle','initial_bpm':160.})
    pred,trace=predict(ev,boot,'C2_CONTINUITY')
    delays=[recovery(pred,b,bounds[k+1]['time'] if k+1<len(bounds) else ev.duration) for k,b in enumerate(bounds) if k>0]
    check('REAL_CHANGE_160_150_160',all(d is not None and 0<=d<=8 for d in delays),{'delays':delays,'changes':pred['changes']})
    held,_=predict(ev,boot,'C_HOLD')
    check('HOLD_CONTROL_NEVER_CHANGES_BPM',all(r['bpm']==160 for r in held['accepted']) and
          not any(c['kind']=='BPM_CHANGE' for c in held['changes']))
    data,bank,bounds=fixture(((160.,64),(240.,64)))
    ev=Evidence(data,bank,cfg);boot=bootstrap(ev,{'kind':'oracle','initial_bpm':160.})
    pred,trace=predict(ev,boot,'C2_CONTINUITY')
    delay=recovery(pred,bounds[1],ev.duration)
    alias=[t['drift'] for t in trace if t['drift'] and t['drift'].get('passed')]
    check('NONHARMONIC_UNWRAP_160_240',delay is not None and delay<=8 and
          any(d['slope']<0 and d['principal_unwrap_slope']>0 for d in alias),{'delay':delay})
    data,bank,bounds=fixture(((160.,128),),density='double')
    # An explicitly wrong but source-compatible initial unit remains an error;
    # this control prevents calling wrong-clock locking a recovery success.
    ev=Evidence(data,bank,cfg);boot=bootstrap(ev,{'kind':'oracle','initial_bpm':80.})
    wrong,_=predict(ev,boot,'C2_CONTINUITY')
    check('WRONG_SEED_LOCK_LIMITATION',boot['status']=='SEEDED' and all(r['bpm']==80 for r in wrong['accepted']),kind='known_limitation')
    data,bank,bounds=fixture(((60.,64),))
    slow=bootstrap(Evidence(data,bank,cfg),{'kind':'oracle','initial_bpm':60.})
    check('SLOW_CLOCK_WINDOW_LIMITATION',slow['status']=='NO_SEED',kind='known_limitation')
    # Formal isolation is additionally enforced and recorded by source workers.
    write(run/'controls.json',{'rows':rows,'passed':all(r['passed'] for r in rows),
                               'fixture_only_not_music_accuracy':True,'version':'1.2',
                               'source_quantization_fps':50,'targets_scored_before_controls':False})
    if not all(r['passed'] for r in rows): raise SystemExit(2)


if __name__=='__main__': main()
