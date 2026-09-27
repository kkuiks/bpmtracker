"""Restricted fixed-primary-role bar lattice; an unaccepted research hypothesis.

Only raw beat/downbeat logits, their physical source clock and an optional
scalar guide enter inference. The guide unit is latent and its factor is local
to a source-derived eight-event window. No reference, meter or anchor input.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction
import hashlib
import math
import time

import numpy as np
from beat_this.model.postprocessor import deduplicate_peaks
from music_map_contract import prepare_map


@dataclass(frozen=True)
class JointConfig:
    min_quarter_bpm: float = 35.
    max_quarter_bpm: float = 320.
    max_bar_seconds: float = 8.
    beam_width: int = 16
    max_transition_comparisons: int = 100_000_000
    max_cpu_seconds: float = 120.
    max_working_memory_bytes: int = 512 * 1024 * 1024
    max_alternatives: int = 8
    tempo_transition_weight: float = 8.
    template_change_cost: float = 2.
    guide_relative_scale: float = .02


# A global frozen vocabulary, not a per-song meter restriction.
TEMPLATES = (
    ('2/4:1+1',2,4,(1,1)), ('3/4:1+1+1',3,4,(1,1,1)),
    ('4/4:1+1+1+1',4,4,(1,1,1,1)), ('6/8:3+3',6,8,(3,3)),
    ('8/4:1x8',8,4,(1,)*8), ('8/4:2+2+2+2',8,4,(2,2,2,2)),
)
GUIDE_UNITS = (Fraction(1,2),Fraction(1),Fraction(3,2),Fraction(2))


def _configuration(config):
    config=config or JointConfig()
    if not isinstance(config,JointConfig):raise TypeError('config must be JointConfig')
    for name in ('beam_width','max_transition_comparisons','max_working_memory_bytes','max_alternatives'):
        v=getattr(config,name)
        if isinstance(v,bool) or not isinstance(v,int) or v<1:raise ValueError(name+' must be a positive integer')
    for name in ('min_quarter_bpm','max_quarter_bpm','max_bar_seconds','max_cpu_seconds','guide_relative_scale'):
        v=getattr(config,name)
        if isinstance(v,bool) or not math.isfinite(v) or v<=0:raise ValueError(name+' must be finite and positive')
    for name in ('tempo_transition_weight','template_change_cost'):
        v=getattr(config,name)
        if isinstance(v,bool) or not math.isfinite(v) or v<0:raise ValueError(name+' must be finite and nonnegative')
    if config.min_quarter_bpm>=config.max_quarter_bpm:raise ValueError('quarter-rate range is empty')
    return config


def _source(source):
    if not isinstance(source,dict) or set(source)-{'sha256','sample_rate','sample_frames','path'}:
        raise ValueError('source accepts only physical hash/sample geometry and optional path; no interpretation fields')
    return prepare_map({'schema_version':1,'source':source,'clock_knots':[],'support_seconds':[]})['source']


def _evidence(values,fps):
    v=np.asarray(values,dtype=float)
    if v.ndim!=1 or not np.isfinite(v).all():raise ValueError('logits must be finite one-dimensional arrays')
    if isinstance(fps,bool) or not math.isfinite(fps) or fps<=0:raise ValueError('fps must be finite and positive')
    return v


def first_stable_window(beat_logits,fps,source,*,config=None):
    """Existing minimal peaks plus chronological pre-pruning stable8 predicate."""
    _configuration(config);source=_source(source);beat=_evidence(beat_logits,fps)
    duration=source['sample_frames']/source['sample_rate']
    if len(beat):
        maxima=np.lib.stride_tricks.sliding_window_view(np.pad(beat,3,constant_values=-np.inf),7).max(axis=1)
        peaks=deduplicate_peaks(np.flatnonzero((beat==maxima)&(beat>0)),width=1)/fps
        peaks=peaks[(peaks>=0)&(peaks<duration)]
    else:peaks=np.array([],dtype=float)
    base={'status':'guide_window_unresolved','start_seconds':None,'end_seconds':None,
          'source_support_seconds':None,'source_seconds':None,'event_times_seconds':[],
          'events_seconds':[],'event_indices':None,'stable_period_seconds':None,
          'method':'minimal7frame_positive_logit_peaks; existing chronological8event stability predicate before longest-region pruning',
          'guide_value_used':False,'reference_used':False,'trace':{'source_peak_count':len(peaks),'windows_checked':0,'rejected_segments':[]}}
    if len(peaks)<8:return base
    intervals=np.diff(peaks);plausible=intervals[(intervals>=60/320)&(intervals<=60/35)]
    typical=float(np.median(plausible)) if len(plausible) else float(np.median(intervals))
    gap=max(4.,8*typical);cuts=np.r_[0,np.flatnonzero(intervals>gap)+1,len(peaks)]
    base['trace']['gap_threshold_seconds']=gap
    for left,right in zip(cuts[:-1],cuts[1:]):
        for start in range(int(left),int(right)-7):
            sample=np.diff(peaks[start:start+8]);period=float(np.median(sample));multiples=np.rint(sample/period)
            base['trace']['windows_checked']+=1
            if (60/320<=period<=60/35 and np.all((multiples>=1)&(multiples<=2)) and np.max(abs(sample/period-multiples))<=.2):
                observed=peaks[start:start+8].tolist();span=[observed[0],observed[-1]]
                return {**base,'status':'found','start_seconds':span[0],'end_seconds':span[1],
                    'source_support_seconds':span,'source_seconds':span,'event_times_seconds':observed,
                    'events_seconds':observed,'event_indices':[start,start+8],'stable_period_seconds':period}
        base['trace']['rejected_segments'].append({'event_start':int(left),'event_end_exclusive':int(right),'reason':'no_eight_event_periodic_window'})
    return base


def _template_geometry(index):
    name,numerator,denominator,groups=TEMPLATES[index]
    offsets=np.r_[0,np.cumsum(groups)[:-1]].astype(float)/numerator
    return name,4*numerator/denominator,offsets


def fixed_schedule_data_score(beat_logits,downbeat_logits,fps,bar_starts_seconds,primary_events_seconds):
    """Declared-observation countercontrol only; identical masks have equal data energy."""
    beat=_evidence(beat_logits,fps);down=_evidence(downbeat_logits,fps)
    if len(beat)!=len(down):raise ValueError('channel lengths differ')
    def energy(values,times):
        times=np.asarray(times,dtype=float)
        if times.ndim!=1 or not np.isfinite(times).all() or np.any(np.diff(times)<=0):raise ValueError('event schedule must increase')
        frames=np.floor(times*fps+.5).astype(int)
        if np.any(frames<0) or np.any(frames>=len(values)):raise ValueError('event schedule exceeds logits')
        if len(set(frames.tolist()))!=len(frames):raise ValueError('one native frame cannot count twice in one channel')
        return float(values[frames].sum())
    b=energy(beat,primary_events_seconds);d=energy(down,bar_starts_seconds)
    return {'beat_logit_energy':b,'downbeat_logit_energy':d,'data_energy':b+d,
            'calibrated_likelihood':False,'role':'declared schedule countercontrol, not inference'}


def _top(values,limit):
    flat=values.ravel();finite=np.flatnonzero(np.isfinite(flat))
    if len(finite)>limit:
        local=np.argpartition(flat[finite],-limit)[-limit:];finite=finite[local]
    return finite.tolist()


def infer_joint_music_map(beat_logits,downbeat_logits,fps,source,*,guide_bpm=None,config=None):
    config=_configuration(config);source=_source(source);beat=_evidence(beat_logits,fps);down=_evidence(downbeat_logits,fps)
    if len(beat)!=len(down):raise ValueError('beat/downbeat channel lengths must match')
    if guide_bpm is not None and (isinstance(guide_bpm,bool) or not math.isfinite(guide_bpm) or guide_bpm<=0):raise ValueError('guide must be one finite positive scalar BPM')
    window=first_stable_window(beat,fps,source,config=config);duration=source['sample_frames']/source['sample_rate']
    started=time.process_time();endpoint_count=min(len(beat),int(math.floor(duration*fps+1e-10)))
    base={'schema_version':1,'status':'unresolved','map':None,'path':[],'alternatives':[],
        'guide_window':window,'score_components':None,'configuration':asdict(config),
        'guide':{'provided_scalar_bpm':guide_bpm,'unit_quarters_vocabulary':[{'numerator':h.numerator,'denominator':h.denominator} for h in GUIDE_UNITS],
                 'triplet_guide_unit_one_third_supported':False,'factor_outside_source_window':0.},
        'diagnostics':{'reference_used_for_prediction':False,'accepted':False,'model_changed':False,
            'observation_role':'fixed primary-group beat role; downbeat at bar start',
            'data_score':'raw-logit event-vs-common-background energy, not calibrated likelihood',
            'native_frame_sampling':'nearest native frame, positive half-up rounding; no peak prerequisite for lattice events',
            'initial_partial_bars_with_negative_context':True,
            'initial_partial_bar_emissions_outside_source_censored':True,
            'initial_partial_bar_requires_observed_event_position':True,
            'native_primary_samples_distinct_within_bar':True,
            'change_support':'tempo and template changes at bar boundaries only',
            'midbar_tempo_changes_supported':False,'nonbarline_resets_supported':False,'additive_5_8_supported':False,
            'guide_unit_inferred_once_not_user_supplied':True,'initial_phase_searched':True,
            'authored_musical_origin_inferred':False,'global_optimum_claimed':False,
            'musical_meter_uniqueness_certified':False,
            'local_topk_may_discard_ties_before_beam_sort':True,
            'reported_tie_counts_are_lower_bounds_not_global_uniqueness_tests':True,
            'beat_logits_sha256':hashlib.sha256(beat.astype('<f8').tobytes()).hexdigest(),
            'downbeat_logits_sha256':hashlib.sha256(down.astype('<f8').tobytes()).hexdigest()},
        'resources':{'transition_comparisons':0,'start_comparisons':0,'completed_endpoints':0,
            'beam_tie_truncation_endpoints':0,'discarded_cutoff_ties_lower_bound':0}}
    def finish(status):
        base['status']=status;base['resources']['cpu_seconds']=time.process_time()-started
        return base
    if guide_bpm is not None and window['status']!='found':return finish('guide_window_unresolved')
    if not endpoint_count or not (np.any(beat[:endpoint_count]>0) or np.any(down[:endpoint_count]>0)):
        return finish('insufficient_positive_event_evidence')
    if np.ptp(beat[:endpoint_count])==0 and np.ptp(down[:endpoint_count])==0:
        base['diagnostics']['temporal_information_absent']=True
        return finish('ambiguous_no_temporal_discrimination')
    preliminary_bytes=(endpoint_count+1)*config.beam_width*(8*8+6*8)
    if preliminary_bytes>config.max_working_memory_bytes:
        base['resources']['estimated_working_memory_bytes']=preliminary_bytes
        base['resources']['working_memory_scope']='lattice storage lower bound; excludes caller/runtime/model memory'
        return finish('budget_exceeded_memory')
    bounds=[]
    for index in range(len(TEMPLATES)):
        _,quarters,offsets=_template_geometry(index)
        lower=max(len(offsets),int(math.ceil(60*quarters*fps/config.max_quarter_bpm)))
        upper=min(int(math.floor(60*quarters*fps/config.min_quarter_bpm)),int(math.floor(config.max_bar_seconds*fps)))
        bounds.append((index,quarters,lower,upper))
    duration_state_count=sum(max(0,upper-lower+1) for _,_,lower,upper in bounds)
    preliminary_bytes+=duration_state_count*config.beam_width*8*18
    if preliminary_bytes>config.max_working_memory_bytes:
        base['resources']['estimated_working_memory_bytes']=preliminary_bytes
        base['resources']['working_memory_scope']='lattice and proposed duration-work estimate, checked before vocabulary allocation'
        return finish('budget_exceeded_memory')
    templates=[];durations=[];rates=[]
    for index,quarters,lower,upper in bounds:
        for bar_frames in range(lower,upper+1):
            templates.append(index);durations.append(bar_frames);rates.append(60*quarters*fps/bar_frames)
    template=np.asarray(templates,dtype=np.int16);bar_frames=np.asarray(durations,dtype=np.int32);rate=np.asarray(rates,dtype=float)
    if not len(rate):return finish('unsupported_empty_duration_vocabulary')
    width=config.beam_width;shape=(endpoint_count+1,width)
    # Eight float matrices, six integer matrices and bounded per-endpoint work.
    estimate=int(np.prod(shape))*(8*8+6*8)+len(rate)*width*8*18
    base['resources']['estimated_working_memory_bytes']=estimate
    base['resources']['working_memory_scope']='allocated lattice plus bounded work estimate; excludes caller/runtime/model memory'
    if estimate>config.max_working_memory_bytes:return finish('budget_exceeded_memory')
    score=np.full(shape,-np.inf);rates_at=np.zeros(shape);templates_at=np.full(shape,-1,dtype=np.int16)
    previous_end=np.full(shape,-1,dtype=np.int32);previous_slot=np.full(shape,-1,dtype=np.int16)
    duration_at=np.zeros(shape,dtype=np.int32);unit_at=np.full(shape,-1,dtype=np.int8)
    path_start=np.zeros(shape,dtype=np.int32);bars_at=np.zeros(shape,dtype=np.int32)
    components=np.zeros((*shape,5),dtype=float) # beat,downbeat,tempo,template,guide
    guide_start=window['start_seconds'] if guide_bpm is not None else None
    guide_end=window['end_seconds'] if guide_bpm is not None else None
    guide_width=(guide_end-guide_start) if guide_bpm is not None else None
    units=range(4) if guide_bpm is not None else (-1,)
    frame_coords=np.arange(endpoint_count+1)
    for end in range(1,endpoint_count+1):
        if time.process_time()-started>config.max_cpu_seconds:return finish('budget_exceeded_cpu')
        active=np.arange(len(bar_frames));ds=bar_frames;ts=template;rs=rate;starts=end-ds
        physical_start=starts>=0;safe_starts=np.maximum(starts,0)
        b_energy=np.zeros(len(active));d_energy=np.zeros(len(active));d_energy[physical_start]=down[starts[physical_start]]
        observed_positions=physical_start.astype(int)
        for k in range(len(TEMPLATES)):
            mask=ts==k
            if not np.any(mask):continue
            _,_,fractions=_template_geometry(k)
            indices=starts[mask,None]+np.floor(ds[mask,None]*fractions[None,:]+.5).astype(int)
            inside=(indices>=0)&(indices<endpoint_count)
            safe_indices=np.clip(indices,0,endpoint_count-1)
            b_energy[mask]=(beat[safe_indices]*inside).sum(axis=1)
            observed_positions[mask]+=inside.sum(axis=1)
        emission=b_energy+d_energy
        previous=score[safe_starts];finite=np.isfinite(previous)&physical_start[:,None]
        tempo_cost=np.zeros(previous.shape)
        np.divide(rs[:,None],rates_at[safe_starts],out=tempo_cost,where=finite)
        tempo_cost=np.where(finite,-config.tempo_transition_weight*np.abs(np.log(np.maximum(tempo_cost,1e-300))),0.)
        meter_cost=np.where(ts[:,None]!=templates_at[safe_starts],-config.template_change_cost,0.)
        common=previous+emission[:,None]+tempo_cost+meter_cost
        candidates=[]
        if guide_bpm is not None:
            overlap=np.maximum(0.,np.minimum(end/fps,guide_end)-np.maximum(starts/fps,guide_start))/guide_width
            start_allowed=(starts/fps<=guide_start)&(observed_positions>0)
            hypotheses=(-1,*units) if end/fps<=guide_start else tuple(units)
        else:
            overlap=np.zeros(len(active));start_allowed=observed_positions>0;hypotheses=(-1,)
        for h in hypotheses:
            if guide_bpm is None:
                allowed=finite;initial_allowed=start_allowed;guide_energy=np.zeros(len(active))
            elif h==-1:
                allowed=finite&(unit_at[safe_starts]==-1)&(overlap[:,None]==0)
                initial_allowed=start_allowed&(overlap==0);guide_energy=np.zeros(len(active))
            else:
                allowed=finite&((unit_at[safe_starts]==h)|((unit_at[safe_starts]==-1)&(overlap[:,None]>0)))
                initial_allowed=start_allowed&(overlap>0)
                guide_energy=-.5*(np.log(guide_bpm/(rs/float(GUIDE_UNITS[h])))/math.log1p(config.guide_relative_scale))**2*overlap
            base['resources']['transition_comparisons']+=int(np.count_nonzero(allowed))
            base['resources']['start_comparisons']+=int(np.count_nonzero(initial_allowed))
            if base['resources']['transition_comparisons']+base['resources']['start_comparisons']>config.max_transition_comparisons:
                return finish('budget_exceeded_transition_comparisons')
            values=np.where(allowed,common+guide_energy[:,None],-np.inf)
            for flat in _top(values,width):
                i,j=divmod(flat,width);candidates.append((float(values[i,j]),i,j,h,False,float(guide_energy[i])))
            initial=np.where(initial_allowed,emission+guide_energy,-np.inf)
            for i in _top(initial,width):candidates.append((float(initial[i]),i,-1,h,True,float(guide_energy[i])))
        if not candidates:continue
        # Stable tie order is only serialization, never a uniqueness assertion.
        candidates.sort(key=lambda x:(-x[0],int(ts[x[1]]),int(ds[x[1]]),x[3],x[4],x[2]))
        if len(candidates)>width:
            cutoff=candidates[width-1][0]
            tied=sum(abs(c[0]-cutoff)<=1e-9 for c in candidates[width:])
            if tied:base['resources']['beam_tie_truncation_endpoints']+=1;base['resources']['discarded_cutoff_ties_lower_bound']+=tied
        for slot,(value,i,j,h,initial,guide_energy) in enumerate(candidates[:width]):
            start=int(starts[i]);score[end,slot]=value;rates_at[end,slot]=rs[i];templates_at[end,slot]=ts[i]
            previous_end[end,slot]=-1 if initial else start;previous_slot[end,slot]=j;duration_at[end,slot]=ds[i];unit_at[end,slot]=h
            path_start[end,slot]=start if initial else path_start[start,j];bars_at[end,slot]=1 if initial else bars_at[start,j]+1
            increment=np.array([b_energy[i],d_energy[i],0. if initial else tempo_cost[i,j],0. if initial else meter_cost[i,j],guide_energy])
            components[end,slot]=increment if initial else components[start,j]+increment
        base['resources']['completed_endpoints']=end
    final=score.copy()
    if guide_bpm is not None:
        final[(frame_coords/fps<guide_end),:]=-np.inf
        final[path_start/fps>guide_start]=-np.inf
        final[unit_at<0]=-np.inf
    finalists=_top(final,max(config.max_alternatives,width))
    finalists.sort(key=lambda f:(-float(final.ravel()[f]),-(f//width),f%width))
    finalists=[f for f in finalists if final.ravel()[f]>0]
    if not finalists:return finish('no_supported_positive_score_path')

    def decode(flat):
        endpoint,slot=divmod(flat,width);last_endpoint,last_slot=endpoint,slot;path=[]
        total=components[endpoint,slot].copy();h=int(unit_at[endpoint,slot])
        while endpoint>=0:
            k=int(templates_at[endpoint,slot]);ds=int(duration_at[endpoint,slot]);start=endpoint-ds
            name,numerator,denominator,groups=TEMPLATES[k]
            prior_end=int(previous_end[endpoint,slot]);prior_slot=int(previous_slot[endpoint,slot])
            increment=components[endpoint,slot].copy() if prior_end<0 else components[endpoint,slot]-components[prior_end,prior_slot]
            _,_,fractions=_template_geometry(k)
            native_frames=start+np.floor(ds*fractions+.5).astype(int)
            path.append({'template_id':name,'numerator':numerator,'denominator':denominator,'grouping':list(groups),
                'source_start_seconds':start/fps,'source_end_seconds':endpoint/fps,'logit_start_frame':start,'logit_end_frame':endpoint,
                'quarter_bpm':float(rates_at[endpoint,slot]),'primary_group_source_seconds':(start/fps+ds/fps*fractions).tolist(),
                'native_primary_sample_frames':native_frames[(native_frames>=0)&(native_frames<endpoint_count)].tolist(),
                'censored_primary_sample_frames':native_frames[(native_frames<0)|(native_frames>=endpoint_count)].tolist(),
                'downbeat_emission_censored':start<0,
                'local_score_components':dict(zip(('beat','downbeat','tempo_prior','template_prior','guide'),increment.tolist()))})
            endpoint,slot=prior_end,prior_slot
        path.reverse();q=0.;knots=[{'pulse':0.,'source_seconds':path[0]['source_start_seconds']}];meters=[]
        for bar in path:
            signature=(bar['numerator'],bar['denominator'],tuple(bar['grouping']))
            if not meters or signature!=(meters[-1]['numerator'],meters[-1]['denominator'],tuple(meters[-1]['grouping'])):
                meters.append({'pulse':q,'numerator':signature[0],'denominator':signature[1],'grouping':list(signature[2]),'bar_action':'continue'})
            bar['start_quarter']=q;q+=4*bar['numerator']/bar['denominator'];bar['end_quarter']=q
            knots.append({'pulse':q,'source_seconds':bar['source_end_seconds']})
        context=[path[0]['source_start_seconds'],path[-1]['source_end_seconds']]
        support=[max(0.,context[0]),min(duration,context[1])]
        declared=prepare_map({'schema_version':1,'source':source,'clock_knots':knots,
            'quarters_per_pulse':{'numerator':1,'denominator':1},'meter_events':meters,'bar_anchor_pulse':0.,'shared_origin_id':None,
            'support_seconds':[support],'analysis_condition':'user_bpm_guided' if guide_bpm is not None else 'unhinted'})
        declared.update(accepted=False,semantic_status='inferred declared hypothesis, not certified unit or authored origin')
        score_parts=dict(zip(('beat','downbeat','tempo_prior','template_prior','guide'),total.tolist()))
        score_parts.update(data=score_parts['beat']+score_parts['downbeat'],total=float(final[last_endpoint,last_slot]),calibrated_confidence=False)
        return {'map':declared,'path':path,'score_components':score_parts,
                'guide_unit_quarters':None if h<0 else {'numerator':GUIDE_UNITS[h].numerator,'denominator':GUIDE_UNITS[h].denominator},
                'support_seconds':support,'clock_context_seconds':context}
    decoded=[decode(f) for f in finalists[:config.max_alternatives]]
    best=decoded[0];base.update(map=best['map'],path=best['path'],score_components=best['score_components'],alternatives=decoded[1:])
    base['guide']['inferred_unit_quarters']=best['guide_unit_quarters']
    base['guide']['status']='applied_only_in_source_window' if guide_bpm is not None else 'not_provided'
    aliases=[]
    for index,bar in enumerate(best['path']):
        k=next(i for i,t in enumerate(TEMPLATES) if t[0]==bar['template_id']);_,_,mask=_template_geometry(k)
        options=[];seconds=bar['source_end_seconds']-bar['source_start_seconds']
        for other in range(len(TEMPLATES)):
            name,quarters,othermask=_template_geometry(other);bpm=60*quarters/seconds
            if len(mask)==len(othermask) and np.array_equal(mask,othermask) and config.min_quarter_bpm<=bpm<=config.max_quarter_bpm:
                options.append({'template_id':name,'quarter_bpm':bpm,'identical_primary_and_downbeat_observation_mask':True})
        if len(options)>1:aliases.append({'bar_index':index,'same_data_score_alternatives':options})
    base['diagnostics']['observational_template_aliases']=aliases
    base['diagnostics']['identical_mask_aliases_present']=bool(aliases)
    base['diagnostics']['no_identical_mask_alias_in_frozen_vocabulary']=not bool(aliases)
    base['diagnostics']['tie_truncation_precludes_confidence']=bool(base['resources']['beam_tie_truncation_endpoints'])
    base['diagnostics']['top_retained_score_ties']=sum(abs(v['score_components']['total']-best['score_components']['total'])<=1e-9 for v in decoded)
    a,b=best['support_seconds'];base['diagnostics']['uncovered_source_intervals']=[[x,y] for x,y in ((0.,a),(b,duration)) if y>x]
    base['diagnostics']['full_source_contract_validated']=False
    return finish('unaccepted_joint_map_hypothesis')
