"""Fresh source-only candidate generation followed by explicit map selection.

Research prototype: preserves the G21/L2 graph, exposes a deterministic bounded
candidate pool, and changes only the complete-map selection criterion. It does
not claim to repair the graph's missing changing paths.
"""
import json,time
from pathlib import Path
import numpy as np
from source_scores import MapScorer,VARIANTS,geometry,geometry_key


def pool_from_trace(result, trace, baseline, fixed):
    pool={}
    def add(value,origin):
        if not value or 'initial' not in value:return
        k=geometry_key(value)
        row=pool.setdefault(k,{'candidate_index':len(pool),'geometry':geometry(value),'origins':[]})
        if origin not in row['origins']:row['origins'].append(origin)
    branch=trace['candidate_branches']
    for head in branch['retained_initials']:add(head,'G21_retained_root')
    for expansion in branch['expansions']:
        add(expansion['parent'],'G21_expanded_parent')
        for head in expansion['best_children']:add(head,'G21_recorded_child')
    for expansion in trace['baseline_expansions']:add(expansion['parent'],'L2_expanded_parent')
    add(result,'saved_final_G21');add(baseline,'saved_final_L2');add(fixed,'saved_final_LINEAR_FIXED')
    return list(pool.values())


def fixed_from_family(family,unit,duration):
    selected=[level for level in family.get('levels',[]) if level['power']==unit.get('power')]
    if not unit.get('available') or not selected:return None
    best=max(selected,key=lambda x:x['best']['score'])['best']
    bpm=best['quarter_bpm'];sig=best['time_signature']
    period=60./bpm*sig['numerator']*4./sig['denominator']
    phase=best['offset_seconds']%period
    if phase>1e-8:phase-=period
    return {'format':'joljak-continuous-beat-map','version':1,'status':'map','duration_seconds':duration,
            'initial':{'bpm':bpm,'numerator':sig['numerator'],'denominator':sig['denominator'],'bar_zero_source_seconds':phase},'events':[]}


def predict_with_trace(packet):
    if set(packet)!={'unit','fixed_unit','duration_seconds','data'}:raise ValueError('Source packet fields')
    if set(packet['data'])!={'events_path','prepared_source_path','family_path'}:raise ValueError('Source data fields')
    for unit in (packet['unit'],packet['fixed_unit']):
        if set(unit)-{'available','unit_id','power','numeric_tap_discarded'}:raise ValueError('Numeric aid forbidden')
    import candidate_api
    from experiments.beat_event_stability_v1 import core as original_l2
    captured=[];old_fit=original_l2.fit
    def capture(*args,**kwargs):
        value=old_fit(*args,**kwargs);captured.append(value);return value
    original_l2.fit=capture
    started=time.perf_counter()
    try:
        old_packet={k:packet[k] for k in ('unit','duration_seconds')}
        old_packet['data']={k:packet['data'][k] for k in ('events_path','prepared_source_path')}
        g21,trace=candidate_api.predict_with_trace(old_packet)
    finally:
        original_l2.fit=old_fit
    generation_seconds=time.perf_counter()-started
    if len(captured)!=1:raise ValueError('Expected exactly one original L2 invocation')
    with np.load(packet['data']['events_path'],allow_pickle=False) as f:events={k:f[k].copy() for k in f.files}
    prepared=json.loads(Path(packet['data']['prepared_source_path']).read_text())
    family=json.loads(Path(packet['data']['family_path']).read_text())
    fixed=fixed_from_family(family,packet['fixed_unit'],packet['duration_seconds'])
    pool=pool_from_trace(g21,trace,captured[0],fixed)
    scorer=MapScorer(events,prepared,family)
    scored=[];scoring_started=time.perf_counter()
    for row in pool:
        result=scorer.score(row['geometry'])
        scored.append({**row,'scores':result['scores']})
    outputs={}
    for variant in VARIANTS:
        selected=max(scored,key=lambda r:(r['scores'][variant],-len(r['geometry']['events']),-r['candidate_index']))
        outputs[variant]={'format':'joljak-continuous-beat-map','version':1,'status':'map',
                          'duration_seconds':packet['duration_seconds'],**selected['geometry'],'method':variant,
                          'source_score':selected['scores'][variant]/packet['duration_seconds'],
                          'selection_candidate_index':selected['candidate_index'],'free_phase_parameters_after_start':0}
    return outputs,{'source_only':True,'reference_read':False,'candidate_generation_seconds':generation_seconds,
                    'pool_scoring_seconds':time.perf_counter()-scoring_started,'source_pool':scored,
                    'control_G21':g21,'control_L2':captured[0],'control_LINEAR_FIXED':fixed,'G21_trace':trace}
