"""Clock evidence and seed episodes on original, uncut source coordinates."""
from __future__ import annotations

import math
import numpy as np
from scipy.ndimage import maximum_filter1d

from .common import CONFIG


def intervals(mask):
    start=np.flatnonzero(mask & ~np.r_[False,mask[:-1]])
    end=np.flatnonzero(mask & ~np.r_[mask[1:],False])+1
    return list(zip(start.tolist(),end.tolist()))


def channel(times,weights,duration,clock,centers,window,epsilon):
    p=60/clock['bpm'];phi=clock['phase']%p
    ticks=phi+np.arange(math.ceil(-phi/p),math.ceil((duration-phi)/p))*p
    if not len(ticks):return (np.zeros(len(centers)),)*4
    first=math.ceil(-phi/p);k=np.rint((times-phi)/p).astype(int)-first
    res=times-(phi+(k+first)*p)
    use=(k>=0)&(k<len(ticks))&(abs(res)<=min(.08,p*.25))
    reward=weights[use]*np.exp(-.5*(res[use]/epsilon)**2)
    matching=np.zeros(len(ticks));count=np.zeros(len(ticks))
    np.maximum.at(matching,k[use],reward)
    np.maximum.at(count,k[use],(reward>=.25).astype(float))
    left=np.maximum(0,centers-window/2);right=np.minimum(duration,centers+window/2)
    a,b=np.searchsorted(ticks,left),np.searchsorted(ticks,right)
    cumulative=np.r_[0.,np.cumsum(matching)];nc=np.r_[0.,np.cumsum(count)]
    match=cumulative[b]-cumulative[a]
    coverage=np.divide(match,b-a,out=np.zeros(len(a)),where=b>a)
    mass=np.r_[0.,np.cumsum(weights)];i,j=np.searchsorted(times,left),np.searchsorted(times,right)
    total=mass[j]-mass[i]
    explanation=np.minimum(1.,np.divide(match,total,out=np.zeros(len(total)),where=total>0))
    quality=2*coverage*explanation/np.maximum(coverage+explanation,1e-9)
    return quality,explanation,nc[b]-nc[a],total


def table(events,clocks,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg);duration=float(events['duration'])
    time=np.arange(cfg['step']/2,duration,cfg['step']);n=len(time);k=len(clocks)
    q=np.zeros((n,k),dtype=np.float32);short=np.zeros_like(q);long=np.zeros_like(q)
    explanation=np.zeros_like(q);count=np.zeros_like(q);seed_count=np.zeros_like(q)
    local=np.zeros_like(q);pcm=np.zeros_like(q)
    info=np.zeros(n,dtype=bool)
    for j,h in enumerate(clocks):
        s,e,c,m=channel(events['times'],events['weights'],duration,h,time,cfg['windows'][0],cfg['epsilon'])
        l,_,lc,_=channel(events['times'],events['weights'],duration,h,time,cfg['windows'][1],cfg['epsilon'])
        instant,_,_,_=channel(events['times'],events['weights'],duration,h,time,2.,cfg['epsilon'])
        short[:,j]=s;long[:,j]=l;q[:,j]=.70*s+.30*l
        explanation[:,j]=e;count[:,j]=c;seed_count[:,j]=lc;local[:,j]=instant
        info |= m>=cfg['information_mass']
        pc,_,_,_=channel(events['pcm_times'],events['pcm_weights'],duration,h,time,cfg['windows'][0],.035)
        pcm[:,j]=pc
    return {'time':time,'quality':q,'short_quality':short,'long_quality':long,
            'explanation':explanation,'count':count,'seed_count':seed_count,
            'local_quality':local,'pcm':pcm,'information':info,
            'duration':duration,'clocks':clocks}


def seed_episodes(tab,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg);result=[];dt=cfg['step'];time=tab['time']
    for j,h in enumerate(tab['clocks']):
        strong=(tab['quality'][:,j]>=cfg['quality_threshold']) & (tab['seed_count'][:,j]>=cfg['minimum_seed_quarters'])
        # This is a seed qualification, not a rule for ending a held clock.
        for a,b in intervals(strong):
            if (b-a)*dt+1e-9<cfg['minimum_seed_seconds']:continue
            score=float(np.maximum(tab['quality'][a:b,j]-.45,0).sum()*dt)
            result.append({'clock':j,'start_index':a,'end_index':b,'start':max(0.,float(time[a]-dt/2)),
                           'end':min(tab['duration'],float(time[b-1]+dt/2)),
                           'rank':score,'quality':float(tab['quality'][a:b,j].mean()),
                           'bpm':h['bpm'],'phase':h['phase']})
    return sorted(result,key=lambda e:(-e['rank'],-e['quality'],e['start'],e['clock']))


def refine_episodes(events,tab,cfg=None):
    from .proposals import regression,unique_clocks
    cfg=dict(CONFIG if cfg is None else cfg);extra=[]
    for e in seed_episodes(tab,cfg)[:128]:
        a,b=np.searchsorted(events['times'],[e['start'],e['end']])
        h=tab['clocks'][e['clock']]
        fit=regression(events['times'][a:b],events['weights'][a:b],60/h['bpm'],h['phase'])
        if fit:extra.append({**fit,'center':(e['start']+e['end'])/2,'span':e['end']-e['start'],
                              'seed_start':e['start'],'seed_end':e['end'],'provenance':'source_episode_refit'})
    # Newly fitted clocks lead the retention order; no reference-defined region.
    return unique_clocks(extra+tab['clocks'],cfg['candidate_budget']),extra
