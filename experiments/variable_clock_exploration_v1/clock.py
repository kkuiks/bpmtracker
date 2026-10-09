"""Audio-event clock witnesses, affine compression and multiscale agreement.

No source identity, reference, support label, tempo hint or meter is accepted.
This is an exploratory pulse-clock model, not an application replacement.
"""
from __future__ import annotations

from fractions import Fraction
import math

import numpy as np
from scipy.signal import find_peaks
from scipy.special import expit


def quantize(bpm):
    return float(Fraction(float(np.clip(bpm, 30, 400))).limit_denominator(4))


def events_from_evidence(data, attack_snap=False):
    fps = float(data['fps'])
    probability = expit(np.asarray(data['beat_logits'], dtype=float))
    positions, _ = find_peaks(probability, height=.25, distance=3)
    times = positions / fps
    weights = probability[positions]
    if 'silent_frame_mask' in data:
        keep = ~np.asarray(data['silent_frame_mask'], dtype=bool)[positions]
        times, weights = times[keep], weights[keep]
    snapped = 0
    if attack_snap and 'attack_times' in data and len(data['attack_times']):
        attacks = np.asarray(data['attack_times'], dtype=float)
        strengths = np.asarray(data['attack_weights'], dtype=float)
        corrected = times.copy()
        for i, t in enumerate(times):
            start, end = np.searchsorted(attacks, [t-.07, t+.07])
            if end > start:
                candidates = np.arange(start, end)
                score = strengths[candidates] * np.exp(-.5*((attacks[candidates]-t)/.04)**2)
                corrected[i] = attacks[candidates[np.argmax(score)]]
                snapped += 1
        times = corrected
        keep = np.r_[True, np.diff(times) > .06]
        times, weights = times[keep], weights[keep]
    return times, weights, {'events': len(times), 'attack_corrected_events': snapped,
                           'raw_attack_available': 'attack_times' in data,
                           'strict_silence_mask_available': 'silent_frame_mask' in data}


def event_axis(times):
    """Infer missing-pulse counts locally; absolute labels and BPM never enter."""
    if len(times) < 2:
        return np.zeros(len(times))
    gaps = np.diff(times)
    local = np.array([np.median(gaps[max(0,i-4):min(len(gaps),i+5)]) for i in range(len(gaps))])
    counts = np.clip(np.rint(gaps / np.maximum(local, .1)), 1, 16)
    return np.r_[0., np.cumsum(counts)]


def fit_line(x, y, weights=None):
    weights = np.ones(len(x)) if weights is None else weights
    sw = weights.sum()
    if len(x) < 3 or sw <= 0:
        return None
    xm, ym = np.sum(x*weights)/sw, np.sum(y*weights)/sw
    denominator = np.sum(weights*(x-xm)**2)
    if denominator <= 0:
        return None
    period = np.sum(weights*(x-xm)*(y-ym))/denominator
    if not .15 <= period <= 2:
        return None
    origin = ym-period*xm
    residual = y-origin-period*x
    rms = math.sqrt(float(np.sum(weights*residual**2)/sw))
    nominal_bpm=quantize(60/period);nominal_period=60/nominal_bpm
    # Preserve the declared rational output domain even when a continuous latent
    # regression fits more precisely. Event scores use this nominal clock.
    nominal_origin=float(np.sum(weights*(y-nominal_period*x))/sw)
    return {'period': float(period), 'origin': float(origin), 'rms': rms,
            'bpm_continuous': float(60/period), 'bpm': nominal_bpm,
            'nominal_period':nominal_period,'nominal_phase':nominal_origin%nominal_period,
            'phase': float(origin % period), 'events': len(x),
            'slope_error': float(max(.01, rms)/math.sqrt(denominator))}


def noise_scale(x, t):
    if len(t) < 5:
        return .03
    alpha = (x[1:-1]-x[:-2])/(x[2:]-x[:-2])
    predicted = (1-alpha)*t[:-2]+alpha*t[2:]
    residual = t[1:-1]-predicted
    return float(np.clip(np.median(abs(residual-np.median(residual)))*1.4826/math.sqrt(1.5), .02, .12))


def affine_partition(x, y, weights, sigma, penalty_scale, minimum=4):
    """Nonrecursive global affine description-length comparison of event times."""
    n = len(x)
    if n < minimum:
        return []
    prefix = [np.r_[0.,np.cumsum(v)] for v in
              (weights,weights*x,weights*y,weights*x*x,weights*x*y,weights*y*y)]
    best = np.full(n+1, np.inf); previous = np.full(n+1,-1,dtype=int)
    best[0] = -penalty_scale*math.log(max(n,3))
    penalty = penalty_scale*math.log(max(n,3))
    for end in range(minimum,n+1):
        starts = np.arange(end-minimum+1)
        sw,sx,sy,sxx,sxy,syy = [v[end]-v[starts] for v in prefix]
        vx = sxx-sx*sx/np.maximum(sw,1e-10)
        covariance = sxy-sx*sy/np.maximum(sw,1e-10)
        slopes = covariance/np.maximum(vx,1e-10)
        residual = np.maximum(0,syy-sy*sy/np.maximum(sw,1e-10)-covariance**2/np.maximum(vx,1e-10))
        costs = best[starts]+residual/sigma**2+penalty
        costs[(slopes < .15)|(slopes > 2)|(vx <= 0)] = np.inf
        index = int(np.argmin(costs))
        best[end],previous[end] = costs[index],starts[index]
    if not np.isfinite(best[n]):
        return []
    spans=[]; end=n
    while end>0:
        start=int(previous[end])
        if start < 0: return []
        spans.append((start,end));end=start
    return spans[::-1]


