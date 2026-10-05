"""One association per distinct downbeat/onset peak under each latent clock.

Event-location posteriors cannot reward multiple short bars or group pulses.
Overlapping distinct source maxima remain separate observations. Quarter-event
coordinate assignment stays in the unchanged latent-clock factor.
"""
import numpy as np
from . import bar_structure
from .bar_structure import SUBDIVISION
from .latent_clock import time_at

_ORIGINAL=bar_structure.emissions


def budget_events(channels,dt,t,obs,parameters,background,active):
    from .observations import local_peaks,refined_times
    channels=channels.copy();physical=np.flatnonzero((t>=0)&(t<obs['duration']))
    for i,name in enumerate(('down','onset')):
        p0,p1=background[i],active[i]
        log_odds=np.log(p1/p0)-np.log((1-p1)/(1-p0));intercept=np.log((1-p1)/(1-p0))
        threshold=-intercept/log_odds
        if i==1:
            sub=parameters.get('subdivision_active',.3)
            a=np.log(sub/p0)-np.log((1-sub)/(1-p0));b=np.log((1-sub)/(1-p0))
            threshold=min(threshold,-b/a)
        source=np.clip(obs[name],1e-5,1-1e-5);scale,bias=parameters.get(name+'_calibration',[1.,0.])
        source=1/(1+np.exp(-np.clip(scale*np.log(source/(1-source))+bias,-30,30)))
        peaks=local_peaks(source,threshold)
        retained=np.zeros_like(t)
        if len(physical):
            for peak,time in zip(peaks,refined_times(source,peaks,obs['fps'])):
                if not 0<=time<obs['duration']:continue
                winner=physical[int(np.argmin(abs(t[physical]-time)))]
                value=source[peak]/(1+((t[winner]-time)/.04)**2)
                retained[winner]=max(retained[winner],value)
        channels[i]=retained
    return channels


