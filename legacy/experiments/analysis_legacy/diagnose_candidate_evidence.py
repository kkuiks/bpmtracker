"""C5 saved-candidate and C6 native-score diagnostics, with no inference/decoding.

Run ``prepare`` before ``execute``. Frozen files, configuration and dependencies
are checked before and after execution. Whole-source and region pools stay
separate. Event scores retain the old canonical-quarter definition. Oracles use
references and are diagnostic only. Native-score ranks/peaks describe position,
not calibrated confidence, signal strength or musical correctness.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from grid_metrics import nearest_event_diagnostics

DEFAULT_CAPABILITIES=Path('data/runs/music-map-contract/2026-09-26-v1/prediction-capabilities.json')
DEFAULT_OUTPUT=Path('data/runs/failure-localization/2026-09-26-v1/candidate-evidence')
CORE=Path('data/runs/logic-maintenance/2026-09-26-v1/after-correctness/core-paths-v2')
REGIONS=CORE.parent/'region-paths'
PROFILES={'20ms':.02,'70ms':.07}
WINDOW_SECONDS=.07


def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()
def file_record(path):
    path=Path(path)
    return {'path':str(path),'exists':path.is_file(),'sha256':digest(path) if path.is_file() else None}
def verify_files(records):
    for record in records:
        path=Path(record['path'])
        if path.is_file()!=record['exists'] or (record['exists'] and digest(path)!=record['sha256']):
            raise ValueError('frozen input changed: '+str(path))


def event_scores(reference,times,support=None):
    lo,hi=support or reference['evaluation_support_seconds']
    truth=[v for v in reference['beats_seconds'] if lo<=v<=hi]
    predicted=[v for v in times if lo<=v<=hi]
    return {label:nearest_event_diagnostics(truth,predicted,tolerance) for label,tolerance in PROFILES.items()}
def summarize_metrics(metrics):
    return {label:{key:values[key] for key in ('true_positives','false_positives','false_negatives','precision','recall','f1')}
            for label,values in metrics.items()}
def candidate_support(candidate,duration):
    span=candidate.get('source_support_seconds') or candidate.get('fitted_clock_support_seconds') or (candidate.get('clock') or {}).get('support_seconds')
    if span is None or len(span)!=2:return None
    lo,hi=max(0.,float(span[0])),min(duration,float(span[1]))
    return [lo,hi] if hi>lo else None


def score_pool(reference,pool,duration,*,family,cached_scores=None,cache_origin=None):
    if pool is None:
        return {'status':'missing_pool','family':family,'candidate_count':None,'automatic':None,'oracle_diagnostic':None,'full_map_accuracy':None}
    if duration<=0:raise ValueError('candidate pool requires known source duration')
    candidates=pool.get('candidates',[]);ids=[c['id'] for c in candidates];selected_id=pool.get('selected_candidate_id')
    if len(set(ids))!=len(ids):raise ValueError('duplicate candidate IDs')
    if selected_id is not None and selected_id not in ids:raise ValueError('selected candidate not in frozen pool')
    rows=[];modes=Counter();lo,hi=reference['evaluation_support_seconds']
    for candidate in candidates:
        times=[e['source_seconds'] for e in candidate['indexed_grid']];span=candidate_support(candidate,duration)
        local_span=[max(lo,span[0]),min(hi,span[1])] if span else None
        if local_span and local_span[1]<=local_span[0]:local_span=None
        cached=(cached_scores or {}).get(candidate['id'])
        if cached is not None:
            whole={label:cached['whole_annotation_diagnostic']['event_'+label] for label in PROFILES}
            old_local=cached.get('within_proposed_region_diagnostic')
            local={label:old_local['event_'+label] for label in PROFILES} if old_local else None
            if cached.get('compute_uncached_local') and local_span:local=event_scores(reference,times,local_span)
            mode='reused_exact_bound_whole_scores'+('_fresh_local_support_score' if cached.get('compute_uncached_local') else '_and_local_scores')
        else:
            whole=event_scores(reference,times);local=event_scores(reference,times,local_span) if local_span else None
            mode='fresh_fixed_event_scoring_only'
        modes[mode]+=1;overlap=max(0.,min(hi,span[1])-max(lo,span[0])) if span else 0.
        rows.append({'candidate_id':candidate['id'],'automatic_selected':candidate['id']==selected_id,'score_origin':mode,
            'cached_score_origin':cache_origin if cached is not None else None,
            'whole_annotation_diagnostic':summarize_metrics(whole),
            'within_proposed_support_diagnostic':summarize_metrics(local) if local else None,
            'candidate_source_support_seconds':span,'local_evaluation_support_seconds':local_span,
            'source_duration_fraction':(span[1]-span[0])/duration if span else None,
            'reference_duration_fraction':overlap/(hi-lo) if hi>lo else None,
            'emitted_event_count':len(times),'emitted_event_span_seconds':[times[0],times[-1]] if times else None,
            'meter':candidate.get('meter'),'quarter_unit':candidate.get('quarter_unit'),
            'musical_index_origin':candidate.get('musical_index_origin'),'full_music_map_available':False})
    selected=next((r for r in rows if r['candidate_id']==selected_id),None)
    oracle={'diagnostic_only':True,'reference_used_for_choice':True,
        'scope':'best saved finite-pool canonical-quarter event F1, not attainable full-map accuracy','profiles':{}}
    for label in PROFILES:
        best=max((r['whole_annotation_diagnostic'][label]['f1'] for r in rows),default=None)
        actual=selected['whole_annotation_diagnostic'][label]['f1'] if selected else None
        oracle['profiles'][label]={'best_f1':best,'tied_best_candidate_ids':[r['candidate_id'] for r in rows if r['whole_annotation_diagnostic'][label]['f1']==best],
            'automatic_selected_f1':actual,'gap_from_automatic':best-actual if best is not None and actual is not None else None}
    return {'status':'scored_pool' if candidates else 'empty_pool','family':family,'candidate_count':len(rows),
        'selected_candidate_id':selected_id,'selection_status':pool.get('selection_status'),
        'ranking_policy':pool.get('ranking_policy','preserved_in_saved_generator'),
        'automatic':{'candidate_id':selected_id,'status':'saved_automatic_selection' if selected else 'no_selected_candidate',
                     'scores':selected['whole_annotation_diagnostic'] if selected else summarize_metrics(event_scores(reference,[]))},
        'candidate_rows':rows,'score_modes':dict(modes),'oracle_diagnostic':oracle,'full_map_accuracy':None,
        'partial_region_family':family=='partial_regions','reference_used_to_change_predictions':False}


def cache_binding(score,prediction_hash,reference_hash,evaluator_hashes_match):
    return bool(evaluator_hashes_match and score.get('prediction_sha256')==prediction_hash and
        (score.get('reference') or {}).get('sha256')==reference_hash and score.get('scores'))
def eligible_region_cache(score,prediction_hash,reference_hash,pool,evaluator_hashes_match):
    if not cache_binding(score,prediction_hash,reference_hash,evaluator_hashes_match):return False
    saved=score['scores'];candidates=pool.get('candidates',[])
    if saved.get('selected_candidate_id')!=pool.get('selected_candidate_id'):return False
    if set(saved.get('candidate_scores',{}))!={c['id'] for c in candidates}:return False
    return all(saved['candidate_scores'][c['id']].get('source_support_seconds')==c.get('source_support_seconds') for c in candidates)


def ulp_margin(*values):
    return 8*max(math.ulp(float(value)) for value in (*values,1.))
def within_tolerance(a,b,tolerance):
    return abs(a-b)<=tolerance+ulp_margin(a,b,tolerance)
def ulp_event_counts(reference,prediction,tolerance):
    """Sensitivity comparator only. Historical canonical scores are unchanged."""
    i=j=tp=0
    while i<len(reference) and j<len(prediction):
        if within_tolerance(reference[i],prediction[j],tolerance):i+=1;j+=1;tp+=1
        elif prediction[j]<reference[i]:j+=1
        else:i+=1
    return {'true_positives':tp,'false_negatives':len(reference)-tp,'false_positives':len(prediction)-tp}
def threshold_sensitivity(reference,pool,diagnostic,case):
    if pool is None:return []
    candidates={c['id']:c for c in pool.get('candidates',[])};rows=[]
    for scored in diagnostic.get('candidate_rows',[]):
        candidate=candidates[scored['candidate_id']];times=[e['source_seconds'] for e in candidate['indexed_grid']]
        for scope,key,support in [('whole_annotation','whole_annotation_diagnostic',reference['evaluation_support_seconds']),
                                  ('within_proposed_support','within_proposed_support_diagnostic',scored['local_evaluation_support_seconds'])]:
            if support is None or scored[key] is None:continue
            lo,hi=support;truth=[t for t in reference['beats_seconds'] if lo<=t<=hi];predicted=[t for t in times if lo<=t<=hi]
            for label,tolerance in PROFILES.items():
                old=scored[key][label];new=ulp_event_counts(truth,predicted,tolerance)
                rows.append({'id':case['id'],'model':case['model'],'family':diagnostic['family'],
                    'candidate_id':candidate['id'],'scope':scope,'profile':label,
                    'historical_counts':{k:old[k] for k in new},'alternative_8ulp_counts':new,
                    'changed':any(old[k]!=new[k] for k in new)})
    return rows


def probe_channel(values,fps,reference_times,*,source_duration,decoded=None):
    values=np.asarray(values)
    if values.ndim!=1 or not len(values) or not np.isfinite(values).all() or not np.isfinite(fps) or fps<=0:raise ValueError('invalid native score channel')
    frame_times=np.arange(len(values),dtype=float)/fps;valid=frame_times<source_duration
    values=values[valid];frame_times=frame_times[valid]
    if not len(values):return {'status':'no_physical_source_frames','rows':[]}
    peaks=np.flatnonzero((values[1:-1]>=values[:-2])&(values[1:-1]>=values[2:])&((values[1:-1]>values[:-2])|(values[1:-1]>values[2:])))+1
    peak_set=set(peaks.tolist());decoded={k:None if v is None else np.asarray(v,dtype=float) for k,v in (decoded or {}).items()};rows=[]
    for ordinal,t in enumerate(reference_times):
        epsilon=ulp_margin(t,t-WINDOW_SECONDS,t+WINDOW_SECONDS)
        left=int(np.searchsorted(frame_times,t-WINDOW_SECONDS-epsilon,'left'));right=int(np.searchsorted(frame_times,t+WINDOW_SECONDS+epsilon,'right'))
        row={'reference_index_within_support':ordinal,'reference_seconds':float(t),'window_seconds':[t-WINDOW_SECONDS,t+WINDOW_SECONDS],
             'frame_count':right-left,'decoded_event_availability':{}}
        for method,events in decoded.items():
            if events is None:row['decoded_event_availability'][method]={'status':'unavailable'};continue
            insertion=int(np.searchsorted(events,t));options=[i for i in (insertion-1,insertion) if 0<=i<len(events)]
            nearest=min(options,key=lambda i:(abs(events[i]-t),events[i])) if options else None
            delta=float(events[nearest]-t) if nearest is not None else None
            row['decoded_event_availability'][method]={'status':'available','nearest_error_seconds':delta,
                'within20ms':nearest is not None and within_tolerance(float(events[nearest]),float(t),.02),
                'within70ms':nearest is not None and within_tolerance(float(events[nearest]),float(t),.07),
                'matching_scope':'nearest availability, not one-to-one F1 or musical identity'}
        if right<=left:row['status']='no_frame_in_window';rows.append(row);continue
        near=min(range(left,right),key=lambda i:(abs(frame_times[i]-t),i));window=values[left:right]
        max_value=float(np.max(window));maxima=np.flatnonzero(window==max_value)+left
        maximum=min(maxima.tolist(),key=lambda i:(abs(frame_times[i]-t),i));nearby_peaks=peaks[(peaks>=left)&(peaks<right)]
        peak=min(nearby_peaks.tolist(),key=lambda i:(abs(frame_times[i]-t),i)) if len(nearby_peaks) else None
        row.update(status='probed',nearest_frame_index=near,nearest_frame_error_seconds=float(frame_times[near]-t),
            nearest_frame_raw_value=float(values[near]),nearest_frame_window_rank=1+int(np.sum(window>values[near])),
            nearest_frame_tied_value_count=int(np.sum(window==values[near])),window_maximum_frame_index=int(maximum),
            window_maximum_error_seconds=float(frame_times[maximum]-t),window_maximum_raw_value=max_value,
            window_maximum_tie_count=len(maxima),window_maximum_is_native_local_peak=maximum in peak_set,
            native_local_peak_count=len(nearby_peaks),nearest_local_peak_error_seconds=float(frame_times[peak]-t) if peak is not None else None)
        rows.append(row)
    scored=[r for r in rows if r['status']=='probed']
    summary={'reference_count':len(rows),'probed_count':len(scored),
        'nearest_frame_window_rank_counts':dict(Counter(r['nearest_frame_window_rank'] for r in scored)),
        'no_native_local_peak_count':sum(r['native_local_peak_count']==0 for r in scored),
        'window_maximum_absolute_distance_median_seconds':float(np.median([abs(r['window_maximum_error_seconds']) for r in scored])) if scored else None,
        'decoded_event_availability':{method:{'status':'unavailable' if events is None else 'available',
            'reference_count':len(rows) if events is not None else None,
            **{label:sum(r['decoded_event_availability'][method].get(label,False) for r in rows) if events is not None else None
               for label in ('within20ms','within70ms')}} for method,events in decoded.items()}}
    return {'status':'probed' if rows else 'no_reference_events','summary':summary,'rows':rows,
            'interpretation':'descriptive native-score position only; no strength/confidence or musical correctness claim'}


def prepare(capabilities_path,output):
    output=Path(output)
    if output.exists():raise ValueError('freeze requires a new output directory')
    caps=read(capabilities_path);cohort=caps['proposed_fixed_diagnostic_cohort'];files={}
    def add(path):
        record=file_record(path)
        prior=caps['prediction_artifact_sha256'].get(record['path'])
        if prior is not None and record['sha256']!=prior:raise ValueError('candidate/prediction differs from frozen cohort artifact: '+str(path))
        files[record['path']]=record;return str(path)
    add(capabilities_path)
    for p in [CORE/'configuration.json',REGIONS/'configuration.json',Path(__file__),Path(__file__).with_name('grid_metrics.py'),Path(__file__).with_name('compare_clock_candidates.py')]:add(p)
    cases=[]
    for track in cohort:
        add(track['reference']['path'])
        if files[track['reference']['path']]['sha256']!=track['reference']['sha256']:raise ValueError('reference differs from frozen cohort')
        for model in ('beat_this','beat_transformer'):
            core=CORE/'predictions'/track['id']/model/'predictions.json'
            case={'id':track['id'],'model':model,'cohort_role':track['role'],
                'c5_selection':'all frozen-cohort available models, extension predeclared before execution',
                'c6_selected':'C6' in track['planned_control_ids'],'reference':track['reference'],
                'reference_tier':track['reference_tier'],'reference_caveats':track['reference_caveats'],
                'capabilities':track['current_reference_capabilities'],'core_prediction':add(core),
                'whole_pool':add(core.with_name('candidates.json')),'core_score':add(CORE/'scores'/track['id']/(model+'.json')),
                'region_prediction':add(REGIONS/'predictions'/track['id']/model/'predictions.json'),
                'region_score':add(REGIONS/'scores'/track['id']/(model+'.json'))}
            if core.is_file():
                predicted=read(core);case['source']=predicted['source']
                if case['c6_selected']:add(predicted['source']['logits_path'])
                expected=next((r for r in track['prediction_inputs'] if r['model']==model),None)
                if expected is None or expected['sha256']!=digest(core):raise ValueError('frozen cohort prediction binding mismatch')
            else:case['availability']='no_saved_frozen_model_output'
            cases.append(case)
    configuration={'schema_version':1,'controls':['C5','C6'],'cohort_count':len(cohort),
        'candidate_profiles_seconds':PROFILES,'candidate_score_level':'canonical-quarter supplied-reference diagnostic, not map-equivalence score',
        'C5_scope':'all frozen15 tracks; whole-source and partial-region pools separate; absent models explicit',
        'C6_track_ids':[r['id'] for r in cohort if 'C6' in r['planned_control_ids']],
        'C6_window_half_width_seconds':WINDOW_SECONDS,'C6_channels':['beat','downbeat'],
        'C6_nearest_frame_rank':'one plus strictly greater native values in inclusive window; ties counted',
        'C6_native_local_peak':'both native neighbors no greater, at least one strictly lower; endpoints excluded; no magnitude threshold',
        'C6_numerical_boundary_policy':'inclusive8ULP only; no timing shift or window tuning',
        'C5_numerical_boundary_policy':'frozen grid_metrics dependency hash; cache reuse requires matching evaluator hash; separate8ULP sensitivity',
        'C6_tie_resolution':'closest in physical source time then earlier frame','C6_decoded_methods':['official','common_minimal'],
        'model_inference':False,'decoder_rerun':False,'reference_alignment':False,'model_confidence_calibration':False,
        'candidate_oracle_is_actual':False,'input_condition':'unchanged unhinted saved predictions; no guide-BPM intervention',
        'NTM_scope':'agreement with owner-approved map, no independent20ms reference truth','unseen_validation':False,'numpy_version':np.__version__}
    save(output/'configuration.json',configuration)
    save(output/'manifest.json',{'schema_version':1,'status':'frozen_before_execution','created_utc':datetime.now(timezone.utc).isoformat(),
        'configuration_sha256':digest(output/'configuration.json'),'files':list(files.values()),'cases':cases})
    return {'status':'frozen_before_execution','cases':len(cases),'files':len(files)}


def execute(output):
    output=Path(output);manifest=read(output/'manifest.json');configuration=read(output/'configuration.json')
    if manifest['status']!='frozen_before_execution' or (output/'report.json').exists():raise ValueError('use a fresh frozen run')
    if digest(output/'configuration.json')!=manifest['configuration_sha256'] or configuration['numpy_version']!=np.__version__:raise ValueError('configuration/environment changed after freeze')
    verify_files(manifest['files']);started=time.perf_counter();rows=[];sensitivity=[];frozen={r['path']:r for r in manifest['files']}
    region_config=read(REGIONS/'configuration.json');core_config=read(CORE/'configuration.json')
    match=lambda hashes:all(hashes.get(name)==digest(Path(__file__).with_name(name)) for name in ('grid_metrics.py','compare_clock_candidates.py'))
    region_match=match(region_config['evaluation_hashes']);core_match=match(core_config['metric_source_hashes'])
    for case in manifest['cases']:
        row={'id':case['id'],'model':case['model'],'C5':{},'C6':None};reference=read(case['reference']['path'])
        if digest(case['reference']['path'])!=case['reference']['sha256']:raise ValueError('reference binding differs from frozen cohort')
        core=read(case['core_prediction']) if frozen[case['core_prediction']]['exists'] else None
        for family,path in [('whole_source',case['whole_pool']),('partial_regions',case['region_prediction'])]:
            saved=read(path) if frozen[path]['exists'] else None;pool=saved.get('generated') if family=='partial_regions' and saved else saved
            cache=None;cache_origin=None
            if family=='partial_regions' and pool is not None and frozen[case['region_score']]['exists']:
                score=read(case['region_score'])
                if eligible_region_cache(score,frozen[path]['sha256'],case['reference']['sha256'],pool,region_match):
                    cache=score['scores']['candidate_scores'];cache_origin=file_record(case['region_score'])
            if family=='whole_source' and pool is not None and core and frozen[case['core_score']]['exists']:
                score=read(case['core_score']);selected=next((c for c in pool['candidates'] if c['id']==pool['selected_candidate_id']),None)
                if selected and cache_binding(score,frozen[case['core_prediction']]['sha256'],case['reference']['sha256'],core_match):
                    times=[e['source_seconds'] for e in selected['indexed_grid']]
                    if times==core['methods']['clock_candidates_selected']['prediction']['beats_seconds']:
                        cache={selected['id']:{'whole_annotation_diagnostic':score['scores']['clock_candidates_selected'],'compute_uncached_local':True}}
                        cache_origin=file_record(case['core_score'])
            diagnostic=score_pool(reference,pool,core['source']['duration_seconds'] if core else 0.,family=family,cached_scores=cache,cache_origin=cache_origin)
            diagnostic.update(id=case['id'],model=case['model'],reference_tier=case['reference_tier'],reference_caveats=case['reference_caveats'])
            sensitivity.extend(threshold_sensitivity(reference,pool,diagnostic,case))
            target=output/'C5'/case['id']/case['model']/(family+'.json');save(target,diagnostic)
            row['C5'][family]={'path':str(target),'status':diagnostic['status'],'candidate_count':diagnostic['candidate_count'],
                'selected_candidate_id':diagnostic.get('selected_candidate_id'),'automatic':diagnostic.get('automatic'),
                'oracle_diagnostic':diagnostic.get('oracle_diagnostic'),'score_modes':diagnostic.get('score_modes',{})}
        if not case['c6_selected']:row['C6']={'status':'not_selected_for_C6_in_frozen_design'}
        elif core is None:row['C6']={'status':'unavailable_model_output_and_native_cache'}
        else:
            source=core['source'];path=source['logits_path']
            if not frozen[path]['exists']:row['C6']={'status':'unavailable_native_cache'}
            else:
                if digest(path)!=source['logits_sha256']:raise ValueError('logits disagree with model provenance')
                if source['source_frame_offset']!=0 or source['frame_time_offset_seconds']!=0:raise ValueError('nonzero stored source origin')
                with np.load(path,allow_pickle=False) as saved:
                    fps=float(saved['fps']);channels={channel:np.asarray(saved[channel]) for channel in ('beat','downbeat') if channel in saved}
                    for field in ('source_frame_offset','frame_time_offset_seconds'):
                        if field in saved and float(saved[field])!=0:raise ValueError('nonzero native cache origin')
                if fps!=source['native_frame_rate']:raise ValueError('frame rate disagrees with frozen prediction')
                probe={'id':case['id'],'model':case['model'],'fps':fps,'window_half_width_seconds':WINDOW_SECONDS,
                    'source':source,'reference_tier':case['reference_tier'],'reference_caveats':case['reference_caveats'],
                    'channel_results':{},'scope':'reference-conditioned descriptive evidence, not strength/confidence or unseen performance'}
                lo,hi=reference['evaluation_support_seconds']
                for channel,field,cap in [('beat','beats_seconds','beat_events'),('downbeat','downbeats_seconds','downbeat_events')]:
                    if not case['capabilities'].get(cap) or reference.get(field) is None:
                        probe['channel_results'][channel]={'status':'unavailable_qualified_reference_events'};continue
                    if channel not in channels:probe['channel_results'][channel]={'status':'unavailable_native_channel'};continue
                    truth=[v for v in reference[field] if lo<=v<=hi]
                    decoded={method:(core['methods'].get(method,{}).get('prediction') or {}).get(field) for method in ('official','common_minimal')}
                    probe['channel_results'][channel]=probe_channel(channels[channel],fps,truth,source_duration=source['duration_seconds'],decoded=decoded)
                target=output/'C6'/case['id']/(case['model']+'.json');save(target,probe)
                row['C6']={'status':'probed','path':str(target),'channels':{k:{'status':v['status'],'summary':v.get('summary')} for k,v in probe['channel_results'].items()}}
        rows.append(row)
    verify_files(manifest['files'])
    sensitivity_summary={'status':'complete','historical_scores_replaced':False,
        'policy':'8ULP timing comparison only; original reference/prediction support filtering unchanged',
        'comparison_count':len(sensitivity),'changed_comparison_count':sum(r['changed'] for r in sensitivity),
        'changed_rows':[r for r in sensitivity if r['changed']],
        'unchanged_comparison_count':sum(not r['changed'] for r in sensitivity)}
    save(output/'threshold-sensitivity.json',sensitivity_summary)
    report={'schema_version':1,'status':'complete','configuration':configuration,'manifest_sha256':digest(output/'manifest.json'),
        'wall_clock_seconds':time.perf_counter()-started,'cohort_track_count':len({r['id'] for r in rows}),'model_case_count_including_unavailable':len(rows),
        'C5_status_counts':{family:dict(Counter(r['C5'][family]['status'] for r in rows)) for family in ('whole_source','partial_regions')},
        'C6_status_counts':dict(Counter(r['C6']['status'] for r in rows)),'rows':rows,
        'C5_threshold_sensitivity':{k:v for k,v in sensitivity_summary.items() if k!='changed_rows'},
        'limits':['Canonical-quarter event scores do not apply the reviewed map-equivalence policy.',
            'Best-candidate scores are reference-assisted finite-pool diagnostics, never automatic performance.',
            'Region-local and whole-annotation scores stay separate; no bridge/full-song map is invented.',
            'Native-score ranks/peaks cannot establish calibrated strength, musical identity or reference correctness.',
            'Missing a supplied-reference quarter peak is not proof of acoustic information loss: an accepted 4/4-to-8/4 map may use another click density.',
            'No unit declaration, BPM hint, model, decoder, reference or saved candidate changed.']}
    save(output/'report.json',report)
    return {k:report[k] for k in ('status','C5_status_counts','C6_status_counts','wall_clock_seconds')}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','execute'))
    p.add_argument('--capabilities',type=Path,default=DEFAULT_CAPABILITIES);p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT)
    a=p.parse_args();print(json.dumps(prepare(a.capabilities,a.output_dir) if a.action=='prepare' else execute(a.output_dir)))
if __name__=='__main__':main()
