"""Refine unaccepted clocks with a soft preference for simple quarter rates.

The input supplies pulse indices and a change topology. This neither discovers
quarter meaning nor adds tempo changes. References never enter selection. Fixed
integer/half rates compete with unrestricted rates while phase and existing
boundaries are refitted together. Scores are experimental, not probabilities.
"""
from dataclasses import asdict, dataclass, replace
from numbers import Integral
import numpy as np

from fit_clock import clock_time, design_matrix


@dataclass(frozen=True)
class PriorConfig:
    strength: float = 1.
    correlation_seconds: float = 4.
    noise_floor_seconds: float = .010
    quantization_seconds: float = .020
    half_rate_cost: float = .35
    candidate_radius_bpm: float = .5
    boundary_shift_pulses: float = 8.
    max_iterations: int = 24
    coordinate_passes: int = 2


def _huber(residual, delta):
    z=abs(residual)
    return float(np.sum(np.where(z<=delta,z*z,2*delta*z-delta*delta)))


def _constraint_basis(count, rates):
    rows=[];targets=[]
    for index,rate in enumerate(rates):
        if rate is not None:
            row=np.zeros(count);row[1:index+2]=1
            rows.append(row);targets.append(60/rate)
    if not rows:return np.zeros(count),np.eye(count)
    c=np.asarray(rows);d=np.asarray(targets)
    base=np.linalg.lstsq(c,d,rcond=None)[0]
    _,s,vt=np.linalg.svd(c,full_matrices=True)
    rank=int(np.sum(s>max(c.shape)*np.finfo(float).eps*s[0]))
    if np.max(abs(c@base-d))>1e-10:raise ValueError('rate constraints conflict')
    return base,vt[rank:].T


def _optimize(x,y,seed_knots,rates,delta,bounds,iterations):
    """Bounded variable projection; no source/reference realignment."""
    base,null=_constraint_basis(len(seed_knots)+2,rates)
    def solve(knots):
        a=design_matrix(x,knots);z=a@null;offset=y-a@base;weights=np.ones(len(x))
        for _ in range(8):
            root=np.sqrt(weights)
            co=base+null@np.linalg.lstsq(z*root[:,None],offset*root,rcond=None)[0]
            residual=y-a@co;updated=np.minimum(1,delta/np.maximum(abs(residual),1e-12))
            if np.max(abs(updated-weights))<1e-6:break
            weights=updated
        if np.any(np.cumsum(co[1:])<=0):return None
        return co,residual,weights,_huber(residual,delta),a
    knots=np.array(seed_knots,dtype=float);current=solve(knots)
    if current is None:return None
    for _ in range(iterations):
        co,residual,weights,cost,a=current
        if not len(knots):break
        derivative=(x[:,None]>knots)*(-co[None,2:])
        jac=np.column_stack([a@null,derivative]);root=np.sqrt(weights)
        step=np.linalg.lstsq(jac*root[:,None],residual*root,rcond=None)[0][-len(knots):]
        step=np.clip(step,-2.,2.)
        if np.max(abs(step))<1e-7:break
        accepted=False
        for shrink in (1.,.5,.25,.125,.0625,.03125):
            trial_knots=np.clip(knots+shrink*step,bounds[0],bounds[1])
            trial=solve(trial_knots)
            if trial is not None and trial[3]<cost-1e-12:
                knots,current=trial_knots,trial;accepted=True;break
        if not accepted:break
    return {'knots':knots,'coefficients':current[0],'residual':current[1],
            'data_cost':current[3],'rates':tuple(rates)}


