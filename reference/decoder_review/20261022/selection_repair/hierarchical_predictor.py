"""Executable literal-phase/role-suffix research candidate, source input only."""
import math
import numpy as np
from collections import defaultdict
from phase_api import refine_map as phase_pool
from phase_predictor import select_native
from run_hierarchical_phase import observed_bar,METHODS

def refine_map(events,original,method='coded_literal_phase_role_suffix_mdl'):
    if method not in METHODS:raise ValueError('Unknown source method')
    payload=phase_pool(events,original);groups=defaultdict(list)
    for row in payload['candidates']:
        row['literal_phase_score']=observed_bar(row['geometry'],events)+sum(row['components'][k] for k in ('expected_bar','meter_prior','transition'))
        groups[row['retained_events']].append(row)
    eligible=[]
    for bank in groups.values():
        code=math.log(len(bank)) if METHODS[method] else 0.
        best=max(bank,key=lambda r:(r['literal_phase_score']-(code if r['rotation_quarters'] else 0.),-r['rotation_quarters']))
        value=best['scores']['phase_completed_suffix_mdl']-(code if best['rotation_quarters'] else 0.)
        eligible.append((value,best))
    value,best=max(eligible,key=lambda x:(x[0],-x[1]['retained_events'],-x[1]['rotation_quarters']))
    payload['selections']['phase_completed_suffix_mdl']={'candidate_index':best['candidate_index'],'score':value}
    result=select_native(original,payload,'phase_completed_suffix_mdl')
    result.update(method=method,bar_selection_score_scheme='Literal observed bars select initial origin; role-aware bars plus boundary code select suffix'+('; changed initial origin also pays log(legal rotations)' if METHODS[method] else ''))
    return result,{'source_only':True,'reference_read':False,'candidate_count':len(payload['candidates']),
                  'selected_candidate_index':best['candidate_index'],'score':value}

def predict_with_trace(packet,method='coded_literal_phase_role_suffix_mdl'):
    import candidate_api
    original,trace=candidate_api.predict_with_trace(packet)
    if original.get('status')!='map':return original,{'G21_trace':trace}
    with np.load(packet['data']['events_path'],allow_pickle=False) as f:events={k:f[k].copy() for k in f.files}
    output,selection=refine_map(events,original,method)
    return output,{'G21_trace':trace,'hierarchical_bar_selection':selection}

def predict(packet,method='coded_literal_phase_role_suffix_mdl'):
    return predict_with_trace(packet,method)[0]
