"""Same conditional two-best DP; precompute length-only sparse repeat factors."""
import numpy as np
from .bar_structure import vocabulary,emissions,score_path,SUBDIVISION

def decode(clock,obs,parameters=None,*,states=None,repeat_targets=None):
    """Exact two-best conditional bar paths; continuous-clock search is bounded."""
    parameters={} if parameters is None else parameters
    states=vocabulary() if states is None else tuple(states)
    scores,meta=emissions(clock,obs,states,parameters)
    lengths=np.array([s['length'] for s in states],int)
    end,guard=meta['end'],meta['guard'];total=end+guard+1;count=len(states)
    ranks=2
    if count*ranks>=32767:raise ValueError('parent index exceeds int16')
    dp=np.full((total,count,ranks),-np.inf);parents=np.full((total,count,ranks),-1,np.int16)
    best=np.full((total,ranks),-np.inf);best_state=np.full((total,ranks),-1,int)
    keys=list(dict.fromkeys((s['n'],s['d'],s['group']) for s in states))
    group_index=np.array([keys.index((s['n'],s['d'],s['group'])) for s in states])
    indexes=[np.flatnonzero(group_index==i) for i in range(len(keys))]
    width=len(indexes[0]);uniform=all(len(ix)==width for ix in indexes)
    group_best=np.full((total,len(keys),ranks),-np.inf);group_state=np.full((total,len(keys),ranks),-1,int)
    change_cost=parameters.get('meter_change_cost',4.);rhythm_cost=parameters.get('rhythm_change_cost',1.)
    trace=np.arange(count);rows=trace
    repeat_penalties=None
    if repeat_targets is not None:
        unique_lengths=np.unique(lengths);length_ids=np.searchsorted(unique_lengths,lengths)
        repeat_penalties=np.zeros((len(meta['start_cells']),len(unique_lengths)))
        rq,rphase,rweight=repeat_targets
        for q0,phase,weight in zip(rq,rphase,rweight):
            upper=int(np.floor(q0*SUBDIVISION))
            for i,length in enumerate(unique_lengths):
                starts=np.arange(max(-guard,upper+1-length),min(end,upper)+1)
                if not len(starts):continue
                predicted=(q0-starts/SUBDIVISION)/(length/SUBDIVISION)
                distance=abs(predicted-phase);distance=np.minimum(distance,1-distance)
                repeat_penalties[starts+guard,i]+=parameters.get('repeat_strength',.1)*weight*distance
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
        if parameters.get('quarter_origin_consistent',False):
            value[(starts<=0)&(starts%SUBDIVISION!=0)]=-np.inf
        if repeat_penalties is not None:
            value-=repeat_penalties[np.clip(starts+guard,0,len(repeat_penalties)-1),length_ids,None]
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

