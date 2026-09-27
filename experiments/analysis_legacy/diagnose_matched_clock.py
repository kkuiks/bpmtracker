"""Paired C2/C3 oracle diagnostics on uniquely matched saved peak subsets.

All arms use reference-selected subsets. They are not automatic performance.
Only existing frozen v1 fitting is executed; no reference/audio alignment,
new model, threshold tuning, or fitted reference clock is introduced.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left,bisect_right
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')

import numpy as np
from run_crossed_benchmark import fit_prediction
from fit_clock import clock_time
from music_map_contract import interpolate_clock
from music_map_reference_adapters import _declared_clock, ALLOWED_KINDS

TOLERANCES=(.020,.070)
QUARTER_PARITY_SECONDS=1e-8
FIT_CONFIGURATION={'min_input_events':8,'max_input_events':2000,'min_events_per_initial_segment':8,
 'max_initial_segments':12,'split_penalty_seconds_squared':.01,'continuous_selection':False,
 'callable':'run_crossed_benchmark.fit_prediction (existing ablate_clock_inputs.fit_prediction alias)',
 'fallback':'preserve returned event list; no clock result is never called a successful fit'}
DEPENDENCIES=['diagnose_matched_clock.py','run_crossed_benchmark.py','ablate_clock_inputs.py','fit_clock.py',
 'run_beat_this.py','music_map_contract.py','music_map_reference_adapters.py','musical_units.py']
DEFAULT_COHORT=Path('data/runs/music-map-contract/2026-09-26-v1/prediction-capabilities.json')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(path)


def events(value,label):
    values=np.asarray(value,dtype=float)
    if values.ndim!=1 or not np.isfinite(values).all() or np.any(np.diff(values)<=0):
        raise ValueError(f'{label} must be finite, ordered, unique event times')
    return values


def unique_correspondence(reference_times,prediction_times,tolerance):
    """A pair is admitted only if each endpoint has exactly one possible partner."""
    ref=events(reference_times,'reference');pred=events(prediction_times,'prediction')
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('nonnegative finite tolerance required')
    def neighbors(a,b):
        found=[]
        for t in a:
            lower,upper=t-tolerance,t+tolerance
            edge_ulp=8*max(math.ulp(float(v)) for v in (t,lower,upper,tolerance))
            indices=[]
            for j in range(bisect_left(b,lower-edge_ulp),bisect_right(b,upper+edge_ulp)):
                comparison_ulp=8*max(math.ulp(float(t)),math.ulp(float(b[j])),math.ulp(float(tolerance)))
                if abs(b[j]-t)<=tolerance+comparison_ulp:indices.append(j)
            found.append(indices)
        return found
    rn=neighbors(ref,pred);pn=neighbors(pred,ref)
    pairs=[(i,n[0]) for i,n in enumerate(rn) if len(n)==1 and len(pn[n[0]])==1]
    paired_ref={i for i,j in pairs};paired_pred={j for i,j in pairs}
    return {'pairs':[{'reference_index':i,'prediction_index':j} for i,j in pairs],
        'reference_count':len(ref),'prediction_count':len(pred),'matched_count':len(pairs),
        'unpaired_reference_count':len(ref)-len(paired_ref),'unpaired_prediction_count':len(pred)-len(paired_pred),
        'reference_without_nearby_prediction_count':sum(not n for n in rn),
        'prediction_without_nearby_reference_count':sum(not n for n in pn),
        'ambiguity_excluded_reference_count':sum(i not in paired_ref and bool(n) for i,n in enumerate(rn)),
        'ambiguity_excluded_prediction_count':sum(i not in paired_pred and bool(n) for i,n in enumerate(pn)),
        'reference_neighbor_counts':[len(n) for n in rn],'prediction_neighbor_counts':[len(n) for n in pn],
        'criterion':'exactly one neighbor in each direction, inclusive absolute-time tolerance plus8ULP numeric-boundary inclusion only; no optimization/shift',
        'tolerance_seconds':tolerance}


def _numerical_interpolate(knots,value,*,inverse=False):
    """Clamp only floating endpoint representation, never a musical tolerance."""
    key='source_seconds' if inverse else 'pulse'
    lo,hi=knots[0][key],knots[-1][key]
    epsilon=32*max(math.ulp(float(value)),math.ulp(float(lo)),math.ulp(float(hi)))
    if value<lo and lo-value<=epsilon:value=lo
    if value>hi and value-hi<=epsilon:value=hi
    return interpolate_clock(knots,value,inverse=inverse)


def reference_identity(reference):
    """Use explicit quarter IDs or validate exact integer quarters of declared MIDI."""
    times=events(reference['beats_seconds'],'reference beats')
    explicit=reference.get('quarter_indices')
    declared_map=None;verification_map=None
    if reference.get('kind') in ALLOWED_KINDS:
        tt,qq,quarter_at,_=_declared_clock(reference)
        hi=float(reference['evaluation_support_seconds'][1])
        declared_map=[{'pulse':q,'source_seconds':t} for t,q in zip(tt,qq) if t<=hi]
        if declared_map[-1]['source_seconds']<hi:declared_map.append({'pulse':quarter_at(hi),'source_seconds':hi})
        if len(declared_map)<2:raise ValueError('declared reference clock has no positive domain')
        verification_hi=max(hi,float(times[-1]) if len(times) else hi)
        verification_map=[{'pulse':q,'source_seconds':t} for t,q in zip(tt,qq) if t<=verification_hi]
        if verification_map[-1]['source_seconds']<verification_hi:verification_map.append({'pulse':quarter_at(verification_hi),'source_seconds':verification_hi})
    if explicit is not None:
        quarters=events(explicit,'explicit reference quarter indices')
        if len(quarters)!=len(times):raise ValueError('reference quarter/time lengths differ')
        basis='explicit reference quarter_indices; preserved without musical relabeling'
    elif declared_map is not None:
        raw=np.array([_numerical_interpolate(verification_map,float(t),inverse=True) for t in times])
        quarters=np.rint(raw)
        errors=[abs(_numerical_interpolate(verification_map,float(q))-float(t)) for q,t in zip(quarters,times)]
        if max(errors,default=0)>QUARTER_PARITY_SECONDS:raise ValueError('declared beat events are not exact integer quarters of supplied map')
        basis='integer quarter identity from explicit authored MIDI tick/tempo clock; <=1e-8s numerical parity; no source-time shift'
    else:
        raise ValueError('explicit quarter identities unavailable; event ordinal is not a substitute')
    if len(quarters) and (np.max(abs(quarters-np.rint(quarters)))>1e-9 or np.any(np.diff(quarters)<1-1e-9)):
        raise ValueError('frozen v1 fitter requires distinct integer quarter identities')
    quarters=np.rint(quarters)
    if declared_map is not None:
        parity=[abs(_numerical_interpolate(verification_map,float(q))-float(t)) for q,t in zip(quarters,times)]
        if max(parity,default=0)>QUARTER_PARITY_SECONDS:raise ValueError('explicit quarter identities disagree with supplied clock times')
    elif reference.get('kind')=='creator_click_wav_with_audited_source_mapping':
        tempos=reference.get('tempo_events') or []
        if len(tempos)==1 and len(times)>=2:
            bpm=float(tempos[0]['bpm_quarter'])
            expected=times[0]+(quarters-quarters[0])*60/bpm
            if np.max(abs(expected-times))<=QUARTER_PARITY_SECONDS:
                declared_map=[{'pulse':float(quarters[0]),'source_seconds':float(times[0])},
                              {'pulse':float(quarters[-1]),'source_seconds':float(times[-1])}]
    return {'times':times,'quarters':quarters,'quarter_identity_basis':basis,'reference_clock_knots':declared_map,
        'continuous_reference_scope':('supplied authored step-clock agreement' if reference.get('kind') in ALLOWED_KINDS else 'explicit constant tempo and observed quarter/time anchor') if declared_map else 'unavailable; observed quarter events only'}


def statistics(errors):
    values=np.asarray(errors,dtype=float)
    if not len(values):return {'count':0,'signed_mean_seconds':None,'signed_median_seconds':None,'absolute_p50_seconds':None,'absolute_p95_seconds':None,'absolute_max_seconds':None,'rms_seconds':None}
    return {'count':len(values),'signed_mean_seconds':float(np.mean(values)),'signed_median_seconds':float(np.median(values)),
        'absolute_p50_seconds':float(np.quantile(abs(values),.5)),'absolute_p95_seconds':float(np.quantile(abs(values),.95)),
        'absolute_max_seconds':float(np.max(abs(values))),'rms_seconds':float(np.sqrt(np.mean(values**2)))}


def continuous_error(proposal,q0,reference_knots,domain=None):
    """Exact piecewise-linear error integral in an explicit common quarter gauge."""
    if proposal is None:return {'status':'unavailable_failed_clock'}
    if not reference_knots:return {'status':'unavailable_reference_continuous_clock'}
    lo=max(q0+proposal['pulse_index_span'][0],reference_knots[0]['pulse'])
    hi=min(q0+proposal['pulse_index_span'][1],reference_knots[-1]['pulse'])
    if domain is not None:lo,hi=max(lo,domain[0]),min(hi,domain[1])
    if hi<=lo:return {'status':'no_common_quarter_domain','domain_quarters':[lo,hi]}
    points=sorted(set([lo,hi]+[q0+k for k in proposal['knot_pulse_indices'] if lo<q0+k<hi]+[k['pulse'] for k in reference_knots if lo<k['pulse']<hi]))
    predicted=clock_time(np.array(points)-q0,proposal['knot_pulse_indices'],proposal['coefficients'])
    truth=np.array([interpolate_clock(reference_knots,q) for q in points]);error=predicted-truth
    absolute_integral=0.;square_integral=0.
    for a,b,e0,e1 in zip(points,points[1:],error,error[1:]):
        width=b-a;square_integral+=width*(e0*e0+e0*e1+e1*e1)/3
        absolute_integral+=width*((abs(e0)+abs(e1))/2 if e0*e1>=0 else (e0*e0+e1*e1)/(2*(abs(e0)+abs(e1))))
    return {'status':'scored_supplied_clock_agreement','quarter_domain':[lo,hi],'quarter_span':hi-lo,
        'weighting':'quarter-coordinate weighted; not time-weighted and not independent original-click truth',
        'mean_absolute_seconds':float(absolute_integral/(hi-lo)),'rms_seconds':float(math.sqrt(square_integral/(hi-lo))),
        'max_absolute_seconds':float(np.max(abs(error))),'integration_breakpoints_quarters':points,
        'error_seconds_at_breakpoints':error.tolist(),'source_time_shift_applied':False}


def run_fit(times,indices,q0,reference_times,reference_quarters,reference_knots):
    times=np.asarray(times,dtype=float);indices=np.asarray(indices,dtype=float)
    start=time.perf_counter()
    try:
        proposal,predicted,status=fit_prediction({'beats_seconds':times.tolist(),'downbeats_seconds':[]},pulse_indices=indices)
        execution_error=None
    except Exception as error:
        proposal=None;predicted={'beats_seconds':times.tolist(),'downbeats_seconds':[]};status='diagnostic_execution_error';execution_error=f'{type(error).__name__}: {error}'
    elapsed=time.perf_counter()-start
    result={'status':status,'execution_error':execution_error,'clock_produced':proposal is not None,'proposal':proposal,
        'fitted_or_fallback_events_seconds':predicted['beats_seconds'],'input_times_seconds':times.tolist(),'input_indices':indices.tolist(),
        'quarter_coordinate_assertion':{'absolute_q0':q0,'mapping':'q = q0 + input_index; explicit privileged diagnostic assertion, never inferred automatic unit'},
        'input_event_count':len(times),'output_event_count':len(predicted['beats_seconds']),
        'output_role':'fitted_grid' if proposal else 'fallback_input_events_no_clock',
        'missing_quarter_count_asserted':int(indices[-1]+1-len(indices)) if len(indices) else 0,
        'quarter_span_asserted':float(indices[-1]-indices[0]) if len(indices)>1 else 0.,
        'elapsed_seconds':elapsed,'process_high_water_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'fit_configuration':FIT_CONFIGURATION,'reference_assisted_diagnostic':True}
    if proposal is None:
        result['observation_fit_residual']={'status':'unavailable_failed_clock'}
        result['reference_time_error_at_paired_observations']={'status':'unavailable_failed_clock'}
        result['reference_time_error_at_true_quarter_positions']={'status':'unavailable_failed_clock'}
    else:
        fitted=clock_time(indices,proposal['knot_pulse_indices'],proposal['coefficients'])
        result['observation_fit_residual']={**statistics(fitted-times),'warning':'conditional on supplied index assignments; a good ordinal fit does not certify correct musical counting'}
        result['reference_time_error_at_paired_observations']={**statistics(fitted-reference_times),'warning':'observation correspondence retained; not structural correctness of the asserted clock coordinate'}
        true_relative=np.asarray(reference_quarters)-q0
        inside=(true_relative>=proposal['pulse_index_span'][0])&(true_relative<=proposal['pulse_index_span'][1])
        pred_truth=clock_time(true_relative[inside],proposal['knot_pulse_indices'],proposal['coefficients'])
        result['reference_time_error_at_true_quarter_positions']={**statistics(pred_truth-np.asarray(reference_times)[inside]),
            'matched_reference_queries':len(true_relative),'queries_inside_clock_domain':int(sum(inside)),
            'queries_outside_clock_domain':int(sum(~inside)),'source_time_shift_applied':False}
    result['continuous_reference_clock_error']=continuous_error(proposal,q0,reference_knots)
    return result


def paired_diagnostic(reference_times,reference_quarters,prediction_times,tolerance,*,reference_knots=None,allow_c2=True):
    ref=events(reference_times,'reference');quarters=events(reference_quarters,'quarters');pred=events(prediction_times,'predictions')
    if len(ref)!=len(quarters):raise ValueError('reference identity lengths differ')
    match=unique_correspondence(ref,pred,tolerance)
    ri=np.array([p['reference_index'] for p in match['pairs']],dtype=int);pi=np.array([p['prediction_index'] for p in match['pairs']],dtype=int)
    rt,pt,q=ref[ri],pred[pi],quarters[ri]
    q0=float(q[0]) if len(q) else None;relative=q-q0 if q0 is not None else q.copy()
    result={'matching':match,'matched_observations':[{'reference_index':int(i),'prediction_index':int(j),'reference_seconds':float(a),'prediction_seconds':float(b),'absolute_quarter':float(c),'signed_error_seconds':float(b-a)} for i,j,a,b,c in zip(ri,pi,rt,pt,q)],
        'pre_fit_timing_error':{**statistics(pt-rt),'warning':'errors are truncated by matching tolerance by construction'},
        'all_arms_reference_selected_subset':True,'no_full_baseline_attribution':True,'absolute_quarter_gauge_origin':q0,
        'source_time_shift_applied':False,'arms':{}}
    if not len(q):
        result['status']='no_unique_correspondence';return result
    arms={'quarter_indexed_model_times':(pt,relative),'quarter_indexed_reference_times':(rt,relative)}
    if allow_c2:arms={'sequential_model_times':(pt,np.arange(len(pt),dtype=float)),**arms}
    for name,(times,indices) in arms.items():result['arms'][name]=run_fit(times,indices,q0,rt,q,reference_knots)
    for name,left,right in [('C2','sequential_model_times','quarter_indexed_model_times'),('C3','quarter_indexed_model_times','quarter_indexed_reference_times')]:
        if left not in result['arms']:
            result[name]={'status':'not_in_scope_for_observed_click_reference'};continue
        a,b=result['arms'][left],result['arms'][right]
        comparison={'left':left,'right':right,'scope':'same matched subset only','same_source_times':name=='C2','same_reference_quarter_indices':name=='C3',
            'both_clocks_produced':a['clock_produced'] and b['clock_produced'],'timing_alignment_applied':False}
        if comparison['both_clocks_produced']:
            domain=[q0+max(a['proposal']['pulse_index_span'][0],b['proposal']['pulse_index_span'][0]),q0+min(a['proposal']['pulse_index_span'][1],b['proposal']['pulse_index_span'][1])]
            comparison['common_quarter_domain']=domain
            comparison['left_common_domain_error']=continuous_error(a['proposal'],q0,reference_knots,domain)
            comparison['right_common_domain_error']=continuous_error(b['proposal'],q0,reference_knots,domain)
        result[name]=comparison
    result['status']='diagnostic_complete';return result


def freeze_inputs(cohort_path,output_dir):
    cohort_path,output_dir=Path(cohort_path),Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):raise FileExistsError('diagnostic output must be new or empty')
    output_dir.mkdir(parents=True,exist_ok=True)
    catalog=json.loads(cohort_path.read_text());cohort=catalog['proposed_fixed_diagnostic_cohort']
    input_hashes={str(cohort_path):sha(cohort_path)};cases=[]
    for track in cohort:
        ref=track['reference'];path=Path(ref['path'])
        if sha(path)!=ref['sha256']:raise ValueError(f'reference artifact changed: {path}')
        input_hashes[str(path)]=ref['sha256']
        ledger=Path(track['reference_record_path'])
        if sha(ledger)!=track['reference_record_sha256']:raise ValueError('qualification ledger changed')
        input_hashes[str(ledger)]=track['reference_record_sha256']
        admission=next((r for r in json.loads(ledger.read_text())['tracks'] if r['id']==track['id']),None)
        if not admission or not admission.get('retained_for_primary_scores'):raise ValueError('diagnostic reference is not retained by qualified ledger')
        reference_payload=json.loads(Path(ref['path']).read_text())
        for item in track['prediction_inputs']:
            path=Path(item['path'])
            if sha(path)!=item['sha256']:raise ValueError(f'prediction artifact changed: {path}')
            input_hashes[str(path)]=item['sha256'];core=json.loads(path.read_text())
            if core.get('id')!=track['id'] or core.get('model')!=item['model']:raise ValueError('core case identity disagrees with frozen cohort')
            if reference_payload.get('source_audio_sha256') not in {core['source'].get('sha256'),core['source'].get('original_sha256')}:raise ValueError('reference/audio source identity mismatch')
            if core.get('references_used_for_prediction'):raise ValueError('matched acoustic seed must be an original reference-free prediction')
            if 'common_minimal' not in core['methods']:raise ValueError('frozen common minimal seed missing')
            cases.append({'id':track['id'],'role':track['role'],'model':item['model'],'reference':ref,'prediction':item,
                'support_seconds':track['source_evaluation_support_seconds'],'reference_tier':track['reference_tier'],'reference_caveats':track['reference_caveats'],
                'source':core['source'],'model_configuration':core.get('model_configuration'),
                'official_events_equal_common_minimal':core['methods'].get('official',{}).get('prediction',{}).get('beats_seconds')==core['methods']['common_minimal']['prediction']['beats_seconds']})
    source_hashes={name:sha(Path(__file__).with_name(name)) for name in DEPENDENCIES}
    snapshot=output_dir/'source-snapshot';snapshot.mkdir()
    for name in DEPENDENCIES:shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    configuration={'schema_version':1,'cohort_path':str(cohort_path),'track_count':len(cohort),'model_case_count':len(cases),'tolerances_seconds':TOLERANCES,
        'seed_method':'common_minimal','seed_reason':'same saved threshold/maxima seed used by current candidate generation for both acoustic models; native Beat Transformer DBN is not substituted',
        'matching_boundary_policy':'8ULP only in candidate bounds and inclusive comparison; no fixed tolerance inflation',
        'fit_configuration':FIT_CONFIGURATION,'source_hashes':source_hashes,'input_hashes':input_hashes,'cases':cases,
        'frozen_before_execution':True,'all_results_diagnostic_only':True,'configuration_tuned_after_results':False,
        'quarter_gauge':'same first matched declared reference quarter in all paired arms; coordinate rebase only, no source-time shift',
        'known_reference_timing_limits':'NTM compares approved supplied map only; no independent original-click millisecond bound',
        'observed_click_forestry_scope':'C3only with explicit quarter_indices; no continuous reference clock invented'}
    write_json(output_dir/'configuration.json',configuration)
    write_json(output_dir/'manifest.json',{'configuration_sha256':sha(output_dir/'configuration.json'),'state':'frozen_before_execution','rows':[],'complete':False})
    return configuration


def run(output_dir,cohort_path=DEFAULT_COHORT):
    output_dir=Path(output_dir);config=freeze_inputs(cohort_path,output_dir)
    manifest={'configuration_sha256':sha(output_dir/'configuration.json'),'state':'running','rows':[],'complete':False}
    for case in config['cases']:
        row={'id':case['id'],'model':case['model'],'role':case['role'],'reference_assisted_diagnostic':True,'evidence_scope':'agreement with supplied reference identities and timing; not automatic whole-song performance'}
        try:
            reference=json.loads(Path(case['reference']['path']).read_text());core=json.loads(Path(case['prediction']['path']).read_text())
            identity=reference_identity(reference);lo,hi=case['support_seconds']
            keep=(identity['times']>=lo)&(identity['times']<=hi);native=events(core['methods']['common_minimal']['prediction']['beats_seconds'],'saved common minimal')
            predkeep=(native>=lo)&(native<=hi)
            row.update(reference_kind=reference.get('kind'),quarter_identity_basis=identity['quarter_identity_basis'],continuous_reference_scope=identity['continuous_reference_scope'],
                reference_support_seconds=[lo,hi],reference_events_outside_support=int(sum(~keep)),native_predictions_outside_reference_support=int(sum(~predkeep)),
                timing_precision_warning='owner-approved supplied map; independently certified original-click timing error unknown' if reference.get('kind')=='owner_accepted_producer_tempo_map' else reference.get('annotation_caveat'),
                trials={})
            for tolerance in TOLERANCES:
                row['trials'][f'{tolerance*1000:g}ms']=paired_diagnostic(identity['times'][keep],identity['quarters'][keep],native[predkeep],tolerance,
                    reference_knots=identity['reference_clock_knots'],allow_c2=reference.get('kind')!='observed_creator_click_quarters')
            row['status']='completed'
        except Exception as error:
            row['status']='blocked_or_error';row['error']=f'{type(error).__name__}: {error}'
        path=output_dir/'tracks'/case['id']/(case['model']+'.json');write_json(path,row)
        manifest['rows'].append({'id':case['id'],'model':case['model'],'status':row['status'],'path':str(path),'sha256':sha(path)})
        write_json(output_dir/'manifest.json',manifest)
        print(case['id'],case['model'],row['status'],flush=True)
    changed=[path for path,digest in config['input_hashes'].items() if sha(path)!=digest]
    changed += [name for name,digest in config['source_hashes'].items() if sha(Path(__file__).with_name(name))!=digest]
    manifest.update(complete=True,state='complete' if not changed else 'invalidated_inputs_changed',changed_inputs=changed,
        status_counts={s:sum(r['status']==s for r in manifest['rows']) for s in sorted({r['status'] for r in manifest['rows']})})
    write_json(output_dir/'manifest.json',manifest);return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cohort',type=Path,default=DEFAULT_COHORT);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();result=run(a.output_dir,a.cohort);print(json.dumps(result['status_counts']))
    if result['changed_inputs'] or result['status_counts'].get('blocked_or_error'):raise SystemExit(1)


if __name__=='__main__':main()
