"""Semi-Markov bar/group/rhythm paths on competing latent clocks.

The likelihood explains the whole source span. Numerator and denominator are
not independently classified. Alternative rhythm patterns do not change meter.
"""
from functools import lru_cache
import numpy as np
from .latent_clock import time_at

SUBDIVISION=8


@lru_cache(None)
def vocabulary():
    states=[]
    for d in (2,4,8,16,32):
        for n in range(1,33):
            groups=[tuple([1]*n)]
            if d>=8 and n%3==0:groups.append(tuple([3]*(n//3)))
            if d>=4 and n>=5 and n%2:
                a=tuple([2]*((n-3)//2)+[3])
                groups.extend([a,a[-1:]+a[:-1]])
            if d>=8 and n>=6 and n%2==0:
                additive=tuple([3,3]+[2]*((n-6)//2))
                groups.extend([additive,additive[-1:]+additive[:-1]])
            for group in dict.fromkeys(groups):
                for rhythm in ('regular','half_time','syncopated','riff_7_16','rest'):
                    for visibility in ('observed','weak'):
                        states.append(dict(n=n,d=d,group=group,rhythm=rhythm,visibility=visibility,length=round(4*n/d*SUBDIVISION)))
    return tuple(states)


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
    # Riff phase is inferred from this source, independently of bar length.
    riff_period=14  # seven sixteenth notes in the 1/8-quarter lattice
    riff_phases=[]
    for phase in range(riff_period):
        selected=(units-phase)%riff_period==0
        ratio=np.log(active[1]/bg[1])-np.log((1-active[1])/(1-bg[1]))
        base=np.log((1-active[1])/(1-bg[1]))
        riff_phases.append(float(np.sum(dt[selected]*(channels[1,selected]*ratio+base))))
    riff_phase=int(np.argmax(riff_phases))
    riff_cells=(units-riff_phase)%riff_period==0
    riff_ratio=np.log(active[1]/bg[1])-np.log((1-active[1])/(1-bg[1]))
    riff_base=np.log((1-active[1])/(1-bg[1]))
    riff_field=dt*(channels[1]*riff_ratio+riff_base)*riff_cells
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
        elif state['rhythm']=='syncopated':
            patternq=np.array([0.,1.5,3.]) if (n,d)==(4,4) else np.unique(np.r_[0,(patternq[1:]+.5)%(length/SUBDIVISION)])
        for channel,positions in [(0,np.array([0.])),(1,patternq)]:
            for position in positions:
                cell=round(position*SUBDIVISION)
                if 0<=cell<length:kernel[channel,cell]=active[channel]
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
                contribution=dt[index]*(channels[c,index]*a[c,k]+b[c,k])
                if c==1 and state['rhythm']=='riff_7_16':contribution=np.where(riff_cells[index],0.,contribution)
                channel_value+=contribution
            if c==0 and state['visibility']=='weak':
                # Persistent weak-observation state: retain bars across runs of
                # missing downbeats, instead of paying independently per miss.
                channel_value[:]=-parameters.get('weak_quarter_cost',.12)*length/SUBDIVISION
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
            rest_evidence=dt*(channels[2]*rest_a+rest_b)
            prefix=np.r_[0.,np.cumsum(rest_evidence)]
            index=start_cells+guard
            value+=prefix[index+length]-prefix[index]
        # Fixed grammar complexity: free grouping/pattern choices have a cost.
        # This coefficient is selected only by held-out control/learning data.
        complexity=parameters.get('pattern_cost',.03)*(state['rhythm']!='regular')
        complexity+=parameters.get('group_cost',.01)*max(0,len(state['group'])-1)
        scores[:,j]=value-complexity
    return scores,dict(end=end,guard=guard,start_cells=start_cells,times=t,dt=dt)


def decode(clock,obs,parameters=None,*,states=None,repeat_targets=None):
    """Exact two-best conditional bar paths; continuous-clock search is bounded."""
    parameters={} if parameters is None else parameters
    states=vocabulary() if states is None else tuple(states)
    scores,meta=emissions(clock,obs,states,parameters)
    lengths=np.array([s['length'] for s in states],int)
    end,guard=meta['end'],meta['guard'];total=end+guard+1;count=len(states)
    ranks=2
    dp=np.full((total,count,ranks),-np.inf);parents=np.full((total,count,ranks),-1,np.int32)
    best=np.full((total,ranks),-np.inf);best_state=np.full((total,ranks),-1,int)
    keys=list(dict.fromkeys((s['n'],s['d'],s['group']) for s in states))
    group_index=np.array([keys.index((s['n'],s['d'],s['group'])) for s in states])
    indexes=[np.flatnonzero(group_index==i) for i in range(len(keys))]
    width=len(indexes[0]);uniform=all(len(ix)==width for ix in indexes)
    group_best=np.full((total,len(keys),ranks),-np.inf);group_state=np.full((total,len(keys),ranks),-1,int)
    change_cost=parameters.get('meter_change_cost',4.);rhythm_cost=parameters.get('rhythm_change_cost',1.)
    trace=np.arange(count);rows=trace
    for stop in range(1,total):
        starts=stop-lengths;nonnegative=np.maximum(0,starts)
        choices=np.concatenate([dp[nonnegative,trace,:],group_best[nonnegative,group_index,:]-rhythm_cost,
                                best[nonnegative,:]-change_cost],axis=1)
        same_parents=np.column_stack([trace*ranks,trace*ranks+1])
        candidates=np.concatenate([same_parents,group_state[nonnegative,group_index,:],best_state[nonnegative,:]],axis=1)
        first=np.argmax(choices,axis=1);first_parent=candidates[rows,first]
        next_scores=np.where(candidates!=first_parent[:,None],choices,-np.inf)
        second=np.argmax(next_scores,axis=1)
        prior=np.column_stack([choices[rows,first],next_scores[rows,second]])
        previous=np.column_stack([first_parent,candidates[rows,second]])
        initial=starts<=0;prior[initial,0]=0.;prior[initial,1]=-np.inf;previous[initial]=-1
        value=prior+scores[np.clip(starts+guard,0,len(scores)-1),trace,None]
        if repeat_targets is not None:
            rq,rphase,rweight=repeat_targets
            for q0,phase,weight in zip(rq,rphase,rweight):
                inside=(starts/ SUBDIVISION<=q0)&(stop/SUBDIVISION>q0)
                predicted=(q0-starts/SUBDIVISION)/(lengths/SUBDIVISION)
                distance=abs(predicted-phase);distance=np.minimum(distance,1-distance)
                value-=parameters.get('repeat_strength',.1)*weight*distance[:,None]*inside[:,None]
        if stop>end:value[starts>=end]=-np.inf
        dp[stop]=value;parents[stop]=previous
        global_order=np.argsort(value.ravel())[-ranks:][::-1]
        best[stop]=value.ravel()[global_order];best_state[stop]=global_order
        if uniform:
            grouped=value.reshape(len(keys),width*ranks)
            order=np.argsort(grouped,axis=1)[:,-ranks:][:,::-1]
            group_best[stop]=np.take_along_axis(grouped,order,axis=1)
            group_state[stop]=np.arange(len(keys))[:,None]*width*ranks+order
        else:
            for i,ix in enumerate(indexes):
                v=value[ix].ravel();order=np.argsort(v)[-ranks:][::-1]
                group_best[stop,i]=v[order];group_state[stop,i]=ix[order//ranks]*ranks+order%ranks
    terminal_scores=dp[end:].reshape(-1)
    available=np.flatnonzero(np.isfinite(terminal_scores))
    winners=available[np.argsort(terminal_scores[available])[-min(16,len(available)):][::-1]]
    results=[];seen=set()
    for winner in winners:
        terminal=end+int(winner//(count*ranks));encoded=int(winner%(count*ranks));stop=terminal;bars=[];base_score=0.;encoded_states=[]
        while stop>0 and encoded>=0:
            state,rank=divmod(encoded,ranks);start=stop-int(lengths[state]);s=states[state]
            bars.append(dict(q=start/SUBDIVISION,n=s['n'],d=s['d'],grouping=list(s['group']),rhythm=s['rhythm'],visibility=s['visibility']))
            encoded_states.append(state)
            encoded=int(parents[stop,state,rank]);stop=start
        bars.reverse();encoded_states.reverse()
        identity=tuple((b['q'],b['n'],b['d'],tuple(b['grouping']),b['rhythm'],b['visibility']) for b in bars)
        if identity in seen:continue
        seen.add(identity);previous=None
        for bar,j in zip(bars,encoded_states):
            key=(bar['n'],bar['d'],tuple(bar['grouping']),bar['rhythm'],bar['visibility'])
            base_score+=scores[round(bar['q']*SUBDIVISION)+guard,j]
            if previous is not None:
                if key[:3]!=previous[:3]:base_score-=change_cost
                elif key[3:]!=previous[3:]:base_score-=rhythm_cost
            previous=key
        results.append(dict(bars=bars,score=float(terminal_scores[winner]),base_score=float(base_score),
                            states=len(states),terminal_quarter=terminal/SUBDIVISION,k_best=ranks))
        if len(results)==ranks:break
    if not results:raise ValueError('no terminal bar paths')
    primary=results[0];primary['alternatives']=results[1:]
    return primary


def score_path(clock,obs,bars,parameters=None,states=None):
    parameters={} if parameters is None else parameters
    states=vocabulary() if states is None else tuple(states)
    scores,meta=emissions(clock,obs,states,parameters)
    lookup={(s['n'],s['d'],s['group'],s['rhythm'],s['visibility']):i for i,s in enumerate(states)}
    total=0.;previous=None;last=None
    for bar in bars:
        key=(bar['n'],bar['d'],tuple(bar['grouping']),bar['rhythm'],bar.get('visibility','observed'));state=lookup[key]
        start=round(bar['q']*SUBDIVISION)
        if abs(start-bar['q']*SUBDIVISION)>1e-5:raise ValueError('off-lattice bar')
        if last is not None and start!=last:raise ValueError('discontinuous bars')
        if previous is not None:
            if key[:3]!=previous[:3]:total-=parameters.get('meter_change_cost',4.)
            elif key[3:]!=previous[3:]:total-=parameters.get('rhythm_change_cost',1.)
        total+=scores[start+meta['guard'],state]
        previous=key;last=start+states[state]['length']
    return float(total)