def emissions(clock,obs,states,parameters):
    end=int(np.ceil(clock[-1,0]*SUBDIVISION-1e-8));guard=max(s['length'] for s in states)
    units=np.arange(-guard,end+guard+1);q=units/SUBDIVISION;t=time_at(clock,q)
    channels=np.stack([np.interp(t,obs['times'],obs[name]) for name in ('down','onset','beat')])
    next_t=time_at(clock,q+1/SUBDIVISION)
    # Exact physical exposure of each quadrature cell, including a partial
    # final audio frame. An unsupported margin must not count as a full cell.
    dt=np.maximum(0.,np.minimum(next_t,obs['duration'])-np.maximum(t,0.))*obs['fps']
    # A source-trained calibration may alter evidence log-odds, never clocks.
    for i,name in enumerate(('down','onset','beat')):
        p=np.clip(channels[i],1e-5,1-1e-5)
        a,b=parameters.get(name+'_calibration',[1.,0.])
        channels[i]=1/(1+np.exp(-np.clip(a*np.log(p/(1-p))+b,-30,30)))
    bg=np.array(parameters.get('background',[.025,.06,.06]))
    active=np.array(parameters.get('active',[.8,.65,.65]))
    channels=budget_events(channels,dt,t,obs,parameters,bg,active)
    event_exposure=((t>=0)&(t<obs['duration'])).astype(float)
    # Riff phase is inferred from this source, independently of bar length.
    riff_period=14  # seven sixteenth notes in the 1/8-quarter lattice
    riff_phases=[]
    for phase in range(riff_period):
        selected=(units-phase)%riff_period==0
        ratio=np.log(active[1]/bg[1])-np.log((1-active[1])/(1-bg[1]))
        base=np.log((1-active[1])/(1-bg[1]))
        riff_phases.append(float(np.sum(event_exposure[selected]*(channels[1,selected]*ratio+base))))
    riff_phase=int(np.argmax(riff_phases))
    riff_cells=(units-riff_phase)%riff_period==0
    riff_ratio=np.log(active[1]/bg[1])-np.log((1-active[1])/(1-bg[1]))
    riff_base=np.log((1-active[1])/(1-bg[1]))
    riff_field=event_exposure*(channels[1]*riff_ratio+riff_base)*riff_cells
    riff_prefix=np.r_[0.,np.cumsum(riff_field)]
    start_cells=np.arange(-guard,end+1)
    scores=np.zeros((len(start_cells),len(states)))
    for j,state in enumerate(states):
        length=state['length'];n,d=state['n'],state['d']
        kernel=np.tile(bg[:,None],(1,length))
        groupq=np.cumsum([0,*state['group'][:-1]])*4/d
        patternq=groupq.copy()
        if state['rhythm']=='rest':patternq=np.array([])
        elif state['rhythm']=='half_time':patternq=patternq[::2]
        elif state['rhythm']=='duple_subdivision':
            patternq=np.arange(0,length/SUBDIVISION,2/d)
        elif state['rhythm']=='syncopated':
            patternq=np.array([0.,1.5,3.]) if (n,d)==(4,4) else np.unique(np.r_[0,(patternq[1:]+.5)%(length/SUBDIVISION)])
        for channel,positions in [(0,np.array([0.])),(1,patternq)]:
            for position in positions:
                cell=round(position*SUBDIVISION)
                if 0<=cell<length:kernel[channel,cell]=active[channel]
        if state['rhythm'] not in ('rest','sparse_groups','riff_7_16','syncopated'):
            # Written units within additive/compound groups, and duple rhythm
            # subdivisions, are weaker observations than nominal group starts.
            written=np.arange(0,length/SUBDIVISION,4/d)
            if state['rhythm']=='duple_subdivision':written=patternq
            kernel[1,:]=bg[1]
            for position in written:
                cell=round(position*SUBDIVISION)
                if cell>=length:continue
                strong=any(abs(position-g)<1e-8 for g in patternq) and state['rhythm']!='duple_subdivision'
                if state['rhythm']=='duple_subdivision':strong=any(abs(position-g)<1e-8 for g in groupq)
                value=active[1] if strong else parameters.get('subdivision_active',.3)
                kernel[1,cell]=max(kernel[1,cell],value)
        # Quarter-event likelihood belongs to the clock factor. Group pulses
        # are not forced to coincide with Beat This quarter observations.
        # Correlation computes the complete per-interval Bernoulli likelihood
        # relative to one shared background; no per-bar reward normalization.
        a=np.log(kernel/bg[:,None])-np.log((1-kernel)/(1-bg[:,None]))
        b=np.log((1-kernel)/(1-bg[:,None]))
        value=np.zeros(len(start_cells))
        for c in range(3):
            channel_value=np.zeros(len(start_cells))
            for k in np.flatnonzero(abs(a[c])+abs(b[c])>1e-12):
                index=start_cells+guard+k
                contribution=(event_exposure[index] if c<2 else dt[index])*(channels[c,index]*a[c,k]+b[c,k])
                if c==1 and state['rhythm']=='riff_7_16':contribution=np.where(riff_cells[index],0.,contribution)
                channel_value+=contribution
            if c==0 and state['visibility']=='weak':
                # Persistent weak-observation state: retain bars across runs of
                # missing downbeats, instead of paying independently per miss.
                if state['rhythm']=='rest':
                    # A silent grid has no downbeat observability; preserve its
                    # inherited meter without rewarding fewer guessed bars.
                    channel_value[:]=-parameters.get('weak_quarter_cost',.12)*length/SUBDIVISION
                else:
                    channel_value[:]=parameters.get('weak_temperature',.1)*channel_value-parameters.get('weak_bar_cost',.48)
            value+=channel_value
        if state['rhythm']=='riff_7_16':
            index=start_cells+guard
            value+=riff_prefix[index+length]-riff_prefix[index]
        if state['rhythm']=='rest':
            # Rest is an acoustic explanation, not a free pattern capable of
            # hiding active beat evidence. Score it on the same source frames.
            rest_p=.02;beat_bg=bg[2]
            rest_a=np.log(rest_p/beat_bg)-np.log((1-rest_p)/(1-beat_bg))
            rest_b=np.log((1-rest_p)/(1-beat_bg))
            acoustic=np.interp(t,obs['times'],obs.get('acoustic_beat',obs['beat']))
            rest_evidence=dt*(acoustic*rest_a+rest_b)
            prefix=np.r_[0.,np.cumsum(rest_evidence)]
            index=start_cells+guard
            value+=prefix[index+length]-prefix[index]
        # Fixed grammar complexity: free grouping/pattern choices have a cost.
        # This coefficient is selected only by held-out control/learning data.
        complexity=parameters.get('pattern_cost',.03)*(state['rhythm']!='regular')
        complexity+=parameters.get('group_cost',.01)*max(0,len(state['group'])-1)
        scores[:,j]=value-complexity
    return scores,dict(end=end,guard=guard,start_cells=start_cells,times=t,dt=dt)



def install():
    if bar_structure.emissions is emissions:return
    if bar_structure.emissions is not _ORIGINAL:raise ValueError('unexpected structure score adapter')
    bar_structure.emissions=emissions
    from . import fast_structure,analyzer
    from .capacity_vocabulary import vocabulary
    fast_structure.vocabulary=vocabulary
    bar_structure.vocabulary=vocabulary
    fast_structure.emissions=emissions
    from .capacity_support import decode
    analyzer.decode=decode
    from .capacity_fit import fit
    analyzer.fit=fit
    from .capacity_objective import install_objective
    install_objective()
    bar_structure.decode=fast_structure.decode
    from .learned_support import infer
    analyzer.infer_support=infer