def refine_tempo_clock(times,pulse_indices,baseline,config=None):
    config=config or PriorConfig()
    for name, minimum in (('max_iterations', 1), ('coordinate_passes', 0)):
        value=getattr(config,name)
        if isinstance(value,(bool,np.bool_)) or not isinstance(value,Integral) or value<minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    config=replace(config,max_iterations=int(config.max_iterations),coordinate_passes=int(config.coordinate_passes))
    if (not all(np.isfinite(value) for value in asdict(config).values()) or
            config.strength<0 or config.correlation_seconds<=0 or config.noise_floor_seconds<=0 or
            config.quantization_seconds<0 or not 0<=config.half_rate_cost<=1 or
            config.candidate_radius_bpm<=0 or config.boundary_shift_pulses<=0):
        raise ValueError('invalid tempo prior configuration')
    if baseline.get('accepted') or baseline.get('anchor_checks') or baseline.get('assistance') or baseline.get('locked_knots'):
        raise ValueError('this experiment does not alter accepted or anchored maps')
    x=np.asarray(pulse_indices,dtype=float);times=np.asarray(times,dtype=float)
    knots=np.asarray(baseline['knot_pulse_indices'],dtype=float)
    coefficients=np.asarray(baseline['coefficients'],dtype=float)
    if (x.ndim!=1 or times.shape!=x.shape or len(x)<4 or len(x)>3000 or
            not np.isfinite(x).all() or not np.isfinite(times).all() or np.any(np.diff(x)<0) or
            len(np.unique(x))<4 or knots.ndim!=1 or len(knots)>16 or
            coefficients.shape!=(len(knots)+2,) or not np.isfinite(coefficients).all() or
            not np.isfinite(knots).all() or np.any(np.diff(knots)<=0) or
            np.any(knots<=x[0]) or np.any(knots>=x[-1]) or np.any(np.cumsum(coefficients[1:])<=0)):
        raise ValueError('finite indexed observations and supported monotonic seed required')
    origin=float(np.median(times));y=times-origin
    residual=times-clock_time(x,knots,coefficients)
    sigma=max(config.noise_floor_seconds,config.quantization_seconds/np.sqrt(12),
              float(np.median(abs(residual-np.median(residual)))/.6744897501960817))
    delta=max(.02,1.5*sigma)
    # Adjacent original midpoints bound each change independently, retaining
    # order and avoiding new changes to mimic a forbidden intermediate rate.
    lower=np.maximum(knots-config.boundary_shift_pulses,np.r_[x[0],(knots[:-1]+knots[1:])/2]+1e-5) if len(knots) else knots
    upper=np.minimum(knots+config.boundary_shift_pulses,np.r_[(knots[:-1]+knots[1:])/2,x[-1]]-1e-5) if len(knots) else knots
    rates=60/np.cumsum(coefficients[1:]);membership=np.searchsorted(knots,x,side='right')
    penalties=[];options=[]
    for i,rate in enumerate(rates):
        indices=np.flatnonzero(membership==i);n=max(1,len(indices))
        span=float(np.ptp(times[indices])) if len(indices)>1 else 0.
        effective=min(max(1,len(np.unique(x[indices]))),1+span/config.correlation_seconds)
        penalties.append(config.strength*n*sigma*sigma*np.log(max(3.,effective))/effective)
        candidates={float(round(rate)),float(np.floor(rate*2)/2),float(np.ceil(rate*2)/2)}
        options.append([None]+sorted(v for v in candidates if v>0 and abs(v-rate)<=config.candidate_radius_bpm+1e-10))
    def penalty(assignment):
        return float(sum(p*(1 if v is None else 0 if abs(v-round(v))<1e-9 else config.half_rate_cost)
                         for p,v in zip(penalties,assignment)))
    cache={}
    def evaluate(assignment):
        key=tuple(assignment)
        if key not in cache:
            fit=_optimize(x,y,knots,key,delta,(lower,upper),config.max_iterations)
            if fit is not None:fit.update(prior_cost=penalty(key),score=fit['data_cost']+penalty(key))
            cache[key]=fit
        return cache[key]
    continuous=evaluate([None]*len(rates))
    if continuous is None:raise ValueError('continuous control fit failed')
    starts=[[None]*len(rates)]
    if config.strength>0:
        starts.extend([[min((v for v in values if v is not None),key=lambda v:abs(v-rate),default=None)
                        for values,rate in zip(options,rates)],
                       [next((v for v in values if v is not None and abs(v-round(v))<1e-9),None) for values in options]])
    best=continuous
    for assignment in starts:
        current=evaluate(assignment)
        if current is None:continue
        for _ in range(config.coordinate_passes if config.strength>0 else 0):
            changed=False
            for i,values in enumerate(options):
                for value in values:
                    trial=list(current['rates']);trial[i]=value;fit=evaluate(trial)
                    if fit is not None and fit['score']<current['score']-1e-12:
                        current=fit;changed=True
            if not changed:break
        if current['score']<best['score']-1e-12:best=current
    co=best['coefficients'].copy();co[0]+=origin;k=best['knots']
    starts=np.r_[x[0],k];ends=np.r_[k,x[-1]];periods=np.cumsum(co[1:])
    segments=[{'start_pulse':float(a),'end_pulse':float(b),
        'start_seconds':float(clock_time([a],k,co)[0]),'end_seconds':float(clock_time([b],k,co)[0]),
        'pulse_rate_per_minute':float(60/p)} for a,b,p in zip(starts,ends,periods)]
    return {'schema_version':'tempo-prior-v1','accepted':False,'status':'unaccepted_soft_tempo_prior',
        'source_origin_seconds':0,'reference_used_for_prediction':False,'meter':None,
        'pulse_unit':'input index; quarter interpretation remains caller hypothesis',
        'pulse_index_span':[float(x[0]),float(x[-1])],'input_pulse_indices':x.tolist(),
        'knot_pulse_indices':k.tolist(),'coefficients':co.tolist(),'segments':segments,
        'support_seconds':[segments[0]['start_seconds'],segments[-1]['end_seconds']],
        'parameters':asdict(config),'rate_constraints_bpm':list(best['rates']),
        'diagnostics':{'noise_scale_seconds':sigma,'huber_delta_seconds':delta,
            'penalty_by_segment':penalties,'score_not_confidence':best['score'],
            'data_cost':best['data_cost'],'prior_cost':best['prior_cost'],
            'continuous_control_score':continuous['score'],'continuous_control_data_cost':continuous['data_cost'],
            'assignments_evaluated':len(cache),'new_changes_added':0,
            'boundary_bounds_pulses':[lower.tolist(),upper.tolist()],
            'boundary_movement_pulses':(k-knots).tolist(),
            'global_optimum_claimed':False,'prior_calibrated':False,
            'warning':'Correlated-evidence penalty is a frozen experimental preference, not a population tempo distribution.'}}
