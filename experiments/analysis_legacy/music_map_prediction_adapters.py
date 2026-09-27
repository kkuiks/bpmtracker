"""Lossless views of existing prediction facts in the declared map contract.

This module does not infer a pulse unit, meter, origin, bridge or alignment.
Historical quarter-named fields remain explicit hypotheses. References are not
read; model events and clock coefficients are never changed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from music_map_contract import prepare_map, interpolate_clock

IDENTITY_EPSILON_SECONDS = 1e-8  # floating arithmetic verification, not scoring


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def json_hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _real(value, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return float(value)


def source_identity(source):
    """Identity is inherited from the frozen core input, not a reference map."""
    result={k:deepcopy(source[k]) for k in ('sha256','sample_rate','sample_frames','path','original_path','original_sha256','canonical_decode_mapping') if k in source}
    base=prepare_map({'schema_version':1,'source':result,'clock_knots':[],'support_seconds':[]})
    result=base['source']
    for name in ('source_frame_offset','frame_time_offset_seconds'):
        if source.get(name,0)!=0:
            raise ValueError(f'nonzero {name} requires a separate declared source-clock adapter')
    if 'duration_seconds' in source and abs(_real(source['duration_seconds'],'duration')-base['duration_seconds'])>1/result['sample_rate']:
        raise ValueError('source duration disagrees with native sample geometry')
    result['clock_id']=f"sha256:{result['sha256']}:sr:{result['sample_rate']}:frames:{result['sample_frames']}:origin:0"
    result['clock_identity_provenance']='verified frozen core prediction source geometry; no reference alignment'
    return result


def _clock_parts(clock):
    if not isinstance(clock,dict):raise ValueError('clock must be an object')
    knots=[_real(v,'clock knot') for v in clock.get('knot_pulse_indices',[])]
    coefficients=[_real(v,'clock coefficient') for v in clock.get('coefficients',[])]
    span=clock.get('pulse_index_span')
    if not isinstance(span,(list,tuple)) or len(span)!=2:raise ValueError('clock requires declared pulse span')
    lo,hi=(_real(v,'pulse span') for v in span)
    if hi<=lo or len(coefficients)!=len(knots)+2 or any(b<=a for a,b in zip(knots,knots[1:])):
        raise ValueError('invalid clock coefficient, knot or span geometry')
    positions=[lo,*[k for k in knots if lo<k<hi],hi]
    def time_at(u):return coefficients[0]+coefficients[1]*u+sum(delta*max(u-k,0.) for k,delta in zip(knots,coefficients[2:]))
    geometry=[{'pulse':u,'source_seconds':time_at(u)} for u in positions]
    if any(not math.isfinite(v['source_seconds']) for v in geometry) or any(b['source_seconds']<=a['source_seconds'] for a,b in zip(geometry,geometry[1:])):
        raise ValueError('clock must be finite and increasing on its declared domain')
    return geometry,time_at


def _physical_support(clock, geometry, source, source_window=None):
    declared=clock.get('support_seconds')
    if declared is None:return [],{'original_support_seconds':None,'reason':'source clock did not declare support'}
    if not isinstance(declared,(list,tuple)) or len(declared)!=2:raise ValueError('existing clock support must have two endpoints')
    lo,hi=(_real(v,'declared support') for v in declared)
    if hi<lo:raise ValueError('declared support runs backwards')
    original=[lo,hi];duration=source['sample_frames']/source['sample_rate']
    windows=[(0.,duration),(geometry[0]['source_seconds'],geometry[-1]['source_seconds'])]
    if source_window is not None:
        if not isinstance(source_window,(list,tuple)) or len(source_window)!=2:raise ValueError('source window requires two endpoints')
        a,b=(_real(v,'source window') for v in source_window)
        if b<a:raise ValueError('source window runs backwards')
        windows.append((a,b))
    for a,b in windows:lo,hi=max(lo,a),min(hi,b)
    return ([[lo,hi]] if hi>lo else []),{'original_support_seconds':original,
        'fitted_curve_domain_seconds':[geometry[0]['source_seconds'],geometry[-1]['source_seconds']],
        'intersection_applied':True,'meaning':'declared clock support intersected with curve domain and physical source; not continuous acoustic certification'}


def _events(prediction,source):
    if isinstance(prediction,list):prediction={'beats_seconds':prediction}
    if not isinstance(prediction,dict):raise ValueError('event prediction must be object or beat list')
    result={};duration=source['sample_frames']/source['sample_rate']
    for name in ('beats_seconds','downbeats_seconds'):
        if name not in prediction:continue
        values=prediction[name]
        if not isinstance(values,list):raise ValueError('saved events must be lists')
        numbers=[_real(t,'event time') for t in values]
        if any(b<=a for a,b in zip(numbers,numbers[1:])):
            raise ValueError('saved events must be ordered and unique')
        result[name]=deepcopy(values)
    return result


def adapt_method(method, source, *, provenance, candidate=None, analysis_condition='unhinted'):
    source=source_identity(source);clock=method.get('clock');events=_events(method.get('prediction',{}),source)
    raw={'schema_version':1,'source':source,'clock_knots':[],'support_seconds':[],
         'quarters_per_pulse':None,'meter_events':None,'bar_anchor_pulse':None,'shared_origin_id':None,
         'analysis_condition':analysis_condition}
    duration=source['sample_frames']/source['sample_rate']
    outside={name:[{'event_index':i,'source_seconds':t,'side':'before_source' if t<0 else 'after_source','outside_by_seconds':-t if t<0 else t-duration} for i,t in enumerate(values) if t<0 or t>=duration] for name,values in events.items()}
    diagnostics={'event_validation':{'ordered_unique_finite':True,'physical_source_bounds_valid':not any(outside.values()),'outside_physical_source':outside,'boundary_violations_preserved_without_clipping':True},
                 'reference_consulted':False,'clock_coefficients_modified':False,'events_modified':False,
                 'unit_promotion_performed':False,'identity_epsilon_seconds':IDENTITY_EPSILON_SECONDS,
                 'input_event_indexing_basis':'pre-phase fit coordinates; distinct from candidate output basis'}
    if clock is not None:
        geometry,time_at=_clock_parts(clock)
        support,support_metadata=_physical_support(clock,geometry,source,(candidate or {}).get('source_window_seconds'))
        raw.update(clock_knots=geometry,support_seconds=support)
        diagnostics.update(support_metadata)
        diagnostics['original_clock_unit_declaration']=clock.get('pulse_unit')
        diagnostics['original_clock_coefficients']=deepcopy(clock['coefficients'])
        diagnostics['original_clock_knots']=deepcopy(clock.get('knot_pulse_indices',[]))
        diagnostics['original_pulse_index_span']=deepcopy(clock['pulse_index_span'])
        if candidate is not None:
            if candidate.get('clock')!=clock:raise ValueError('candidate and selected method clocks differ')
            checks=[]
            for event in candidate.get('indexed_grid',[]):
                u=_real(event['quarter_position'],'candidate pulse coordinate');t=_real(event['source_seconds'],'candidate event time')
                interpolated=interpolate_clock(geometry,u)
                error=abs(interpolated-t)
                if error>IDENTITY_EPSILON_SECONDS or abs(time_at(u)-t)>IDENTITY_EPSILON_SECONDS:
                    raise ValueError('emitted candidate grid does not equal its declared clock')
                checks.append(error)
            if 'beats_seconds' in events and events['beats_seconds']!=[e['source_seconds'] for e in candidate.get('indexed_grid',[])]:
                raise ValueError('selected candidate event list differs from indexed grid')
            diagnostics['emitted_grid_identity']={'checked_count':len(checks),'max_absolute_error_seconds':max(checks,default=0.),'passed':True}
            diagnostics['candidate_declarations']={k:deepcopy(candidate[k]) for k in ('id','quarter_unit','musical_index_origin','phase_offset_quarters','input_event_indexing','anchor_checks','source_window_seconds','fitted_clock_support_seconds','emitted_grid_support_seconds','support_warning','unknown_bridges') if k in candidate}
            diagnostics['candidate_coordinate_basis']='phase-adjusted output clock; quarter names are unaccepted latent-pulse hypotheses'
        else:
            # Existing fitted outputs do not always retain per-event indices.
            # Check that every emitted event lies on the integer output lattice
            # when it is inside the declared fitted curve domain; do not guess
            # indices for fallback events or change the declared support.
            domain=[geometry[0]['source_seconds'],geometry[-1]['source_seconds']]
            checked=0;outside=0;max_error=0.
            for t in events.get('beats_seconds',[]):
                if t<domain[0]-IDENTITY_EPSILON_SECONDS or t>domain[1]+IDENTITY_EPSILON_SECONDS:outside+=1;continue
                comparison_time=min(max(t,domain[0]),domain[1])
                pulse=interpolate_clock(geometry,comparison_time,inverse=True)
                integer=round(pulse)
                if geometry[0]['pulse']<=integer<=geometry[-1]['pulse']:
                    error=abs(time_at(integer)-t)
                    if error>IDENTITY_EPSILON_SECONDS:raise ValueError('emitted fitted event is not on its declared integer pulse lattice')
                    checked+=1;max_error=max(max_error,error)
            diagnostics['emitted_grid_identity']={'checked_count':checked,'outside_curve_domain_count':outside,'max_absolute_error_seconds':max_error,'passed':outside==0,'floating_endpoint_clamping_for_comparison_only':True}
    adapted=prepare_map(raw)
    return {'map':adapted,'events':events,'status':'clock_view' if clock is not None else ('events_only' if any(events.values()) else 'empty_prediction'),
            'original_status':method.get('status'),'original_capabilities':deepcopy(method.get('capabilities')),
            'provenance':deepcopy(provenance),'adaptation':diagnostics,
            'full_music_map_claimed':False,'musical_unit_status':'unresolved_or_unaccepted_hypothesis'}


def adapt_core_prediction(core, *, artifact_path, artifact_sha256, candidates=None, candidates_path=None,candidates_sha256=None):
    condition='reference_assisted_diagnostic' if core.get('references_used_for_prediction') else 'unhinted'
    by_id={c['id']:c for c in (candidates or {}).get('candidates',[])}
    output={'schema_version':1,'id':core['id'],'model':core['model'],'source':source_identity(core['source']),
            'artifact_path':str(artifact_path),'artifact_sha256':artifact_sha256,'methods':{},'references_read_by_adapter':False}
    for name,method in core['methods'].items():
        selected=method.get('selected_candidate_id');candidate=by_id.get(selected)
        if selected is not None and candidate is None:raise ValueError('selected candidate is missing from bound candidate artifact')
        output['methods'][name]=adapt_method(method,core['source'],provenance={'artifact_path':str(artifact_path),'artifact_sha256':artifact_sha256,'method':name,
            'candidates_path':str(candidates_path) if candidate else None,'candidates_sha256':candidates_sha256 if candidate else None},candidate=candidate,analysis_condition=condition)
    return output


def adapt_bar_proposals(refinements, core, *, core_path, core_sha256):
    if refinements.get('core_prediction_sha256')!=core_sha256:raise ValueError('bar source hash does not match bound core prediction')
    if Path(refinements.get('core_prediction_path',''))!=Path(core_path):raise ValueError('bar source path does not match bound core prediction')
    if refinements.get('bar_input_grid')!='unchanged_meter_free_clock_prediction':raise ValueError('unknown bar grid binding')
    grid=core['methods']['meter_free_clock']['prediction']['beats_seconds']
    output={}
    for name,bar in refinements.get('bars',{}).items():
        indices=bar.get('bar_start_pulse_indices',[]);times=bar.get('downbeats_seconds',[])
        if len(indices)!=len(times):raise ValueError('bar index/event count mismatch')
        for i,t in zip(indices,times):
            if isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(grid) or abs(grid[i]-t)>IDENTITY_EPSILON_SECONDS:
                raise ValueError('bar events do not match their bound source grid')
        output[name]={'status':'pulse_group_proposal_only','original_status':bar.get('status'),
            'bound_grid':{'core_path':str(core_path),'core_sha256':core_sha256,'method':'meter_free_clock','events_sha256':json_hash(grid)},
            'bar_start_source_seconds':deepcopy(times),'bar_start_grid_ordinals':deepcopy(indices),
            'pulse_group_declarations':deepcopy(bar.get('meter_events',[])),'concrete_meter_events':None,
            'quarters_per_pulse':None,'shared_origin_id':None,'warning':'grid ordinals are not clock pulse coordinates; denominator and musical unit unresolved',
            'original_scope':bar.get('scope'),'full_music_map_claimed':False}
    return output


def adapt_refinements(refinements,core,*,artifact_path,artifact_sha256,core_path,core_sha256):
    if refinements['id']!=core['id'] or refinements['model']!=core['model'] or source_identity(refinements['source'])!=source_identity(core['source']):
        raise ValueError('refinement source/model identity differs from core')
    bars=adapt_bar_proposals(refinements,core,core_path=core_path,core_sha256=core_sha256)
    return {'schema_version':1,'id':core['id'],'model':core['model'],'source':source_identity(core['source']),
        'methods':{name:adapt_method(method,core['source'],provenance={'artifact_path':str(artifact_path),'artifact_sha256':artifact_sha256,'method':name,'core_sha256':core_sha256}) for name,method in refinements['methods'].items()},
        'bars':bars,'references_read_by_adapter':False}


def adapt_region_prediction(regions,core,*,artifact_path,artifact_sha256,core_path,core_sha256):
    if regions['id']!=core['id'] or regions['model']!=core['model'] or regions.get('core_prediction_sha256')!=core_sha256 or Path(regions.get('core_prediction_path',''))!=Path(core_path):
        raise ValueError('region provenance does not match bound core')
    if source_identity(regions['source'])!=source_identity(core['source']):raise ValueError('region source identity differs from core')
    generated=regions['generated'];views={}
    for candidate in generated['candidates']:
        method={'clock':candidate['clock'],'prediction':{'beats_seconds':[e['source_seconds'] for e in candidate['indexed_grid']]},'status':candidate.get('status')}
        view=adapt_method(method,core['source'],candidate=candidate,provenance={'artifact_path':str(artifact_path),'artifact_sha256':artifact_sha256,'candidate_id':candidate['id'],'core_sha256':core_sha256})
        view['region']=deepcopy(candidate.get('region'));view['coordinate_origin_is_region_relative']=True
        views[candidate['id']]=view
    return {'schema_version':1,'id':core['id'],'model':core['model'],'source':source_identity(core['source']),
        'status':generated.get('selection_status'),'selected_candidate_id':generated.get('selected_candidate_id'),
        'candidate_views':views,'unknown_bridges':deepcopy(generated.get('unknown_bridges',[])),
        'regions_joined':False,'full_song_map':False,'references_read_by_adapter':False}


def _read_verified(path,expected=None):
    path=Path(path);actual=sha256(path)
    if expected and actual!=expected:raise ValueError(f'input artifact hash changed: {path}')
    return json.loads(path.read_text()),actual


def _write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def build_views(core_root,output_dir,*,refinements_root=None,regions_root=None):
    core_root,output_dir=Path(core_root),Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):raise FileExistsError('prediction-view output must be new or empty')
    output_dir.mkdir(parents=True,exist_ok=True)
    manifest,manifest_hash=_read_verified(core_root/'manifest.json')
    result={'schema_version':1,'reference_inputs_read':False,'prediction_computation_performed':False,
            'core_manifest_path':str(core_root/'manifest.json'),'core_manifest_sha256':manifest_hash,
            'source_sha256':{name:sha256(Path(__file__).with_name(name)) for name in [Path(__file__).name,'music_map_contract.py','musical_units.py']},'rows':[],'complete':False}
    for row in manifest['rows']:
        record={'id':row['id'],'model':row['model'],'source_status':row.get('status'),'outputs':{}}
        if not row.get('prediction_path'):
            record['status']='unavailable_original_prediction';result['rows'].append(record);continue
        try:
            cp=Path(row['prediction_path']);core,corehash=_read_verified(cp,row.get('prediction_sha256'))
            candp=Path(row['candidates_path']);candidates,candhash=_read_verified(candp,row.get('candidates_sha256'))
            case=output_dir/row['id']/row['model']
            view=adapt_core_prediction(core,artifact_path=cp,artifact_sha256=corehash,candidates=candidates,candidates_path=candp,candidates_sha256=candhash)
            path=case/'core.json';_write(path,view);record['outputs']['core']={'path':str(path),'sha256':sha256(path),'method_count':len(view['methods'])}
            if refinements_root:
                rp=Path(refinements_root)/'predictions'/row['id']/(row['model']+'.json');ref,rhash=_read_verified(rp)
                view=adapt_refinements(ref,core,artifact_path=rp,artifact_sha256=rhash,core_path=cp,core_sha256=corehash)
                path=case/'refinements.json';_write(path,view);record['outputs']['refinements']={'path':str(path),'sha256':sha256(path),'method_count':len(view['methods']),'bar_proposal_count':len(view['bars'])}
            if regions_root:
                rp=Path(regions_root)/'predictions'/row['id']/row['model']/'predictions.json';reg,rhash=_read_verified(rp)
                view=adapt_region_prediction(reg,core,artifact_path=rp,artifact_sha256=rhash,core_path=cp,core_sha256=corehash)
                path=case/'regions.json';_write(path,view);record['outputs']['regions']={'path':str(path),'sha256':sha256(path),'candidate_count':len(view['candidate_views'])}
            record['status']='adapted'
        except (ValueError,KeyError,TypeError,OSError) as error:
            record['status']='adapter_rejected';record['error']=str(error)
        result['rows'].append(record)
    result['complete']=True;result['counts']={state:sum(r['status']==state for r in result['rows']) for state in sorted({r['status'] for r in result['rows']})}
    _write(output_dir/'manifest.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--refinements-root',type=Path);parser.add_argument('--regions-root',type=Path)
    args=parser.parse_args();result=build_views(args.core_root,args.output_dir,refinements_root=args.refinements_root,regions_root=args.regions_root)
    print(json.dumps(result['counts']))
    if result['counts'].get('adapter_rejected'):raise SystemExit(1)


if __name__=='__main__':main()
