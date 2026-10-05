"""Exact manufactured event targets; noisy/censored old fixtures stay preserved."""
import numpy as np
from .fixtures import fixture as noisy_fixture
from .latent_clock import time_at
from .observations import local_peaks,refined_times


def fixture(signatures,**kwargs):
    obs,clock,bars=noisy_fixture(signatures,**kwargs)
    t=obs['times'];start=np.r_[0.,np.cumsum([4*n/d for n,d in signatures])]
    fields={name:np.zeros(len(t)) for name in ['beat','down','onset']}
    delay=kwargs.get('delay',0.)
    def add(name,when,height):
        fields[name]=np.maximum(fields[name],height*np.exp(-.5*((t-when)/.02)**2))
    rest=kwargs.get('rest');missing=kwargs.get('missing_bars',())
    # Events at the physical source end are OUTSIDE the declared support.
    for q in np.arange(0,start[-1],.5):
        if rest and rest[0]<=q<rest[1]:continue
        height=.9 if q==round(q) else .15
        if kwargs.get('half_time') and start[-1]/3<q<2*start[-1]/3 and int(q)%2:height*=.25
        add('beat',float(time_at(clock,q))+delay,height)
    for i,b in enumerate(bars):
        if i not in missing and not(rest and rest[0]<=b['q']<rest[1]):add('down',float(time_at(clock,b['q']))+delay,.99)
        offsets=np.array([0.,1.5,3.]) if kwargs.get('accent_332') and len(bars)/3<i<2*len(bars)/3 and (b['n'],b['d'])==(4,4) else np.cumsum([0,*b['grouping'][:-1]])*4/b['d']
        for q in offsets+b['q']:
            if rest and rest[0]<=q<rest[1]:continue
            add('onset',float(time_at(clock,q))+delay,.95)
    if kwargs.get('riff'):
        for q in np.arange(0,start[-1],1.75):add('onset',float(time_at(clock,q))+delay,.95)
    obs.update(fields)
    ix=np.unique(np.r_[local_peaks(obs['beat'],.2),local_peaks(obs['down'],.2)])
    obs.update(events=refined_times(np.maximum(obs['beat'],obs['down']),ix,50),event_strength=obs['beat'][ix],event_down=obs['down'][ix])
    return obs,clock,bars
