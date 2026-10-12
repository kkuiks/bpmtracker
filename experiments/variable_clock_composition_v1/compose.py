"""Find a trustworthy region anywhere, then connect clocks with held phase."""
from __future__ import annotations

import math
import numpy as np

from .common import CONFIG
from .evidence import intervals,seed_episodes


def initial_episode(tab,cfg):
    episodes=seed_episodes(tab,cfg)
    if not episodes:return None
    earliest=min(e['start'] for e in episodes)
    early=[e for e in episodes if e['start']<=earliest+1. and e['start']<=cfg['initial_deadline']]
    return max(early,key=lambda e:(e['quality'],e['rank'])) if early else None


def source_initial_unit(tab,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg);e=initial_episode(tab,cfg)
    return {'available':e is not None,'base_bpm':e['bpm'] if e else None,
            'scope_start':e['start'] if e else None,'scope_end':e['end'] if e else None,
            'clock':e['clock'] if e else None,'source_only':True}


def phase_distance(a,b,time):
    pa,pb=60/a['bpm'],60/b['bpm']
    qa=a['phase']+round((time-a['phase'])/pa)*pa
    qb=b['phase']+round((time-b['phase'])/pb)*pb
    return min(1.,abs(qa-qb)/min(pa,pb))


def destinations(q,count,clocks,now,cfg,pcm=None):
    use=np.flatnonzero((q>=cfg['quality_threshold'])&(count>=cfg['minimum_seed_quarters']))
    selected=[]
    for j in use[np.argsort(q[use])[::-1]]:
        if pcm is not None and pcm[j]<.15:continue
        h=clocks[j]
        if any(abs(math.log(h['bpm']/clocks[k]['bpm']))<.005 and phase_distance(h,clocks[k],now)<.08 for k in selected):
            continue
        selected.append(int(j))
        if len(selected)>=cfg['destination_beam']:break
    return selected


def decode_side(tab,cfg,anchor,order,allowed,pcm_mode=False):
    k=len(tab['clocks']);n=len(order);quality=tab['quality'];time=tab['time'];dt=cfg['step']
    clocks=tab['clocks'];bpm=np.array([h['bpm'] for h in clocks]);explanation=tab['explanation']
    score=np.full(k,-np.inf);score[anchor]=0.;back=np.empty((n,k),dtype=np.int32)
    identity=np.arange(k,dtype=np.int32);sustain=np.zeros(k,dtype=np.int32)
    for a,i in enumerate(order):
        q=quality[i];best=float(q.max()) if len(q) else 0.
        conflict=(tab['information'][i] & (best>=cfg['contradiction_quality']) &
                  (best-q>=cfg['contradiction_margin']) & (explanation[i]<1-cfg['contradiction_unexplained']))
        sustain=np.where(conflict,sustain+1,0)
        sustained=sustain*dt+1e-9>=cfg['contradiction_seconds']
        # Long windows qualify clocks; the actual interval boundaries use local
        # event evidence as well, avoiding a boundary blurred by an eight-second
        # centered support window.
        emitted_quality=.50*tab['local_quality'][i]+.35*tab['short_quality'][i]+.15*tab['long_quality'][i]
        emission=np.maximum(emitted_quality-.50,0.)*dt
        emission-=sustained*np.maximum(best-q-.10,0.)*dt
        if not tab['information'][i]:emission[:]=0.
        if pcm_mode:emission*=.8+.4*tab['pcm'][i]
        prior=score.copy();parents=identity.copy()
        if a:
            finite=np.flatnonzero(np.isfinite(score))
            beam=finite[np.argsort(score[finite])[-cfg['beam']:]]
            dest=destinations(q,tab['seed_count'][i],clocks,float(time[i]),cfg,tab['pcm'][i] if pcm_mode else None)
            for j in dest:
                if not len(beam):continue
                permitted=sustained[beam] & (q[j]-q[beam]>=cfg['contradiction_margin'])
                # A phase reanchor also requires sustained competing evidence;
                # lack of matches alone cannot terminate the held clock.
                sources=beam[permitted]
                if not len(sources):continue
                cost=cfg['change_penalty']+cfg['octave_penalty']*abs(np.log2(bpm[j]/bpm[sources]))
                if cfg['phase_penalty']:
                    cost+=cfg['phase_penalty']*np.array([phase_distance(clocks[int(s)],clocks[j],float(time[i])) for s in sources])
                values=score[sources]-cost
                winner=int(np.argmax(values))
                if values[winner]>prior[j]+1e-12:
                    prior[j]=values[winner];parents[j]=int(sources[winner])
        score=prior+emission
        if allowed is not None:score[~allowed[i]]=-np.inf
        back[a]=parents
    if not np.isfinite(score).any():return None
    state=int(np.argmax(score));path=np.empty(n,dtype=np.int32)
    for a in range(n-1,-1,-1):
        path[a]=state;state=int(back[a,state])
    return path


