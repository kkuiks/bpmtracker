"""Fresh G21 source inference plus the isolated bar-phase repair stage."""
from pathlib import Path
import numpy as np
from phase_api import refine_map,METHODS

def select_native(prediction,selection,method):
    if method not in METHODS:raise ValueError('Unknown source selection method')
    choice=selection['selections'][method]
    row=next(r for r in selection['candidates'] if r['candidate_index']==choice['candidate_index'])
    result={**prediction,**row['geometry'],'method':method,
        'bar_selection_score':choice['score'],
        'bar_selection_score_scheme':'role-aware observed/expected bars, meter prior, transition cost'+(' and source boundary code' if METHODS[method] else ''),
        'initial_source_origin':'G21_quarter_clock_with_source_bar_phase_completion',
        'refinement':{'physical_quarter_clock_preserved':True,'all_tempo_events_preserved':True,
                      'global_initial_rotation_quarters':row['rotation_quarters'],
                      'quarter_label_shift':row['quarter_label_shift'],'retained_events':row['retained_events'],
                      'independent_section_rephasing':False}}
    for key in ['gate_trace','search_trace','decoder','source_score','pinned_initial_preserved']:result.pop(key,None)
    return result

def predict_with_trace(packet,method='phase_completed_suffix_mdl'):
    import candidate_api
    original,trace=candidate_api.predict_with_trace(packet)
    if original.get('status')!='map':return original,{'G21_trace':trace}
    with np.load(packet['data']['events_path'],allow_pickle=False) as f:events={k:f[k].copy() for k in f.files}
    selection=refine_map(events,original)
    return select_native(original,selection,method),{'G21_trace':trace,'bar_phase_selection':selection}

def predict(packet,method='phase_completed_suffix_mdl'):
    return predict_with_trace(packet,method)[0]
