"""Conditional whole-song clocks assembled without reference-driven prediction.

The one-step bridge is a bounded musical hypothesis, not proof of unobserved
beat counts. Explicit creator/manual anchors are a separate assisted path.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import numpy as np

from fit_clock import clock_time, design_matrix
from fit_clock_v2 import FitConfig, fit_clock_v2


@dataclass(frozen=True)
class AssemblyConfig:
    quantization_seconds: float = .02
    dense_gap_multiple: float = 2.5
    boundary_margin_pulses: float = 3.
    max_relative_rate_change: float = .2
    event_match_seconds: float = .07
    max_bridge_candidates: int = 12


def rebuild_clock(knots, coefficients, source_duration):
    knots=np.asarray(knots,dtype=float);coefficients=np.asarray(coefficients,dtype=float)
    if knots.ndim!=1 or coefficients.ndim!=1 or len(coefficients)!=len(knots)+2:
        raise ValueError('clock requires one slope change per knot')
    slopes=np.cumsum(coefficients[1:])
    if (not np.isfinite(coefficients).all() or not np.isfinite(knots).all() or np.any(slopes<=0) or np.any(np.diff(knots)<=0)
            or not np.isfinite(source_duration) or source_duration<=0):
        raise ValueError('clock must be finite and strictly monotonic')
    boundaries=clock_time(knots,knots,coefficients)
    def inverse(t):
        i=int(np.searchsorted(boundaries,t,side='right'))
        q0=0 if i==0 else knots[i-1]
        t0=coefficients[0] if i==0 else boundaries[i-1]
        return float(q0+(t-t0)/slopes[i])
    lo,hi=inverse(0),inverse(source_duration)
    keep=(knots>lo)&(knots<hi)
    starts=np.r_[lo,knots[keep]];ends=np.r_[knots[keep],hi]
    segments=[]
    for a,b in zip(starts,ends):
        t0,t1=clock_time([a,b],knots,coefficients)
        segments.append({'start_pulse':float(a),'end_pulse':float(b),
            'start_seconds':float(max(0,t0)), 'end_seconds':float(min(source_duration,t1)),
            'pulse_rate_per_minute':float(60*(b-a)/(t1-t0))})
    # Exact linear constraints can leave a 1e-13 intercept. Retain boundary
    # events within floating-point tolerance; this is not a timing alignment.
    q=np.arange(np.ceil(lo-1e-10),np.floor(hi+1e-10)+1)
    t=clock_time(q,knots,coefficients)
    t[np.abs(t)<1e-10]=0.
    t[np.abs(t-source_duration)<1e-10]=source_duration
    inside=(t>=0)&(t<source_duration)
    return {'accepted':False,'source_origin_seconds':0,'source_audio_modified':False,
        'status':'unaccepted_full_source_clock','pulse_unit':'quarter hypothesis',
        'knot_pulse_indices':knots.tolist(),'coefficients':coefficients.tolist(),
        'pulse_index_span':[lo,hi],'support_seconds':[0.,float(source_duration)],'segments':segments,
        'indexed_grid':[{'quarter_position':float(a),'source_seconds':float(b)} for a,b in zip(q[inside],t[inside])],
        'beats_seconds':t[inside].tolist()}


def linear_fit(indices,times):
    x=np.column_stack([np.ones(len(indices)),indices]);weight=np.ones(len(indices))
    for _ in range(8):
        root=np.sqrt(weight);co=np.linalg.lstsq(x*root[:,None],times*root,rcond=None)[0]
        residual=times-x@co;weight=np.minimum(1,.020/np.maximum(abs(residual),1e-12))
    return co,residual


def _source_score(times,observations,logits_by_model,interval,tolerance):
    lo,hi=interval;grid=np.asarray(times);grid=grid[(grid>=lo)&(grid<=hi)]
    if not len(grid):return -1e6,{}
    values={}
    for model,events in observations.items():
        events=np.asarray(events);events=events[(events>=lo)&(events<=hi)]
        if not len(events):coverage=0.
        else:
            i=np.searchsorted(grid,events)
            d=np.minimum(abs(events-grid[np.clip(i,0,len(grid)-1)]),abs(events-grid[np.clip(i-1,0,len(grid)-1)]))
            coverage=float(np.mean(d<=tolerance))
        logits,fps=logits_by_model[model]
        probability=1/(1+np.exp(-np.clip(logits,-60,60)));radius=max(1,round(.04*fps))
        strength=[]
        for t in grid:
            index=round(t*fps);a=max(0,index-radius);b=min(len(probability),index+radius+1)
            strength.append(float(np.max(probability[a:b])) if b>a else 0.)
        values[model]={'observed_event_coverage':coverage,'mean_grid_peak_probability':float(np.mean(strength))}
    score=float(np.mean([v['observed_event_coverage']+.5*v['mean_grid_peak_probability'] for v in values.values()]))
    return score,values


def assemble_clock(region_set,observations,logits_by_model,duration,config=None,tempo_prior_config=None):
    config=config or AssemblyConfig()
    if len(region_set['regions'])<2:raise ValueError('need at least two independent supported regions')
    first=min(c['region']['id'] for c in region_set['candidates']);last=max(c['region']['id'] for c in region_set['candidates'])
    choose=lambda r:max((c for c in region_set['candidates'] if c['region']['id']==r),key=lambda c:c['evidence_score_not_confidence'])
    left,right=choose(first),choose(last)
    if any(c.get('phase_offset_quarters',0)!=0 for c in (left,right)):
        raise ValueError('this pilot requires a zero-phase observed-event candidate')
    if right['clock']['knot_pulse_indices']:
        raise ValueError('this pilot requires a constant-rate terminal region')
    lt=np.asarray(left['input_event_indexing']['source_seconds']);lx=np.asarray(left['input_event_indexing']['quarter_positions'])
    typical=float(np.median(np.diff(lt)/np.diff(lx)))
    gaps=np.flatnonzero(np.diff(lt)>config.dense_gap_multiple*typical)
    cut=int(gaps[0]+1) if len(gaps) else len(lt)
    lt,lx=lt[:cut],lx[:cut]
    early=fit_clock_v2(lt,pulse_indices=lx,config=FitConfig(observation_quantization_seconds=config.quantization_seconds))
    # Explicit experimental opt-in. The original path and cached comparisons
    # retain their behavior when no prior configuration is supplied.
    if tempo_prior_config is not None:
        from tempo_prior import refine_tempo_clock
        early=refine_tempo_clock(lt,lx,early,tempo_prior_config)
    rt=np.asarray(right['input_event_indexing']['source_seconds']);rx=np.asarray(right['input_event_indexing']['quarter_positions'])
    # The primary candidate supplies a relative index hypothesis. Other models
    # contribute only nearby raw observations, never DBN-imputed silent beats.
    rc=np.asarray(right['clock']['coefficients']);rk=np.asarray(right['clock']['knot_pulse_indices'])
    late_first=right['source_support_seconds'][0];late_last=right['source_support_seconds'][1]
    period=float(np.median(np.diff(rt)/np.diff(rx)))
    augmented_q=list(rx);augmented_t=list(rt)
    for events in observations.values():
        for t in events:
            if late_first<=t<=late_last:
                q=round((t-rc[0])/period)
                predicted=float(clock_time([q],rk,rc)[0])
                if abs(predicted-t)<=config.event_match_seconds:
                    augmented_q.append(q);augmented_t.append(t)
    # One contribution per source timestamp; no model is weighted by duplicate
    # appearances in its official and minimal decoding outputs.
    pairs=sorted(set(zip(augmented_q,augmented_t)),key=lambda pair:pair[1])
    rx=np.asarray([v[0] for v in pairs]);rt=np.asarray([v[1] for v in pairs])
    late,residual=linear_fit(rx,rt)
    late_prior=None
    if tempo_prior_config is not None:
        late_prior=refine_tempo_clock(rt,rx,{'coefficients':late.tolist(),'knot_pulse_indices':[]},tempo_prior_config)
        late=np.asarray(late_prior['coefficients']);residual=rt-clock_time(rx,[],late)
    slope_left=float(np.sum(early['coefficients'][1:]));slope_right=float(late[1])
    if abs(slope_right/slope_left-1)>config.max_relative_rate_change:
        raise ValueError('same-level small-transition hypothesis is not supported')
    if abs(slope_left-slope_right)<1e-8:raise ValueError('equal-rate phases require a different bridge hypothesis')
    last_segment=early['segments'][-1]
    left_intercept=last_segment['start_seconds']-slope_left*last_segment['start_pulse']
    bridges=region_set.get('unknown_bridges',[])
    next_observed=min((b['source_end_seconds'] for b in bridges if b['source_start_seconds']>=lt[-1]-.1),default=late_first)
    lower=max(last_segment['start_seconds'],lt[-1]-config.boundary_margin_pulses*slope_left)
    upper=min(late_first,next_observed+config.boundary_margin_pulses*slope_right)
    # Broad enumeration is bounded by source duration and the inferred period,
    # rather than an annotation-derived count or musical bar number.
    center=round((late[0]-early['coefficients'][0])/((slope_left+slope_right)/2))
    radius=max(8,int(duration*abs(1/slope_left-1/slope_right))+8)
    options=[]
    for offset in range(center-radius,center+radius+1):
        q=(late[0]-slope_right*offset-left_intercept)/(slope_left-slope_right)
        t=left_intercept+slope_left*q
        if not lower<=t<=upper or q<=max(early['knot_pulse_indices'],default=0):continue
        knots=[*early['knot_pulse_indices'],float(q)]
        coefficients=[*early['coefficients'],float(slope_right-slope_left)]
        complete=rebuild_clock(knots,coefficients,duration)
        score,detail=_source_score(complete['beats_seconds'],observations,logits_by_model,(lt[-1]-4,late_first),config.event_match_seconds)
        options.append({'id':f'bridge-offset-{offset}','clock':complete,'right_index_offset':int(offset),
            'boundary_seconds':float(t),'boundary_quarter':float(q),'score_not_confidence':score,'score_components':detail})
    options.sort(key=lambda v:-v['score_not_confidence']);options=options[:config.max_bridge_candidates]
    if not options:raise ValueError('no continuous small-step bridge within the disclosed uncertainty interval')
    output={'schema_version':'whole-song-conditional-v1','reference_used_for_prediction':False,
        'configuration':asdict(config),'selected_candidate_id':options[0]['id'],'candidates':options,
        'accepted':False,'status':'conditional_full_map_not_certified',
        'assumptions':['Selected input pulses share a quarter interpretation.','One tempo step connects the supported early and terminal phases.',
                       'The final supported tempo is extrapolated through unsupported sections and the tail.'],
        'bridge_certified':False,'bridge_uncertainty_seconds':[float(lower),float(upper)],
        'unsupported_or_disagreeing_regions':bridges,
        'early_candidate_id':left['id'],'late_candidate_id':right['id'],
        'early_clock':early,'late_line':late.tolist(),'late_residual_p95_seconds':float(np.percentile(abs(residual),95)),
        'observations':{'early_indices':lx.tolist(),'early_seconds':lt.tolist(),'late_indices':rx.tolist(),'late_seconds':rt.tolist()},
        'observed_support_seconds':[float(lt[0]),float(rt[-1])],
        'musical_index_origin':'candidate-relative; original bar origin unresolved','meter':None}
    if tempo_prior_config is not None:
        output['tempo_prior']={'configuration':asdict(tempo_prior_config),'late_fit':late_prior,
                               'scope':'source-only rate/phase refit before conditional bridge assembly'}
    return output


def assist_clock(automatic,anchors,quarter_offset,meter,source_duration):
    """Reconstruct using an explicitly provided musical origin and three anchors.

    Anchor provenance is mandatory. This never reports assisted results as an
    automatic inference or as a measured human correction session.
    """
    if len(anchors)!=3 or any(not a.get('provenance') for a in anchors):
        raise ValueError('three explicit origin/boundary/end anchors with provenance required')
    anchors=sorted(deepcopy(anchors),key=lambda a:a['quarter_position'])
    if (not np.isfinite(quarter_offset) or quarter_offset!=int(quarter_offset) or
        any(not np.isfinite([a['quarter_position'],a['source_seconds']]).all() or
            a['quarter_position']<0 or not 0<=a['source_seconds']<source_duration for a in anchors) or
        any(b['quarter_position']<=a['quarter_position'] or b['source_seconds']<=a['source_seconds']
            for a,b in zip(anchors,anchors[1:]))):
        raise ValueError('anchors must be finite, ordered, distinct and inside the source')
    if anchors[0]['quarter_position']!=0 or meter!= {'numerator':4,'denominator':4}:
        raise ValueError('this completion pilot requires an explicit origin and 4/4 convention')
    selected=next(c for c in automatic['candidates'] if c['id']==automatic['selected_candidate_id'])
    knot_boundary=anchors[1]['quarter_position'];end=anchors[-1]['quarter_position']
    observations=automatic['observations']
    values={}
    for q,t in zip(observations['early_indices'],observations['early_seconds']):
        q=q+quarter_offset
        if q<knot_boundary:values.setdefault(float(q),[]).append(t)
    for q,t in zip(observations['late_indices'],observations['late_seconds']):
        q=q+selected['right_index_offset']+quarter_offset
        if knot_boundary<q<=end:values.setdefault(float(q),[]).append(t)
    # Supplied anchors are explicit constraints, not acoustic observations or
    # reference event streams masquerading as predicted evidence.
    for a in anchors:values.setdefault(float(a['quarter_position']),[]).append(a['source_seconds'])
    x=np.array(sorted(values));times=np.array([np.mean(values[q]) for q in x])
    knots=[q+quarter_offset for q in automatic['early_clock']['knot_pulse_indices'] if 0<q+quarter_offset<knot_boundary]
    knots.append(float(knot_boundary))
    # Fixed topology: preserve inferred early boundaries, constrain the one
    # declared bridge boundary, and do not invent later changes to chase onset bias.
    a=design_matrix(x,knots);c=design_matrix(np.array([v['quarter_position'] for v in anchors]),knots)
    d=np.array([v['source_seconds'] for v in anchors]);base=np.linalg.lstsq(c,d,rcond=None)[0]
    if np.max(abs(c@base-d))>1e-8:raise ValueError('anchors conflict with clock topology')
    _,s,vt=np.linalg.svd(c,full_matrices=True);rank=np.sum(s>max(c.shape)*np.finfo(float).eps*s[0]);null=vt[rank:].T
    coefficients=base+null@np.linalg.lstsq(a@null,times-a@base,rcond=None)[0]
    complete=rebuild_clock(knots,coefficients,source_duration)
    complete.update({'status':'creator_anchor_assisted_complete_map','reference_used_for_prediction':True,
        'assistance':{'anchors':anchors,'quarter_origin_offset':quarter_offset,'meter':meter,
                      'counts':{'timing_anchors':3,'meter_confirmation':1},
                      'human_actions_measured':False,'description':'Creator metadata assisted demonstration, not automatic accuracy or a human correction study.'},
        'meter':{'numerator':4,'denominator':4,'start_quarter':0,'provenance':'explicit creator metadata assistance'},
        'anchor_checks':[{'quarter_position':v['quarter_position'],'absolute_error_seconds':abs(float(clock_time([v['quarter_position']],knots,coefficients)[0])-v['source_seconds'])} for v in anchors]})
    return complete
