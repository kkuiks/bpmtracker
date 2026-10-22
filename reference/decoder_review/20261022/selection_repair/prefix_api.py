"""Executable conservative G21 refiners; no labels or song-specific policy.

Research candidates, not selected replacements for the application or baseline.
predict_with_trace accepts the unchanged anonymous FULL G21 source packet.
refine_map exposes the new stage independently for matched-cache comparisons.
"""
from pathlib import Path
import json,time
import numpy as np
from source_scores import MapScorer,geometry
from experiments.continuous_beat_map_v1.map import validate

CRITERIA={
    'role_prefix_mdl':('role_mdl_pool',False),
    'role_meter_suffix_mdl':('role_mdl_pool',True),
    'role_meter_suffix':('role_pool',True),
}

def refine_map(events,prediction,method='role_meter_suffix_mdl'):
    criterion,preserve_tempos=CRITERIA[method]
    if prediction.get('status')!='map':return prediction,{'no_source_clock':True}
    if abs(float(events['duration'])-prediction['duration_seconds'])>1e-7:raise ValueError('Duration differs')
    start=time.perf_counter()
    floor=max([0]+[i+1 for i,e in enumerate(prediction['events']) if 'bpm' in e]) if preserve_tempos else 0
    scorer=MapScorer(events,{'units':[]});candidates=[]
    for n in range(floor,len(prediction['events'])+1):
        value=geometry({**prediction,'events':prediction['events'][:n]})
        result=scorer.score(value,initial_family_prior=0.)
        candidates.append({'retained_events':n,'geometry':value,'score':result['scores'][criterion]})
    selected=max(candidates,key=lambda c:(c['score'],-c['retained_events']))
    out={**prediction,**selected['geometry'],'method':method,'source_score':selected['score']/prediction['duration_seconds'],
         'refinement':{'upstream_method':'G21','original_events':len(prediction['events']),
                       'retained_events':selected['retained_events'],'all_tempo_events_preserved':preserve_tempos,
                       'initial_preserved':True,'retained_event_geometry_preserved':True}}
    # Remove upstream search/path metadata that described the unrefined map.
    for name in ['gate_trace','search_trace','decoder','pinned_initial_preserved']:out.pop(name,None)
    if not validate(out)['legal']:raise ValueError('Refinement changed native legality')
    return out,{'source_only':True,'reference_read':False,'candidate_count':len(candidates),
                'minimum_retained_events':floor,'selected_events':selected['retained_events'],
                'elapsed_seconds':time.perf_counter()-start,'scores':[{'events':c['retained_events'],'score':c['score']} for c in candidates]}

def predict_with_trace(packet,method='role_meter_suffix_mdl'):
    import candidate_api
    prediction,trace=candidate_api.predict_with_trace(packet)
    with np.load(packet['data']['events_path'],allow_pickle=False) as f:events={k:f[k].copy() for k in f.files}
    refined,selection=refine_map(events,prediction,method)
    return refined,{'G21_trace':trace,'prefix_selection':selection}

def predict(packet,method='role_meter_suffix_mdl'):
    return predict_with_trace(packet,method)[0]
