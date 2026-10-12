"""Source-local clock fits at all rational rates, with spatial retention."""
from __future__ import annotations

import math
import numpy as np

from experiments.metronome_reconstruction_v1.grid import rational_pool
from experiments.variable_tempo_interval_consensus_v0.core import quantize
from .common import CONFIG


def load_events(path):
    with np.load(path,allow_pickle=False) as d:return {k:d[k].copy() for k in d.files}


def unique_clocks(rows,budget):
    kept={}
    for h in rows:
        b=float(h['bpm']);p=60/b;phi=float(h['phase'])%p
        if not 30<=b<=400:continue
        key=(b,round(phi/.006))
        if key not in kept:kept[key]={**h,'bpm':b,'phase':phi,'key':f'{b:.12g}:{phi.hex()}'}
    return list(kept.values())[:budget]


def regression(t,w,p,phase,refine_rate=True):
    original=p
    for _ in range(3):
        k=np.rint((t-phase)/p);res=t-(phase+k*p)
        use=np.flatnonzero(abs(res)<=min(.08,p*.25))
        if len(use)<5:return None
        order=np.lexsort((abs(res[use])/np.maximum(w[use],.01),k[use]));use=use[order]
        use=use[np.r_[True,np.diff(k[use])!=0]]
        if len(use)<5:return None
        x=k[use];y=t[use];v=w[use];xm=np.average(x,weights=v);ym=np.average(y,weights=v)
        if refine_rate:
            spread=float(np.sum(v*(x-xm)**2))
            if spread<=0:return None
            fitted=float(np.sum(v*(x-xm)*(y-ym))/spread)
            if fitted<=0 or abs(fitted/original-1)>.06:return None
            p=fitted
        phase=float(np.average(y-x*p,weights=v))
    b=quantize(60/p);p=60/b
    phase=float(np.average(y-x*p,weights=v))
    error=y-(phase+x*p);rms=float(np.sqrt(np.average(error**2,weights=v)))
    explained=float(v.sum()/max(w.sum(),1e-9))
    coverage=min(1.,float(v.sum()/max((t[-1]-t[0])/p+1,1)))
    quality=2*coverage*explained/max(coverage+explained,1e-9)*math.exp(-.5*(rms/.03)**2)
    if rms>.05 or quality<.30:return None
    return {'bpm':b,'phase':phase%p,'source_quality':quality,'events':len(use),'rms':rms,
            'first_event':float(y.min()),'last_event':float(y.max())}


def generate(events,final=None,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg)
    t,w=events['times'],events['weights'];duration=float(events['duration'])
    if len(t)<cfg['proposal_min_events']:return {'expanded':[],'unrefined':[],'final':final or [],'statistics':{'events':len(t)}}
    rates=np.array([float(r) for r in rational_pool(30,400,4)]);periods=60/rates
    centers=np.arange(1.,duration,cfg['proposal_step'])
    if not len(centers):centers=np.array([duration/2])
    candidates=[[] for _ in centers];raw=[[] for _ in centers]
    windows=[];mass=np.r_[0.,np.cumsum(w)]
    for span in cfg['proposal_spans']:
        a=np.searchsorted(t,np.maximum(0,centers-span/2));b=np.searchsorted(t,np.minimum(duration,centers+span/2))
        width=np.minimum(duration,centers+span/2)-np.maximum(0,centers-span/2)
        windows.append((span,a,b,width,mass[b]-mass[a],np.zeros((len(rates),len(centers))),
                        np.zeros((len(rates),len(centers)))))
    # Compute each frequency's prefix once, then query all window sizes.
    for first in range(0,len(rates),128):
        rr=rates[first:first+128];p=60/rr
        z=np.exp(2j*np.pi*(rr[:,None]/60)*t[None,:])*w[None,:]
        prefix=np.c_[np.zeros(len(rr)),np.cumsum(z,axis=1)]
        for span,a,b,width,m,quality,phase in windows:
            v=prefix[:,b]-prefix[:,a]
            coherence=abs(v)/np.maximum(m[None,:],1e-9)
            exposure=np.minimum(1,m[None,:]*p[:,None]/np.maximum(width[None,:],.01))
            quality[first:first+len(rr)]=coherence*np.sqrt(exposure)
            phase[first:first+len(rr)]=(np.angle(v)*p[:,None]/(2*np.pi))%p[:,None]
    for span,a,b,width,m,scores,phases in windows:
        for i,center in enumerate(centers):
            if b[i]-a[i]<cfg['proposal_min_events']:continue
            seeds=[]
            for j in np.argsort(scores[:,i])[::-1]:
                if scores[j,i]<.30:break
                if any(abs(rates[j]-rates[k])<max(1.,20/span) for k in seeds):continue
                seeds.append(j)
                if len(seeds)>=cfg['proposal_rates_per_window']:break
            for j in seeds:
                h={'bpm':float(rates[j]),'phase':float(phases[j,i]),'source_quality':float(scores[j,i]),
                   'span':span,'center':float(center),'seed_start':max(0.,float(center-span/2)),
                   'seed_end':min(duration,float(center+span/2)),'events':int(b[i]-a[i]),
                   'provenance':'local_phasor_unrefined'}
                raw[i].append(h)
                fit=regression(t[a[i]:b[i]],w[a[i]:b[i]],periods[j],phases[j,i])
                if fit:
                    candidates[i].append({**h,**fit,'provenance':'local_source_regression'})
    def retain(by_center,extra):
        for rows in by_center:
            rows.sort(key=lambda h:h['source_quality']*math.sqrt(min(h['events'],128)),reverse=True)
        ordered=[]
        for depth in range(max((len(r) for r in by_center),default=0)):
            choices=[rows[depth] for rows in by_center if len(rows)>depth]
            choices.sort(key=lambda h:h['source_quality']*math.sqrt(min(h['events'],128)),reverse=True)
            ordered.extend(choices)
        # A common 512-clock final bank is retained as a comparator and as extra
        # proposals; it never restricts local rates to its whole-song family.
        primary=unique_clocks(ordered,cfg['candidate_budget'])
        spare=max(0,cfg['candidate_budget']-len(primary))
        return unique_clocks(primary+list(extra or [])[:spare],cfg['candidate_budget'])
    return {'expanded':retain(candidates,final),'unrefined':retain(raw,final),
            'final':unique_clocks(final or [],512),
            'statistics':{'events':len(t),'rates_per_window':len(rates),'centers':len(centers),
                          'raw_fits':sum(map(len,candidates)),'budget':cfg['candidate_budget'],
                          'source_only':True,'references_used':False}}
