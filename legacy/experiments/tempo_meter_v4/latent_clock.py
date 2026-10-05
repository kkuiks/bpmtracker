"""Beam search over latent event coordinates and tempo-change explanations.

Each observation can be clutter, a quarter, an offbeat or a finer subdivision.
Missing events advance latent coordinates without creating observed beats.
Tempo changes compete with unchanged-clock rhythm changes at every event.
"""
from dataclasses import dataclass
import math
import numpy as np


@dataclass
class State:
    loss:float
    q:float
    t:float
    period:float
    knots:tuple
    assignments:tuple
    skipped:int=0
    moments:tuple=()


def time_at(knots,q):
    a=np.asarray(knots,float);q=np.asarray(q,float)
    out=np.interp(q,a[:,0],a[:,1])
    for x,y,mask in [(a[0],a[1],q<a[0,0]),(a[-2],a[-1],q>a[-1,0])]:
        out=np.where(mask,x[1]+(q-x[0])*(y[1]-x[1])/(y[0]-x[0]),out)
    return out


def initial_phase(obs,period):
    phases=np.linspace(0,period,max(16,int(period*obs['fps']*2)),endpoint=False)
    horizon=min(obs['duration'],32.)
    score=[]
    for phase in phases:
        t=np.arange(phase,horizon,period)
        score.append(np.mean(np.interp(t,obs['times'],obs['beat'])))
    order=np.argsort(score)[::-1];chosen=[]
    for i in order:
        if all(min(abs(phases[i]-p),period-abs(phases[i]-p))>period*.2 for p in chosen):chosen.append(float(phases[i]))
        if len(chosen)==2:break
    return chosen


def update_line(state,q,t,strength):
    """Update the same continuous clock jointly with a coordinate hypothesis.

    The weak two-point prior preserves an initialization without fixing its
    numerical tempo. Data may refit slope and phase before a new segment is
    needed. This prevents slow residual accumulation from changing pulse count.
    """
    q0,t0=state.knots[-1]
    prior=(.5,1.,4.,state.period,4*state.period)
    sw,sx,sxx,sy,sxy=state.moments or prior
    x=q-q0;y=t-t0
    old_residual=t-(state.t+(q-state.q)*state.period)
    weight=max(.05,float(strength))*min(1.,.04/max(abs(old_residual),1e-8))
    sw+=weight;sx+=weight*x;sxx+=weight*x*x;sy+=weight*y;sxy+=weight*x*y
    variance=max(1e-9,sxx-sx*sx/sw)
    slope=(sxy-sx*sy/sw)/variance
    if not 60/400<=slope<=60/25:return state.period,state.t+(q-state.q)*state.period,state.moments
    intercept=(sy-slope*sx)/sw
    return slope,t0+intercept+slope*x,(sw,sx,sxx,sy,sxy)


