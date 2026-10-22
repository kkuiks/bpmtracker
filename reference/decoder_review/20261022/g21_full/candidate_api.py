"""익명 source/단위 입력만 받아 FULL 또는 HELD predictor를 실행합니다."""
from pathlib import Path
import json
import numpy as np
MODE = 'full'
METHOD = 'G21'
IS_BASELINE = False
if IS_BASELINE and MODE == 'full':
    from experiments.beat_event_stability_v1 import core
else:
    import candidate_core as core

def short(head):
    return dict(initial={k:head['initial'][k] for k in ('bpm','numerator','denominator','bar_zero_source_seconds')},
                score=float(head['score']),prefix=float(head['prefix']),events=head['events'],source_policy=head.get('source_policy'))

def predict_packet(packet):
    required={'unit','duration_seconds','data'} | ({'initial'} if MODE=='held' else set())
    if set(packet) != required or set(packet['data']) != {'events_path','prepared_source_path'}:
        raise ValueError('익명 source packet 계약 불일치')
    if set(packet['unit']) - {'available','unit_id','numeric_tap_discarded'}:
        raise ValueError('단위 packet에 numeric tap 또는 다른 정보가 있습니다')
    with np.load(packet['data']['events_path'],allow_pickle=False) as file:
        events={k:file[k].copy() for k in file.files}
    if abs(float(events['duration'])-packet['duration_seconds'])>1e-7:
        raise ValueError('원본 duration 불일치')
    prepared=json.loads(Path(packet['data']['prepared_source_path']).read_text())
    baseline_prepared=prepared
    import candidate_initial_source as initial_source
    original_information_mass=initial_source.CONFIG['initial_information_mass']
    initial_source.CONFIG['initial_information_mass']=original_information_mass*4.
    try:
        rebuilt=initial_source.prepare(events,None)
    finally:
        initial_source.CONFIG['initial_information_mass']=original_information_mass
    if rebuilt['available']:
        mapped=[]
        for unit in prepared['units']:
            end=rebuilt['adaptive_initial_evidence_end']
            old=[{**c,'bootstrap_end':end} for c in unit['initials']]
            # A rebuilt bank can have fewer/different role centers. Reassign
            # each audio-derived BPM to the original source partition, rather
            # than copying a whole nearest rebuilt bucket into another unit.
            added=[]
            for source_unit in rebuilt['units']:
                for c in source_unit['initials']:
                    owner=min(baseline_prepared['units'],key=lambda u:(abs(np.log(c['bpm']/u['representative_bpm'])),u['id']))
                    if owner['id']==unit['id']:
                        added.append({**c,'initial_source_origin':'information_qualified_opening',
                                      'source_original_unit_id':unit['id']})
            mapped.append({**unit,'initials':old+added})
        prepared={**prepared,'units':mapped,'adaptive_initial_evidence_end':rebuilt['adaptive_initial_evidence_end']}
    trace=dict(source_only=True,mode=MODE,input_fields=sorted(packet),
               reference_received=False,retained_initials=[],expansions=[],proposal_calls=[],
               qualified_initial_count=0,meter_search_enabled=MODE=='full')
    target=core.base if IS_BASELINE and MODE=='full' else core
    original_heads=core.base.initial_heads
    def initial_heads(p,u,s):
        old_unit=next(x for x in baseline_prepared['units'] if x['id']==u['id'])
        old_heads=original_heads(baseline_prepared,old_unit,s)
        new_heads=original_heads(p,u,s)
        limit=core.CONFIG['initial_path_budget']
        reserve=limit//2
        heads=[];used=set()
        def append(head,policy):
            identity=tuple(head['initial'][k] for k in ('bpm','numerator','denominator','bar_zero_source_seconds'))+(policy,)
            if identity in used:return False
            heads.append({**head,'source_policy':policy});used.add(identity);return True
        for head in sorted(old_heads,key=lambda h:-h['score'])[:reserve]:
            append(head,'early_unrestricted')
        seen_bpms=set()
        for head in sorted(new_heads,key=lambda h:-h['score']):
            if head['initial']['bpm'] in seen_bpms:continue
            append(head,'qualified_local');seen_bpms.add(head['initial']['bpm'])
            if len(heads)>=limit:break
        for head in sorted(new_heads,key=lambda h:-h['score']):
            if len(heads)>=limit:break
            append(head,'qualified_local')
        trace['initial_root_reserve']={'early':sum(h['source_policy']=='early_unrestricted' for h in heads),
            'qualified':sum(h['source_policy']=='qualified_local' for h in heads),
            'budget':limit,'reference_or_source_identity_dispatch':False}
        trace['qualified_initial_count']=len(u['initials'])
        trace['retained_initials']=[short(h) for h in heads]
        return heads
    core.base.initial_heads=initial_heads
    original_proposals=target.proposals
    def proposals(head,p,s):
        rows,diag=original_proposals(head,p,s)
        old=head['active']
        changed_meter=lambda x:(x['numerator'],x['denominator'])!=(old['numerator'],old['denominator'])
        trace['proposal_calls'].append(dict(parent=short(head),diagnostics=diag,
            tempo_proposals=sum(x['bpm']!=old['bpm'] for x in rows),
            meter_proposals=sum(changed_meter(x) for x in rows),
            proposals=rows))
        return rows,diag
    target.proposals=proposals
    original_extend=target.extend
    def extend(head,p,s,gate):
        children,diag=original_extend(head,p,s,gate)
        trace['expansions'].append(dict(parent=short(head),children=len(children),
            best_children=[short(h) for h in sorted(children,key=lambda h:-h['score'])[:8]]))
        return children,diag
    target.extend=extend
    if IS_BASELINE and MODE=='full':
        result=core.fit(events,prepared,packet['unit'],'L2_DENSE_PROPOSALS')
    elif MODE=='full':
        result=core.fit(events,prepared,{'unit':packet['unit'],'available':packet['unit']['available'],'initial':{}})
    else:
        result=core.fit(events,prepared,{'initial':packet['initial']})
    core.base.initial_heads=original_heads
    from experiments.beat_event_stability_v1 import core as original_l2
    from experiments.beat_event_stability_v1.scoring import Score as LegacyScore
    from experiments.beat_event_map_v1.common import CONFIG as LegacyConfig
    from experiments.beat_event_map_v1.core import state,child_state
    candidate_result=result
    candidate_trace=dict(retained_initials=list(trace['retained_initials']),expansions=list(trace['expansions']),proposal_calls=list(trace['proposal_calls']))
    trace['candidate_branches']=candidate_trace
    legacy_proposals=original_l2.base.proposals
    legacy_extend=original_l2.base.extend
    trace['baseline_proposal_calls']=[]
    trace['baseline_expansions']=[]
    def old_proposals(head,p,s):
        rows,diag=legacy_proposals(head,p,s)
        old=head['active']
        trace['baseline_proposal_calls'].append(dict(parent=short(head),diagnostics=diag,
            meter_proposals=sum((x['numerator'],x['denominator'])!=(old['numerator'],old['denominator']) for x in rows)))
        return rows,diag
    def old_extend(head,p,s,g):
        children,diag=legacy_extend(head,p,s,g)
        trace['baseline_expansions'].append(dict(parent=short(head),children=len(children)))
        return children,diag
    original_l2.base.proposals=old_proposals
    original_l2.base.extend=old_extend
    baseline_result=original_l2.fit(events,baseline_prepared,packet['unit'],'L2_DENSE_PROPOSALS')
    legacy_score=LegacyScore(events)
    def source_cost(prediction):
        initial=prediction['initial']
        metas=[c for u in prepared['units'] for c in u['initials'] if all(abs(c[k]-initial[k])<=1e-9 for k in initial)]
        if not metas:raise ValueError('Source-qualified initial disappeared')
        meta=max(metas,key=lambda c:c['family_prior'])
        value=meta['family_prior']*float(legacy_score.w.sum())
        active=state(initial)
        for event in prediction['events']+[dict(time=prediction['duration_seconds'])]:
            value+=float(legacy_score.totals(active['bpm'],active['phase'],active['numerator'],active['denominator'],active['start'],event['time'])[0])
            if 'quarter' not in event:break
            b,n,d=active['bpm'],active['numerator'],active['denominator']
            new=child_state(active,event['time'],event['quarter'],event.get('bpm',b),event.get('numerator',n),event.get('denominator',d))
            rate=new['bpm']!=b;meter=(new['numerator'],new['denominator'])!=(n,d)
            cost=LegacyConfig['tempo_change_cost']*rate+LegacyConfig['meter_change_cost']*meter
            if rate and min(abs(new['bpm']/b/2-1),abs(new['bpm']/b/.5-1))<=LegacyConfig['octave_ratio_tolerance']:
                cost+=LegacyConfig['octave_change_extra_cost']
            value-=cost;active=new
        return value
    candidate_cost=source_cost(candidate_result);baseline_cost=source_cost(baseline_result)
    if abs(baseline_cost-baseline_result['source_score']*packet['duration_seconds'])>1e-7:
        raise ValueError('Original L2 source-cost reproduction failed')
    fallback=candidate_cost<baseline_cost-1e-9
    result=baseline_result if fallback else candidate_result
    trace['legacy_source_guard']=dict(candidate_cost=candidate_cost,baseline_cost=baseline_cost,
        selected='L2' if fallback else 'early_and_qualified_source_roots',reference_score_used=False,whole_map_selected=True,
        C_P_V_W_not_received=True)
    trace['retained_initials']=candidate_trace['retained_initials']
    trace['expansions']=candidate_trace['expansions']
    trace['proposal_calls']=candidate_trace['proposal_calls']
    trace['initial_information']={'information_mass':original_information_mass*4.,'source_evidence_end':prepared['adaptive_initial_evidence_end'],'tap_or_reference_used':False}
    trace['unit_partition_reconciliation']={'source_only':True,'numeric_tap_received':False,'all_units_prepared_before_selection':True,'original_partition_preserved':True,'rule':'nearest original audio-source role center in log BPM, tie by original unit id; candidate BPM itself remains source-only'}
    trace['episode_locality']={'source_only':True,'lookback':'max(old bar duration, old numerator source pulses) plus measured phase error','fixed_seconds_window':False,'source_end_bound_unchanged':True,'floor_to_legal_old_beat':True}
    trace['quarter_role_meter_gate']={'source_only':True,'tempo_cost_unchanged':True}
    trace['returned_native_map']={k:result.get(k) for k in ('status','initial','events','duration_seconds')}
    trace['distinct_expanded_initials']=len({tuple(x['parent']['initial'].values()) for x in trace['expansions']})
    trace['total_meter_proposals']=sum(x['meter_proposals'] for x in trace['proposal_calls'])
    return result,trace

def predict(packet):
    return predict_packet(packet)[0]

def predict_with_trace(packet):
    return predict_packet(packet)