def constant_partition(values, weights, penalty_scale, minimum):
    n=len(values)
    if n < minimum: return []
    w=np.r_[0.,np.cumsum(weights)]; wy=np.r_[0.,np.cumsum(weights*values)]
    wy2=np.r_[0.,np.cumsum(weights*values**2)]
    best=np.full(n+1,np.inf); back=np.full(n+1,-1,dtype=int)
    penalty=penalty_scale*math.log(max(n,3));best[0]=-penalty
    for end in range(minimum,n+1):
        start=np.arange(end-minimum+1)
        sw=w[end]-w[start];sy=wy[end]-wy[start];sy2=wy2[end]-wy2[start]
        cost=best[start]+np.maximum(0,sy2-sy**2/np.maximum(sw,1e-10))+penalty
        i=int(np.argmin(cost));best[end]=cost[i];back[end]=start[i]
    if not np.isfinite(best[n]):return []
    result=[];end=n
    while end>0:
        start=int(back[end]);result.append((start,end));end=start
    return result[::-1]


def local_witnesses(x,t,w,sigma,duration):
    centers=np.arange(.25,duration,.5); selected=[]; all_counts=[]
    for center in centers:
        choices=[]
        for span in (2,4,8,16,32,64):
            a,b=np.searchsorted(t,[center-span/2,center+span/2])
            if b-a<4:continue
            fit=fit_line(x[a:b],t[a:b],w[a:b])
            if fit is None:continue
            fit={**fit,'span':span,'start':float(t[a]),'end':float(t[b-1])}
            # Test both interleaved subsets to avoid rewarding a flexible tiny fit.
            subsets=[fit_line(x[a:b][j::2],t[a:b][j::2],w[a:b][j::2]) for j in (0,1)]
            if all(s is not None for s in subsets):
                discrepancy=abs(subsets[0]['period']-subsets[1]['period'])*np.ptp(x[a:b])
            else:discrepancy=sigma
            fit['crossfit_discrepancy']=float(discrepancy)
            if fit['rms']<=1.8*sigma and discrepancy<=4*sigma:
                choices.append(fit)
        all_counts.append(len(choices))
        if choices:
            fit=max(choices,key=lambda z:z['events'])
            relative_error=max(fit['slope_error']/fit['period'],.001)
            selected.append((center,math.log(fit['period']),min(1/relative_error**2,1e6),fit))
    return selected,{'centers':len(centers),'supported_centers':len(selected),
                     'multiscale_witnesses':int(sum(all_counts)),
                     'minimum_window_is_not_a_tempo_boundary':True}


def as_regions(spans,x,t,w,duration):
    result=[]
    for start,end in spans:
        fit=fit_line(x[start:end],t[start:end],w[start:end])
        if fit is None:continue
        left=0. if start==0 else float((t[start-1]+t[start])/2)
        right=duration if end==len(t) else float((t[end-1]+t[end])/2)
        result.append({**fit,'start':left,'end':right,'first_event':float(t[start]),
                       'last_event':float(t[end-1]),'event_start_index':start,'event_end_index':end})
    return result


def merge_equivalent(regions,x,t,w,duration,sigma):
    if not regions:return []
    result=[regions[0]]
    for region in regions[1:]:
        old=result[-1]
        a,b=old['event_start_index'],region['event_end_index']
        fit=fit_line(x[a:b],t[a:b],w[a:b])
        uncertainty=3*(old['slope_error']+region['slope_error'])
        if fit and (abs(old['period']-region['period'])<=uncertainty or old['bpm']==region['bpm']) and fit['rms']<=2.5*sigma:
            result[-1]={**old,**fit,'end':region['end'],'last_event':region['last_event'],'event_end_index':b}
        else:result.append(region)
    return result