def search(obs,period,*,beam=32,change_cost=8.,bar_constraints=None,max_paths=4):
    times=obs['events'];strength=obs['event_strength'];down=obs['event_down']
    if len(times)<4:raise ValueError('insufficient source events')
    phases=initial_phase(obs,period)
    states=[State(0.,0.,phase,period,((0.,phase),),()) for phase in phases]
    sigma=.04
    for i,(t,p,d) in enumerate(zip(times,strength,down)):
        candidates=[]
        for state in states:
            predicted=state.q+(t-state.t)/state.period
            # Two nested rhythmic coordinate grids compete. Finer increments
            # pay an explicit notation/role cost, rather than absorbing any time.
            coarse=round(predicted*2)/2
            coordinates=set(coarse+x for x in (-.5,0,.5))
            fine=round(predicted*8)/8
            coordinates.add(fine)
            if not state.assignments:coordinates.add(0.)
            clutter=-math.log(max(1e-6,1-p*.9))+.8*d
            candidates.append(State(state.loss+clutter,state.q,state.t,state.period,state.knots,state.assignments,state.skipped+1,state.moments))
            for q in coordinates:
                if state.assignments and q<=state.q:continue
                if q < -1:continue
                previous_target=state.t+(q-state.q)*state.period
                residual=t-previous_target
                fitted_period,target,moments=update_line(state,q,t,p)
                fitted_residual=t-target
                role=(0. if abs(q-round(q))<1e-7 else .7 if abs(q*2-round(q*2))<1e-7 else 1.8)
                role*=max(.1,float(p))
                timing=min(8.,math.log1p((fitted_residual/sigma)**2))
                gap=q-state.q
                observable_gap=bool(state.assignments) and t-obs['events'][state.assignments[-1][0]]<4*state.period
                missing_cost=math.log(4.)*max(0.,gap-1.) if observable_gap else 0.
                cost=timing+role-.8*p+missing_cost
                if bar_constraints is not None and d>.2:
                    bq,bt=bar_constraints
                    k=int(np.argmin(abs(bt-t)))
                    if abs(bt[k]-t)<.15:
                        cost+=.5*d*min(4.,((q-bq[k])/.25)**2)
                candidates.append(State(state.loss+cost,q,target,fitted_period,state.knots,state.assignments+((i,q),),state.skipped,moments))
                # A new rate starts at the previous latent event, independently
                # of meter boundaries. It preserves continuous musical time.
                dq=q-state.q
                if state.assignments and dq>=.5 and t>state.t:
                    last_observed=times[state.assignments[-1][0]]
                    recent=state.assignments[-8:]+((i,q),)
                    rq=np.array([a[1] for a in recent]);rt=times[np.array([a[0] for a in recent],int)]
                    estimates=[(t-last_observed)/dq]
                    if len(recent)>=4 and np.ptp(rq)>1:
                        estimates.append(float(np.polyfit(rq,rt,1)[0]))
                    for newperiod in dict.fromkeys(round(x,8) for x in estimates):
                        ratio=newperiod/state.period
                        if 60/400<=newperiod<=60/25 and .5<=ratio<=2 and abs(math.log(ratio))>.00005:
                            if abs(residual)>sigma:
                                knots=state.knots+((state.q,state.t),) if state.q>state.knots[-1][0]+1e-8 else state.knots
                                candidates.append(State(state.loss+role-.8*p+missing_cost+change_cost,q,t,newperiod,knots,state.assignments+((i,q),),state.skipped))
        # Keep distinct tempo/phase/count explanations, not only nearby copies.
        candidates.sort(key=lambda x:x.loss)
        unique={}
        for c in candidates:
            key=(round(math.log(c.period)/.003),round(c.q*8),round((c.t-t)/.015),len(c.knots))
            if key not in unique:unique[key]=c
        by_changes={}
        for c in unique.values():by_changes.setdefault(min(4,len(c.knots)-1),[]).append(c)
        reserve=max(2,beam//max(1,len(by_changes)))
        chosen=[c for group in by_changes.values() for c in group[:reserve]]
        ids={id(c) for c in chosen}
        chosen.extend(c for c in unique.values() if id(c) not in ids)
        states=sorted(chosen[:max(beam,len(by_changes)*reserve)],key=lambda c:c.loss)[:beam]
        if not states:raise ValueError('empty latent-coordinate beam')
    output=[]
    for s in sorted(states,key=lambda x:x.loss):
        if len(s.assignments)<4:continue
        endq=s.q+(obs['duration']-s.t)/s.period
        knots=list(s.knots)
        if endq<=knots[-1][0]:continue
        knots.append((endq,obs['duration']))
        if knots[0][0]<0:continue
        a=np.asarray(knots,float)
        if np.any(np.diff(a[:,0])<=0) or np.any(np.diff(a[:,1])<=0):continue
        output.append(dict(clock=a,assignments=np.asarray(s.assignments,float),loss=s.loss,
                           skipped=s.skipped,beam=beam,event_count=len(times)))
        if len(output)==max_paths:break
    if not output:raise ValueError('no valid latent clock')
    return output
