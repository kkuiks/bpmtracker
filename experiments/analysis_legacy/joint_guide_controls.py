"""Finite scalar-guide selection control for saved, unresolved-unit clocks.

This does not declare native pulses to be quarters, generate a clock, infer meter
or consume reference data. ``guide_window`` must be the source-only result of
joint_music_lattice.first_stable_window, shared with the joint experiment.
One relative native-pulse-to-tap ratio is retained over the whole window.
All ratios and weights are frozen experimental assumptions, not universal
musical equivalence or a calibrated probability model.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Real
import numpy as np

NATIVE_TO_TAP_RATIOS=(Fraction(1,2),Fraction(2,3),Fraction(3,4),Fraction(1),
                     Fraction(4,3),Fraction(3,2),Fraction(2),Fraction(3),Fraction(4))


@dataclass(frozen=True)
class GuideControlConfig:
    ratios: tuple=NATIVE_TO_TAP_RATIOS
    relative_sigma: float=.02
    guide_weight: float=1.


def _finite(value,name,*,positive=False):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,Real) or not math.isfinite(value):
        raise ValueError(name+' must be a finite numeric scalar')
    value=float(value)
    if positive and value<=0:raise ValueError(name+' must be positive')
    return value


def _same(a,b):
    return abs(a-b)<=8*max(math.ulp(v) for v in (a,b,1.))


def _configuration(config):
    config=config or GuideControlConfig()
    _finite(config.relative_sigma,'relative_sigma',positive=True)
    if _finite(config.guide_weight,'guide_weight')<0:raise ValueError('guide_weight must be nonnegative')
    ratios=[]
    for value in config.ratios:
        if isinstance(value,(bool,np.bool_)):raise ValueError('ratios must be positive rational values')
        ratio=Fraction(value)
        if ratio<=0:raise ValueError('ratios must be positive')
        if ratio in ratios:raise ValueError('ratios must be unique')
        ratios.append(ratio)
    if not ratios:raise ValueError('at least one ratio is required')
    return config,ratios


def _ratio_dict(value):return {'numerator':value.numerator,'denominator':value.denominator}


def _window(guide_window):
    if not isinstance(guide_window,dict):raise ValueError('guide_window must be the source-derived helper result')
    if guide_window.get('status')=='guide_window_unresolved':return None
    if guide_window.get('status')!='found':raise ValueError('unrecognized guide-window status')
    lo=_finite(guide_window.get('start_seconds'),'guide window start')
    hi=_finite(guide_window.get('end_seconds'),'guide window end')
    if lo<0 or hi<=lo:raise ValueError('guide window must increase on the physical source')
    span=guide_window.get('source_support_seconds')
    if span is not None and (len(span)!=2 or not _same(float(span[0]),lo) or not _same(float(span[1]),hi)):
        raise ValueError('guide window fields disagree')
    return lo,hi


def _rate_pieces(candidate,window):
    clock=candidate.get('clock')
    if not clock or not clock.get('segments'):return None,'unavailable_clock'
    lo,hi=window
    for span in (clock.get('support_seconds'),candidate.get('fitted_clock_support_seconds'),
                 candidate.get('source_support_seconds'),candidate.get('source_window_seconds')):
        if span is None:continue
        if len(span)!=2:raise ValueError('invalid declared clock support')
        a,b=(_finite(x,'support endpoint') for x in span)
        if b<=a:raise ValueError('invalid declared clock support')
        if (lo<a and not _same(lo,a)) or (hi>b and not _same(hi,b)):
            return None,'guide_window_not_fully_supported'
    segments=[];previous=None
    for item in clock['segments']:
        a=_finite(item.get('start_seconds'),'segment start');b=_finite(item.get('end_seconds'),'segment end')
        rate=_finite(item.get('pulse_rate_per_minute'),'native pulse rate',positive=True)
        if b<=a:raise ValueError('clock segments must increase')
        if previous is not None and a<previous and not _same(a,previous):raise ValueError('clock segments overlap or are unordered')
        previous=b
        if b>lo and a<hi:segments.append((max(a,lo),min(b,hi),rate))
    cursor=lo;pieces=[]
    for a,b,rate in segments:
        if a>cursor and not _same(a,cursor):return None,'guide_window_not_fully_supported'
        a=max(cursor,a);width=b-a
        if width>0:pieces.append({'start_seconds':a,'end_seconds':b,'native_pulse_rate_per_minute':rate,'duration_seconds':width})
        cursor=max(cursor,b)
    if cursor<hi and not _same(cursor,hi):return None,'guide_window_not_fully_supported'
    if not pieces:return None,'guide_window_not_fully_supported'
    return pieces,None


def guided_candidate_selection(candidates,guide_bpm,guide_window,*,config=None):
    """Return saved-ID selection, fixed-ratio scores, ambiguity and availability.

    Inputs are not modified. ``guide_bpm`` is a scalar only: no note unit, meter,
    phase, reference or source-window input is accepted from the user. Candidate
    clocks remain native-coordinate proposals; only their ranking may change.
    """
    guide=_finite(guide_bpm,'guide_bpm',positive=True);config,ratios=_configuration(config);window=_window(guide_window)
    if not isinstance(candidates,list):raise ValueError('candidates must be the saved candidate list')
    ids=[c.get('id') for c in candidates]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):raise ValueError('candidate IDs must be unique nonempty strings')
    result={'schema_version':1,'status':'pending','selected_candidate_id':None,'tied_selected_candidate_ids':[],
        'guide_bpm':guide,'guide_window':guide_window,'quarter_unit_assigned':False,'meter_inferred':False,
        'clock_modified':False,'full_music_map_available':False,'reference_used':False,
        'configuration':{'native_to_tap_ratios':[_ratio_dict(r) for r in ratios],
            'relative_sigma':config.relative_sigma,'guide_weight':config.guide_weight,
            'scope':'finite conditional relative-rate selection control, not unrestricted note-unit inference'},
        'candidate_rows':[],'legacy_best_candidate_id':None}
    for candidate in candidates:
        row={'candidate_id':candidate['id'],'status':'pending','ratio_scores':[]}
        try:
            legacy=_finite(candidate.get('evidence_score_not_confidence'),'saved evidence score')
            row['saved_evidence_score_not_confidence']=legacy
            if window is None:row['status']='guide_window_unresolved'
            else:
                pieces,reason=_rate_pieces(candidate,window)
                if reason:row['status']=reason
                else:
                    duration=window[1]-window[0];sigma=math.log1p(config.relative_sigma)
                    for ratio in ratios:
                        terms=[p['duration_seconds']/duration * -.5*(math.log(guide/(p['native_pulse_rate_per_minute']*float(ratio)))/sigma)**2 for p in pieces]
                        penalty=math.fsum(terms)
                        row['ratio_scores'].append({'native_to_tap_ratio':_ratio_dict(ratio),'guide_penalty':penalty})
                    best=max(r['guide_penalty'] for r in row['ratio_scores'])
                    row.update(status='scored',guide_penalty=best,
                        total_score_not_confidence=legacy+config.guide_weight*best,
                        tied_best_native_to_tap_ratios=[r['native_to_tap_ratio'] for r in row['ratio_scores'] if _same(r['guide_penalty'],best)],
                        guide_window_native_rate_pieces=pieces,
                        guide_window_time_weighted_native_rate=math.fsum(p['duration_seconds']*p['native_pulse_rate_per_minute'] for p in pieces)/duration,
                        unit_ambiguity_scope='relative ratio only; neither native nor tapped pulse is assigned a musical note unit')
        except (ValueError,TypeError,KeyError,OverflowError) as error:
            row.update(status='invalid_candidate_declaration',reason=str(error))
        result['candidate_rows'].append(row)
    legacy_rows=[r for r in result['candidate_rows'] if 'saved_evidence_score_not_confidence' in r]
    if legacy_rows:result['legacy_best_candidate_id']=max(legacy_rows,key=lambda r:r['saved_evidence_score_not_confidence'])['candidate_id']
    eligible=[r for r in result['candidate_rows'] if r['status']=='scored']
    if eligible:
        selected=max(eligible,key=lambda r:r['total_score_not_confidence']);best=selected['total_score_not_confidence']
        result.update(status='selected_saved_candidate',selected_candidate_id=selected['candidate_id'],
            tied_selected_candidate_ids=[r['candidate_id'] for r in eligible if _same(r['total_score_not_confidence'],best)])
    else:result['status']='empty_candidate_pool' if not candidates else ('guide_window_unresolved' if window is None else 'no_candidate_covers_guide_window')
    return result


def grouping_observation_contrast(beat_logits,downbeat_logits,fps,bar_intervals,*,shared_primary_phases=None):
    """Source-only score decomposition on declared INFERRED bar geometry.

    This is not an inference winner or a reference-scored metric. Native evidence
    is sampled from the original integer native-bar geometry (positive half-up internal ties, matching the lattice). Default masks contrast
    primary-role3/4 against6/8 on identical bars. ``shared_primary_phases`` is a
    free-role countercontrol: assigning the same observation mask must yield the
    same acoustic score, even when the metrical names differ. No guide, reference
    or meter truth is consumed. The caller must retain inferred-geometry origin.
    """
    beat=np.asarray(beat_logits,dtype=float);down=np.asarray(downbeat_logits,dtype=float)
    fps=_finite(fps,'fps',positive=True)
    if beat.ndim!=1 or down.shape!=beat.shape or not len(beat) or not np.isfinite(beat).all() or not np.isfinite(down).all():raise ValueError('invalid native evidence')
    if shared_primary_phases is not None:
        shared=[_finite(p,'primary phase') for p in shared_primary_phases]
        if not shared or any(p<0 or p>=1 for p in shared) or any(b<=a for a,b in zip(shared,shared[1:])):raise ValueError('invalid shared primary phases')
        masks={'3/4':shared,'6/8':shared}
    else:masks={'3/4':[0.,1/3,2/3],'6/8':[0.,.5]}
    def endpoint_frame(seconds):
        position=seconds*fps;index=round(position)
        if abs(position-index)>8*max(math.ulp(position),math.ulp(1.)):
            raise ValueError('countercontrol requires native-frame lattice bar endpoints')
        if index>len(beat):raise ValueError('bar geometry exceeds native evidence')
        return index
    rows=[]
    for interval in bar_intervals:
        if len(interval)!=2:raise ValueError('bar interval must have two endpoints')
        lo,hi=(_finite(v,'bar endpoint') for v in interval)
        if hi<=lo:raise ValueError('invalid inferred bar interval')
        first,last=endpoint_frame(lo),endpoint_frame(hi)
        values={}
        for meter,phases in masks.items():
            indices=[first+math.floor((last-first)*p+.5) for p in phases]
            if any(i>=last or i>=len(beat) for i in indices):raise ValueError('template exceeds the half-open native bar')
            if len(set(indices))!=len(indices):raise ValueError('template events collide at native-frame resolution')
            observed=[i for i in indices if i>=0]
            beat_score=math.fsum(float(beat[i]) for i in observed);down_score=float(down[first]) if first>=0 else 0.
            values[meter]={'beat_score':beat_score,'downbeat_score':down_score,'total_score_not_confidence':beat_score+down_score,
                'native_frame_indices':observed,'censored_pre_source_primary_count':len(indices)-len(observed),
                'downbeat_pre_source_censored':first<0,'physical_observation_count':len(observed)+int(first>=0)}
        rows.append({'inferred_bar_seconds':[lo,hi],'inferred_bar_frames':[first,last],'hypotheses':values,
            'acoustic_score_difference_3_4_minus_6_8':values['3/4']['total_score_not_confidence']-values['6/8']['total_score_not_confidence']})
    observed_any=any(v['physical_observation_count'] for r in rows for v in r['hypotheses'].values())
    return {'status':('diagnostic_only' if observed_any else 'no_physical_observations') if rows else 'no_inferred_bar_geometry','mode':'free_role_identical_mask' if shared_primary_phases is not None else 'fixed_primary_role',
        'reference_used':False,'guide_used':False,'bar_geometry_origin_required':'caller inferred output, never reference input',
        'all_acoustic_scores_tied':all(_same(r['acoustic_score_difference_3_4_minus_6_8'],0.) for r in rows) if observed_any else None,
        'negative_clock_context':'preserved geometrically; pre-source observation samples censored',
        'rows':rows,'limitation':'This compares declared observation roles, not general meter identifiability or calibrated confidence.'}
