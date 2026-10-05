"""Bounded alternating event-coordinate / clock / meter reconstruction.

No reference or identity input. Observed events may be skipped and quarter
coordinates may have gaps. Bar associations participate in clock refitting.
This local optimizer is an experimental hypothesis, not global joint inference.
"""
import numpy as np
from .meter_event import decode_meter,interpolate
from .clock_search import sigmoid

SIGMA=.040
MAX_ITERATIONS=3


def peaks(logits,structure):
    times=np.arange(len(logits))/50
    st=np.arange(len(structure['events']))/12.5
    beat=.75*sigmoid(logits[:,0])+.25*np.interp(times,st,sigmoid(structure['events'][:,0]))
    down=.6*logits[:,1]+.4*np.interp(times,st,structure['events'][:,1])
    bp=np.flatnonzero((beat>=.35)&(beat>np.r_[-np.inf,beat[:-1]])&(beat>=np.r_[beat[1:],-np.inf]))
    dp=np.flatnonzero((down>=.8)&(down>np.r_[-np.inf,down[:-1]])&(down>=np.r_[down[1:],-np.inf]))
    return dict(beat_times=times[bp],beat_strength=beat[bp],bar_times=times[dp])


def nearest(values,events):
    if not len(events):return np.zeros(len(values),int),np.full(len(values),np.inf)
    index=np.searchsorted(events,values)
    left=np.clip(index-1,0,len(events)-1);right=np.clip(index,0,len(events)-1)
    choose=np.where(abs(values-events[left])<=abs(values-events[right]),left,right)
    return choose,events[choose]-values


def associations(clock,bars,observed):
    q=np.arange(0,np.floor(clock[-1,0])+1)
    qs=[];ts=[];weights=[];receipt={}
    for kind,positions,scale in [('beat',q,1.),('bar',np.array([b['q'] for b in bars]),.35)]:
        positions=positions[(positions>=0)&(positions<=clock[-1,0])]
        predicted=interpolate(clock,positions)
        events=observed[kind+'_times']
        ids,residual=nearest(predicted,events)
        period=interpolate(clock,positions+.5)-interpolate(clock,positions-.5)
        accepted=np.flatnonzero(abs(residual)<=np.minimum(4*SIGMA,.25*period))
        # A source event cannot pull several model boundaries towards itself.
        by_event={}
        for i in accepted:
            old=by_event.get(int(ids[i]))
            if old is None or abs(residual[i])<abs(residual[old]):by_event[int(ids[i])]=int(i)
        keep=np.array(sorted(by_event.values()),int)
        qs.extend(positions[keep]);ts.extend(events[ids[keep]]);weights.extend([scale]*len(keep))
        receipt[kind]=dict(predicted=len(positions),matched=len(keep),unmatched=len(positions)-len(keep))
    return np.asarray(qs),np.asarray(ts),np.asarray(weights),receipt


def fit_knots(q,t,weight,knots,initial):
    if len(q)<2 or np.ptp(q)<1:return initial.copy()
    index=np.clip(np.searchsorted(knots,q,side='right')-1,0,len(knots)-2)
    fraction=(q-knots[index])/(knots[index+1]-knots[index])
    basis=np.zeros((len(q),len(knots)))
    basis[np.arange(len(q)),index]=1-fraction;basis[np.arange(len(q)),index+1]=fraction
    current=initial.copy()
    for _ in range(4):
        residual=basis@current-t
        robust=np.minimum(1.,SIGMA/np.maximum(abs(residual),1e-9))
        w=weight*robust
        # Tiny numerical anchor resolves an unsupported end knot, not a BPM guide.
        lhs=basis.T@(w[:,None]*basis)+np.eye(len(knots))*1e-8
        rhs=basis.T@(w*t)+1e-8*initial
        current=np.linalg.solve(lhs,rhs)
    if not np.all(np.diff(current)>0):return initial.copy()
    return current


def evaluate(clock,logits,structure,observed):
    meter=decode_meter(clock,logits,structure)
    quarters=np.arange(0,np.floor(clock[-1,0])+1)
    times=interpolate(clock,quarters)
    _,residual=nearest(times,observed['beat_times'])
    normalized=np.minimum(abs(residual)/SIGMA,4.)
    huber=np.where(normalized<=1,.5*normalized**2,normalized-.5)
    # Same quarter count for every refinement of a seed. The complexity term
    # is fixed before real-song scoring; not a selected product threshold.
    complexity=.5*len(clock)*np.log(max(2,len(quarters)))/max(1,len(quarters))
    beat_score=-float(np.mean(huber))-float(complexity)
    score=beat_score+.35*meter['score']
    return dict(clock=clock,meter=meter,score=score,beat_score=beat_score,
                complexity=complexity,mean_capped_timing_loss=float(np.mean(huber)))


def refine(clock,logits,structure,observed=None,max_iterations=MAX_ITERATIONS):
    observed=peaks(logits,structure) if observed is None else observed
    current=evaluate(clock.copy(),logits,structure,observed)
    history=[]
    for iteration in range(max_iterations):
        q,t,weight,receipt=associations(current['clock'],current['meter']['bars'],observed)
        if len(q)<2:break
        options=[]
        for name,knots in [('retained_knots',current['clock'][:,0]),
                           ('constant',current['clock'][[0,-1],0])]:
            initial=interpolate(current['clock'],knots)
            fitted=fit_knots(q,t,weight,knots,initial)
            candidate=evaluate(np.column_stack([knots,fitted]),logits,structure,observed)
            candidate['proposal']=name;options.append(candidate)
        best=max(options,key=lambda x:x['score'])
        accepted=best['score']>current['score']+1e-8
        history.append(dict(iteration=iteration,before=current['score'],after=best['score'],
                            accepted=accepted,proposal=best['proposal'],associations=receipt,
                            max_clock_displacement_seconds=float(np.max(abs(
                                interpolate(best['clock'],current['clock'][:,0])-current['clock'][:,1])))))
        if not accepted:break
        current=best
    current['history']=history
    return current