def boundaries(regions,x,t,sigma,continuity):
    result=[]
    for left,right in zip(regions,regions[1:]):
        lo,hi=left['last_event'],right['first_event']
        middle=(lo+hi)/2
        slope=left['period']-right['period']
        crossing=None
        if abs(slope)>1e-10:
            lo_origin,hi_origin=left['origin'],right['origin']
            if left.get('independent_event_coordinates') or right.get('independent_event_coordinates'):
                lo_origin+=left['period']*round((middle-lo_origin)/left['period'])
                hi_origin+=right['period']*round((middle-hi_origin)/right['period'])
            index=(hi_origin-lo_origin)/slope
            value=lo_origin+left['period']*index
            if lo-max(left['period'],right['period'])<=value<=hi+max(left['period'],right['period']):
                crossing=float(value)
        # Phase intersection is inferred from source events, and remains conditional.
        time=crossing if continuity and crossing is not None else middle
        unit_ratio=right['bpm_continuous']/left['bpm_continuous']
        harmonic=min(abs(math.log2(unit_ratio)-k) for k in (-1,1))<.025
        result.append({'time':float(time),'event_bracket':[float(lo),float(hi)],
                       'source_phase_intersection':crossing,'phase_continuity_assumed':continuity,
                       'left_bpm':left['bpm'],'right_bpm':right['bpm'],
                       'kind':'phase_reset' if left['bpm']==right['bpm'] else 'rate_change',
                       'metrical_octave_ambiguity':harmonic,
                       'interval_is_not_a_calibrated_confidence_interval':True})
        left['end']=right['start']=float(np.clip(time,left['start'],right['end']))
    return result


def predict(data,method,penalty=16.,attack_snap=False):
    duration=float(data['duration_seconds'])
    t,w,diagnostic=events_from_evidence(data,attack_snap)
    if len(t)<4:return {'status':'UNKNOWN_insufficient_events','regions':[],'boundaries':[],'diagnostic':diagnostic}
    x=event_axis(t);sigma=noise_scale(x,t)
    diagnostic.update(noise_scale_seconds=sigma,inferred_missing_pulses=int(x[-1]-(len(x)-1)))
    alternatives=[]
    if method in ('phasor_transport','phasor_abstain'):
        from .phasor import regions as phase_regions
        regions,extra,alternatives=phase_regions(t,w,duration,sigma,penalty)
        diagnostic.update(extra)
        spans=None
    elif method=='affine_mdl':
        spans=affine_partition(x,t,w,sigma,penalty)
    elif method in ('multiscale','transport'):
        witnesses,extra=local_witnesses(x,t,w,sigma,duration);diagnostic.update(extra)
        if len(witnesses)<3:return {'status':'UNKNOWN_no_local_witness','regions':[],'boundaries':[],'diagnostic':diagnostic}
        values=np.array([r[1] for r in witnesses]);weights=np.array([r[2] for r in witnesses])
        blocks=constant_partition(values,weights,penalty,3)
        cuts=[]
        for a,b in blocks:
            start=0 if a==0 else int(np.searchsorted(t,(witnesses[a-1][0]+witnesses[a][0])/2))
            end=len(t) if b==len(witnesses) else int(np.searchsorted(t,(witnesses[b-1][0]+witnesses[b][0])/2))
            if end-start>=4:cuts.append((start,end))
        spans=cuts
    else:raise ValueError('Unknown method')
    if spans is not None:regions=merge_equivalent(as_regions(spans,x,t,w,duration),x,t,w,duration,sigma)
    switches=boundaries(regions,x,t,sigma,method in ('transport','phasor_transport','phasor_abstain'))
    for region in regions:
        region['unit_family']=[{'bpm':quantize(region['bpm_continuous']*scale),
                                'scale':scale,'phase':float(region['origin']%(region['period']/scale))}
                               for scale in (.5,1.,2.) if 30<=region['bpm_continuous']*scale<=400]
        region['source_supported_span']=[region['first_event'],region['last_event']]
    unknown=[];uncertain_switches=[]
    if method=='phasor_abstain':
        for region in regions:
            coverage=region['events']/max(1,1+(region['last_event']-region['first_event'])/region['period'])
            region['source_tick_occupancy']=float(min(coverage,1))
            region['confidence_state']='SUPPORTED' if coverage>=.65 else 'UNKNOWN_sparse_tick_support'
            if coverage<.65:unknown.append([region['start'],region['end']])
        accepted=[]
        for switch,left,right in zip(switches,regions,regions[1:]):
            if left['confidence_state']=='SUPPORTED' and right['confidence_state']=='SUPPORTED':accepted.append(switch)
            else:uncertain_switches.append(switch)
        switches=accepted
    if 'silent_frame_mask' in data:
        silent=np.asarray(data['silent_frame_mask'],dtype=bool)
        first=np.flatnonzero(silent & ~np.r_[False,silent[:-1]])
        last=np.flatnonzero(silent & ~np.r_[silent[1:],False])+1
        for a,b in zip(first,last):
            start,end=a/float(data['fps']),min(b/float(data['fps']),duration)
            periods=[r['period'] for r in regions if r['start']<end and r['end']>start]
            if periods and end-start>=min(periods):unknown.append([start,end])
    return {'status':'exploratory_pulse_clock_proposal','regions':regions,'boundaries':switches,
            'unknown_intervals_seconds':unknown,
            'uncertain_boundary_hypotheses':uncertain_switches,
            'source_clock_alternatives':alternatives,
            'native_pulse_unit_is_not_certified_quarter_notation':True,
            'reference_fields_read':False,'initial_tap_used':False,
            'method':method,'penalty':penalty,'attack_snap':attack_snap,'diagnostic':diagnostic}