def summarize(path,tab,cfg,method,policy,anchor=None):
    accepted=[];diagnostic=[];time=tab['time'];step=cfg['step'];clocks=tab['clocks']
    if len(path):
        changes=np.r_[0,np.flatnonzero(np.diff(path)!=0)+1,len(path)]
        for a,b in zip(changes[:-1],changes[1:]):
            j=int(path[a]);start=max(0.,float(time[a]-step/2));end=min(tab['duration'],float(time[b-1]+step/2))
            if j<0:
                diagnostic.append({'start':start,'end':end,'status':'NO_SOURCE_CLOCK'});continue
            h=clocks[j];accepted.append({'start':start,'end':end,'bpm':h['bpm'],'phase':h['phase'],
                                      'period':60/h['bpm'],'clock_index':j,'provenance':h.get('provenance','source')})
            weak=(tab['quality'][a:b,j]<cfg['quality_threshold']) | (tab['count'][a:b,j]<4)
            for x,y in intervals(weak):
                diagnostic.append({'start':max(start,float(time[a+x]-step/2)),
                                   'end':min(end,float(time[a+y-1]+step/2)),
                                   'status':'HELD_WEAK_EVIDENCE','bpm':h['bpm'],'phase':h['phase']})
    return {'status':'COMPOSED' if accepted else 'NO_SEED','method':method,'policy':policy,
            'accepted':accepted,'diagnostic':diagnostic,'anchor':anchor,
            'future_audio_used':True,'meter_inference':False,'clock_domain':[30,400],
            'no_audio_removed_or_concatenated':True,'raw_numeric_hint_used':False,
            'whole_song_numeric_hint_constraint':False}


def predict(tab,method,options=None,unit_packet=None,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg);options=options or {}
    for k in ['phase_penalty','change_penalty','quality_threshold']:
        if k in options:cfg[k]=options[k]
    policy='proxy' if unit_packet is not None else 'none'
    n=len(tab['time']);k=len(tab['clocks']);path=np.full(n,-1,dtype=np.int32)
    def finish(path,anchor=None):
        result=summarize(path,tab,cfg,method,policy,anchor)
        if unit_packet is not None and unit_packet.get('available'):
            result['initial_unit_scope']={'start':unit_packet['scope_start'],'end':unit_packet['scope_end'],
                                         'discrete_power':unit_packet['power']}
        return result
    if not k or not n:return finish(path)
    allowed=None
    if unit_packet is not None and unit_packet.get('available'):
        base=unit_packet['base_bpm'];power=unit_packet['power']
        layers=np.floor(np.log2(np.array([h['bpm'] for h in tab['clocks']])/base)+.5).astype(int)
        use=(tab['time']>=unit_packet['scope_start'])&(tab['time']<unit_packet['scope_end'])
        allowed=np.ones((n,k),dtype=bool);allowed[use]=layers==power
    if options.get('mode')=='local':
        q=tab['quality'].copy()
        if allowed is not None:q[~allowed]=-1
        winner=np.argmax(q,axis=1);ok=(q[np.arange(n),winner]>=cfg['quality_threshold']) & (tab['seed_count'][np.arange(n),winner]>=cfg['minimum_seed_quarters'])
        path[ok]=winner[ok]
        return finish(path)
    episodes=seed_episodes(tab,cfg)
    if not episodes:return finish(path)
    if options.get('anchor')=='initial':
        chosen=initial_episode(tab,cfg)
        if chosen is None:return finish(path)
        at=chosen['start_index']
    else:
        chosen=episodes[0];at=(chosen['start_index']+chosen['end_index']-1)//2
    if allowed is not None and not allowed[at,chosen['clock']]:
        possible=[e for e in episodes if allowed[(e['start_index']+e['end_index']-1)//2,e['clock']]]
        if not possible:return finish(path)
        chosen=possible[0];at=(chosen['start_index']+chosen['end_index']-1)//2
    right_order=np.arange(at,n)
    right=decode_side(tab,cfg,chosen['clock'],right_order,allowed,options.get('pcm',False))
    if right is not None:path[right_order]=right
    if options.get('anchor')!='initial':
        left_order=np.arange(at,-1,-1)
        left=decode_side(tab,cfg,chosen['clock'],left_order,allowed,options.get('pcm',False))
        if left is not None:path[left_order]=left
    if options.get('mute_weak'):
        active=np.flatnonzero(path>=0);j=path[active]
        weak=(tab['quality'][active,j]<cfg['quality_threshold'])|(tab['count'][active,j]<4)
        path[active[weak]]=-1
    anchor={k:v for k,v in chosen.items() if k!='clock'}
    anchor['clock_key']=tab['clocks'][chosen['clock']]['key']
    return finish(path,anchor)
