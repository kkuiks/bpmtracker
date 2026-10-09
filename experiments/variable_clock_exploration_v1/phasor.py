"""Local physical periodicity before assigning event sequence coordinates.

All rational rates compete locally. Phase comes from weighted event phasors;
missing-event indices are fitted separately for each hypothesis. This contrasts
with the other experiment arms' single locally counted event coordinate axis.
"""
import math

import numpy as np

from experiments.metronome_reconstruction_v1.grid import rational_pool


def witnesses(t,w,duration,sigma):
    from .clock import fit_line
    rates=np.array([float(r) for r in rational_pool(30,400,4)])
    periods=60/rates;centers=np.arange(.25,duration,.5)
    candidates=[[] for _ in centers];total=np.r_[0.,np.cumsum(w)]
    for span in (2,4,8,16,32,64):
        left=np.maximum(0,centers-span/2);right=np.minimum(duration,centers+span/2)
        first=np.searchsorted(t,left);last=np.searchsorted(t,right)
        mass=total[last]-total[first];width=right-left
        scores=np.zeros((len(rates),len(centers)));phases=np.zeros_like(scores)
        for a in range(0,len(rates),128):
            frequency=rates[a:a+128]/60
            z=np.exp(2j*np.pi*frequency[:,None]*t[None,:])*w[None,:]
            prefix=np.column_stack((np.zeros(len(frequency)),np.cumsum(z,axis=1)))
            local=prefix[:,last]-prefix[:,first]
            coherence=abs(local)/np.maximum(mass[None,:],1e-10)
            density=np.minimum(1,mass[None,:]*periods[a:a+128,None]/np.maximum(width[None,:],.01))
            scores[a:a+128]=coherence*np.sqrt(density)
            phases[a:a+128]=(np.angle(local)/(2*np.pi*frequency[:,None]))%periods[a:a+128,None]
        for i,center in enumerate(centers):
            a,b=first[i],last[i]
            if b-a<4:continue
            ranked=np.argsort(scores[:,i])[::-1];seeds=[]
            for k in ranked:
                if scores[k,i]<.2:break
                if any(abs(rates[k]-rates[j])<max(2,30/span) for j in seeds):continue
                seeds.append(k)
                if len(seeds)==4:break
            local_t,local_w=t[a:b],w[a:b]
            for k in seeds:
                p,origin=periods[k],phases[k,i]
                fit=None
                for _ in range(3):
                    n=np.rint((local_t-origin)/p)
                    error=local_t-(origin+n*p)
                    use=abs(error)<=min(.08,p*.25)
                    # Capacity one per lattice tick, before fitting the clock.
                    options=np.flatnonzero(use)
                    order=np.lexsort((abs(error[options])/np.maximum(local_w[options],.01),n[options]))
                    ordered=options[order]
                    selected=ordered[np.r_[True,np.diff(n[ordered])!=0]] if len(ordered) else ordered
                    if len(selected)<4:fit=None;break
                    fit=fit_line(n[selected],local_t[selected],local_w[selected])
                    if fit is None:break
                    p,origin=fit['period'],fit['origin']
                if fit is None:continue
                explained=float(local_w[selected].sum()/max(local_w.sum(),1e-10))
                expected=(right[i]-left[i])/p
                coverage=float(min(1,local_w[selected].sum()/max(expected,1)))
                quality=2*coverage*explained/max(coverage+explained,1e-10)
                quality*=math.exp(-.5*(fit['rms']/max(sigma,.02))**2)
                if fit['rms']<=1.8*sigma and quality>=.35:
                    candidates[i].append({**fit,'quality':quality,'span':span,
                                          'first_event':float(local_t[selected[0]]),
                                          'last_event':float(local_t[selected[-1]])})
    selected=[];alternatives=[]
    for center,choices in zip(centers,candidates):
        if not choices:continue
        # Long, internally coherent witnesses rank ahead of tiny permissive fits.
        fit=max(choices,key=lambda r:r['quality']*math.sqrt(min(r['events'],64)))
        uncertainty=max(fit['slope_error']/fit['period'],.001)
        selected.append((center,math.log(fit['period']),min(1/uncertainty**2,1e6),fit))
        unique=[]
        for option in sorted(choices,key=lambda r:r['quality'],reverse=True):
            if any(abs(option['bpm']-r['bpm'])<1e-8 for r in unique):continue
            unique.append(option)
            if len(unique)==5:break
        alternatives.append({'time':float(center),'clocks':[{'bpm':r['bpm'],'phase':r['nominal_phase'],
                                                             'quality':r['quality']} for r in unique]})
    return selected,alternatives


def regions(t,w,duration,sigma,penalty):
    from .clock import constant_partition, fit_line
    selected,alternatives=witnesses(t,w,duration,sigma)
    if len(selected)<3:return [],{'phase_bank_supported_centers':len(selected)},alternatives
    values=np.array([r[1] for r in selected]);weights=np.array([r[2] for r in selected])
    blocks=constant_partition(values,weights,penalty,3);result=[]
    for a,b in blocks:
        start=0. if a==0 else (selected[a-1][0]+selected[a][0])/2
        end=duration if b==len(selected) else (selected[b-1][0]+selected[b][0])/2
        first,last=np.searchsorted(t,[start,end]);local_t,local_w=t[first:last],w[first:last]
        if len(local_t)<4:continue
        seed=selected[(a+b)//2][3];p,origin=seed['period'],seed['origin']
        fit=None
        for _ in range(3):
            n=np.rint((local_t-origin)/p);residual=local_t-origin-n*p
            use=abs(residual)<=min(.08,p*.25)
            if use.sum()<4:fit=None;break
            fit=fit_line(n[use],local_t[use],local_w[use])
            if fit is None:break
            p,origin=fit['period'],fit['origin']
        if fit:
            result.append({**fit,'start':float(start),'end':float(end),
                           'first_event':float(local_t[use][0]),'last_event':float(local_t[use][-1]),
                           'event_start_index':int(first),'event_end_index':int(last),
                           'independent_event_coordinates':True})
    return result,{'phase_bank_supported_centers':len(selected),'rational_rates_tested_per_window':2221,
                    'single_event_axis_used_to_propose':False},alternatives
