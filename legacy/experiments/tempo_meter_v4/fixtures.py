"""Controlled observations with clock, meter and rhythmic changes separated."""
import numpy as np
from .latent_clock import time_at


def fixture(signatures,*,period=.5,tempo_changes=(),half_time=False,missing_bars=(),rest=None,accent_332=False,riff=False,delay=0.,seed=1):
    rng=np.random.default_rng(seed)
    starts=np.r_[0.,np.cumsum([4*n/d for n,d in signatures])]
    knots=[[0.,.3]];last=0.;rate=period
    for q,newperiod in tempo_changes:
        knots.append([q,knots[-1][1]+(q-last)*rate]);last=q;rate=newperiod
    knots.append([starts[-1],knots[-1][1]+(starts[-1]-last)*rate])
    clock=np.array(knots);duration=clock[-1,1];t=np.arange(int(np.ceil(duration*50)))/50
    beat=np.full(len(t),.005);down=beat.copy();onset=beat.copy();energy=np.full(len(t),.2)
    def add(values,when,height):
        values[:]=np.maximum(values,.005+height*np.exp(-.5*((t-when)/.020)**2))
    for q in np.arange(0,starts[-1]+1e-8,.5):
        when=float(time_at(clock,q))+delay
        if rest and rest[0]<=q<rest[1]:continue
        amplitude=.9 if q==round(q) else .15
        if half_time and starts[-1]/3<q<2*starts[-1]/3 and int(q)%2:amplitude*=.25
        add(beat,when,amplitude)
    bars=[]
    for i,(n,d) in enumerate(signatures):
        group=[3]*(n//3) if d==8 and n%3==0 else ([2]*((n-3)//2)+[3] if d==8 and n>=5 and n%2 else [1]*n)
        bars.append(dict(q=float(starts[i]),n=n,d=d,grouping=group,rhythm='regular'))
        if i not in missing_bars and not (rest and rest[0]<=starts[i]<rest[1]):add(down,float(time_at(clock,starts[i]))+delay,.99)
        offsets=np.array([0.,1.5,3.]) if accent_332 and len(signatures)/3<i<2*len(signatures)/3 and (n,d)==(4,4) else np.cumsum([0,*group[:-1]])*4/d
        for q in offsets+starts[i]:
            if rest and rest[0]<=q<rest[1]:continue
            add(onset,float(time_at(clock,q))+delay,.95)
    if riff:
        for q in np.arange(0,starts[-1],1.75):add(onset,float(time_at(clock,q))+delay,.95)
    from .observations import local_peaks,refined_times
    ix=np.unique(np.r_[local_peaks(beat,.2),local_peaks(down,.2)])
    logits=np.column_stack([np.log(np.clip(x,1e-5,1-1e-5)/(1-np.clip(x,1e-5,1-1e-5))) for x in (beat,down)])
    obs=dict(times=t,fps=50.,duration=duration,beat=beat,down=down,onset=onset,energy=energy,
             events=refined_times(np.maximum(beat,down),ix,50.),event_strength=beat[ix],event_down=down[ix],logits=logits,features=None)
    return obs,clock,bars
