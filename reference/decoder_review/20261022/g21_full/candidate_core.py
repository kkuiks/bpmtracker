"""Frozen L2 search with exactly two task restrictions: pin initial, hold meter.

Proposals/extension and path selection are copied from the recorded baseline.
Only meter proposals are removed before candidate ranking/budget truncation.
No shared globals, historical source, guard, scores or budgets are modified.
"""
from experiments.beat_event_map_v1 import core as base
from experiments.beat_event_map_v1.core import nodes, child_state
from candidate_common import CONFIG as BASE_CONFIG
from experiments.beat_event_map_v1.source import rational
from candidate_common import CONFIG as STABILITY_CONFIG
from candidate_emissions import Score
HELD = "PINNED_INITIAL_HELD_METER_L2"
CONSTANT = "PINNED_INITIAL_CONSTANT_MAP"
import math
import numpy as np

CONFIG = BASE_CONFIG


def pinned_head(prepared, pinned, score):
    values = pinned['initial']
    names = ('bpm', 'numerator', 'denominator', 'bar_zero_source_seconds')
    candidates = [c for unit in prepared['units'] for c in unit['initials']
                  if all(abs(c[k] - values[k]) <= 1e-9 for k in names)]
    if not candidates:
        raise RuntimeError('Pinned L2 initial is absent from source-only candidates')
    initial = max(candidates, key=lambda c: c['family_prior'])
    # Keep every exact pinned scalar, not the tolerance-matched candidate value.
    initial = {**initial, **values}
    s = base.state(initial)
    prior = initial['family_prior'] * float(score.w.sum())
    total = float(score.totals(s['bpm'], s['phase'], s['numerator'],
                              s['denominator'], 0, score.duration)[0]) + prior
    return {'initial': initial, 'active': s, 'prefix': prior, 'score': total,
            'events': [], 'gates': []}


def constant_map(pinned, duration):
    if not pinned.get('available'):
        return {'status': 'no_source_clock', 'duration_seconds': duration, 'events': []}
    return {'format': 'bpmtracker-continuous-beat-map', 'version': 1, 'status': 'map',
            'duration_seconds': duration, 'initial': dict(pinned['initial']),
            'events': [], 'method': CONSTANT, 'unit_id': pinned.get('unit_id'),
            'free_phase_parameters_after_start': 0, 'initial_meter_held': True,
            'pinned_initial_preserved': True, 'constant_tempo_forced': True,
            'initial_source_origin': pinned.get('initial_source_origin'),
            'adaptive_initial_evidence_end': pinned.get('adaptive_initial_evidence_end')}

def proposals(head,prepared,score):
    old=head['active'];duration=score.duration;t,q=nodes(old,duration)
    if not len(t):return [],{'old_beats_considered':0}
    use=score.t>=old['start'];times=score.t[use];weights=score.w[use]
    old_values=score.pulse_values(old['bpm'],old['phase'],times)
    old_cum=np.r_[0.,np.cumsum(old_values*weights)];mass_cum=np.r_[0.,np.cumsum(weights)]
    at=np.searchsorted(times,t);prefix_mass=mass_cum[at];suffix_mass=mass_cum[-1]-prefix_mass
    prefix_explain=old_cum[at]/np.maximum(prefix_mass,1e-9)
    length=t-old['start'];tail=duration-t
    db_use=score.bt>=old['start'];dt=score.bt[db_use];dw=score.bw[db_use]
    old_bar_values=score.bar_values(old['bpm'],old['phase'],old['numerator'],old['denominator'],dt)
    old_bar_cum=np.r_[0.,np.cumsum(old_bar_values*dw)];bar_mass=np.r_[0.,np.cumsum(dw)]
    da=np.searchsorted(dt,t);prefix_bar=old_bar_cum[da]/np.maximum(bar_mass[da],1e-9)
    new_bar_mass=bar_mass[-1]-bar_mass[da]
    rows=[];seen=set();pulse_cache={};episode_cache={};bar_proxy_cache={}
    baseline=CONFIG['beat_weight']*(old_cum[-1]/max(mass_cum[-1],1e-9))*(duration-old['start'])
    baseline+=CONFIG['bar_weight']*(old_bar_cum[-1]/max(bar_mass[-1],1e-9))*(duration-old['start'])
    def add(bpm,n,d,run,factor=None):
        changed_rate=bpm!=old['bpm'];changed_meter=(n,d)!=(old['numerator'],old['denominator'])
        if not changed_rate and not changed_meter:return
        barq=q if changed_meter else np.full(len(q),old['bar_quarter'])
        phase=t+(barq-q)*60/bpm
        if factor is not None:
            p=60/run['pulse_bpm']
            distances=[]
            for off in ([0.,.5*60/bpm] if score.role_mixture else [0.]):
                residual=(phase+off-run['phase']+p/2)%p-p/2
                distances.append(abs(residual))
            error=np.min(distances,axis=0)
        else:
            p=60/run['pulse_bpm'];error=abs((t-run['phase']+p/2)%p-p/2)
        # A later source episode may not justify arbitrary earlier changes.
        # Permit one physical source group before its first observation, so an
        # unobserved onset can still lie on a legal old beat. No new phase fits.
        old_bar_seconds=old['numerator']*4/old['denominator']*60/old['bpm']
        source_group=(old['numerator'] if run['channel']=='BEAT' else 1)*60/run['pulse_bpm']
        phase_error=CONFIG['proposal_phase_tolerance_seconds']+2*run['rms_seconds']
        support_start=run['start']-max(old_bar_seconds,source_group)-phase_error
        # Preserve the preceding admissible old beat when the source support
        # bound lies between beats. Geometry still comes only from nodes(old).
        support_raw_start=support_start
        support_index=int(np.searchsorted(t,support_start,side='right'))-1
        if support_index>=0:
            support_start=float(t[min(support_index,len(t)-1)])
        compatible=(error<=phase_error)&(t<run['end']+1e-8)
        if head['source_policy']=='qualified_local':compatible&=(t>=support_start-1e-8)
        indices=np.flatnonzero(compatible)
        if not len(indices):return
        # Every old beat was considered for compatibility; rank by source
        # evidence, never by membership in a fixed wall-clock boundary bin.
        pulse_phase=run['phase'] if factor is not None else old['phase']
        key=(bpm,round(pulse_phase/.006))
        if key not in pulse_cache:
            value=score.pulse_values(bpm,pulse_phase,times)
            pulse_cache[key]=np.r_[0.,np.cumsum(value*weights)]
        new_cum=pulse_cache[key];suffix=(new_cum[-1]-new_cum[at])/np.maximum(suffix_mass,1e-9)
        score_beat=prefix_explain*length+suffix*tail
        bar_key=(bpm,n,d)
        if bar_key not in bar_proxy_cache:
            values=np.zeros(len(t))
            for offset in range(0,len(t),128):
                selected=np.arange(offset,min(offset+128,len(t)))
                period=60/bpm*n*4/d
                residual=(dt[None,:]-phase[selected,None]+period/2)%period-period/2
                valid=dt[None,:]>=t[selected,None]
                sums=(np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)*dw[None,:]*valid).sum(axis=1)
                after=sums/np.maximum(new_bar_mass[selected],1e-9)
                values[selected]=prefix_bar[selected]*length[selected]+after*tail[selected]
            bar_proxy_cache[bar_key]=values
        score_bar=bar_proxy_cache[bar_key][indices]
        cost=CONFIG['tempo_change_cost']*changed_rate+CONFIG['meter_change_cost']*changed_meter
        if changed_rate and min(abs(bpm/old['bpm']/2-1),abs(bpm/old['bpm']/.5-1))<=CONFIG['octave_ratio_tolerance']:
            cost+=CONFIG['octave_change_extra_cost']
        prior=CONFIG['meter_prior'][f'{n}/{d}']-CONFIG['meter_prior'][f"{old['numerator']}/{old['denominator']}"]
        proxy=CONFIG['beat_weight']*score_beat[indices]+CONFIG['bar_weight']*score_bar-baseline-cost-prior*tail[indices]
        episode_key=(run['first_index'],run['last_index'],run['channel'])
        if episode_key not in episode_cache:
            if run['channel']=='BEAT':
                inside=(times>=run['start'])&(times<run['end']);mass=float(weights[inside].sum())
                agreement=float(np.sum(score.pulse_values(old['bpm'],old['phase'],times[inside])*weights[inside])/max(mass,1e-9))
            else:
                inside=(dt>=run['start'])&(dt<run['end']);mass=float(dw[inside].sum())
                agreement=float(np.sum(old_bar_values[inside]*dw[inside])/max(mass,1e-9))
            episode_cache[episode_key]=(agreement,mass)
        agreement,mass=episode_cache[episode_key]
        local=(np.exp(-.5*(error[indices]/CONFIG['neural_sigma_seconds'])**2)-agreement)*mass-cost
        # Keep strongly supported short episodes even if their final continuation
        # loses: a later return or a second new tempo may complete the explanation.
        order=list(np.argsort(-proxy,kind='stable')[:8])
        order+=list(np.argsort(-local,kind='stable')[:4])
        for local_index in dict.fromkeys(order):
            i=int(indices[int(local_index)]);identity=(bpm,n,d,round(float(t[i]),7))
            if identity in seen:continue
            seen.add(identity)
            rows.append({'time':float(t[i]),'quarter':float(q[i]),'bpm':bpm,'numerator':n,'denominator':d,
                         'proxy':float(proxy[int(local_index)]),'local_evidence_gain':float(local[int(local_index)]),'cost':cost,
                         'evidence_start':float(t[i]),'evidence_end':run['end'],'source_support_start':float(support_start),'source_support_raw_start':float(support_raw_start),'source_policy':head['source_policy'],
                         'source_run':{k:run[k] for k in ['channel','start','end','observations','quality']}})
    for run in prepared['pulses']:
        nearest=None;physical_nearest=None
        if getattr(score,'unit_hold',False):
            eligible=[rational(run['pulse_bpm']/f) for f in [.5,1.,2.]
                      if 30<=rational(run['pulse_bpm']/f)<=400]
            if eligible:nearest=min(eligible,key=lambda b:(abs(math.log(b/old['bpm'])),b))
            if eligible:physical_nearest=min(eligible,key=lambda b:(abs(math.log((b*old['denominator']/4)/run['pulse_bpm'])),b))
        for factor in CONFIG['pulse_factors']:
            bpm=rational(run['pulse_bpm']/factor)
            if not 30<=bpm<=400 or bpm==old['bpm']:continue
            if getattr(score,'unit_hold',False) and bpm != nearest:continue
            signatures=CONFIG['signatures'] if getattr(score,'unit_hold',False) else {(old['numerator'],old['denominator']),(4,4),(3,4),(6,8)}
            for n,d in signatures:
                add(bpm,n,d,run,factor)
    for n,d in CONFIG['signatures']:
        if (n,d)==(old['numerator'],old['denominator']):continue
        for run in prepared['bars']:
            target=old['bpm']/(n*4/d)
            if abs(math.log(run['pulse_bpm']/target))<.10:add(old['bpm'],n,d,run)
    rows.sort(key=lambda r:-r['proxy'])
    def kind(r):
        rate=r['bpm']!=old['bpm']
        meter=(r['numerator'],r['denominator'])!=(old['numerator'],old['denominator'])
        return (rate,meter)
    groups={k:[r for r in rows if kind(r)==k] for k in [(True,False),(False,True),(True,True)]}
    groups={k:v for k,v in groups.items() if v}
    selected=[];identities=set()
    cap=CONFIG['extension_candidates']
    def take(bank,budget):
        reserve=round(budget*CONFIG['evidence_candidate_reserve']/cap)
        picked=list(bank[:budget-reserve])
        seen={(r['bpm'],r['numerator'],r['denominator'],r['time']) for r in picked}
        for r in sorted(bank,key=lambda r:-r['local_evidence_gain']):
            key=(r['bpm'],r['numerator'],r['denominator'],r['time'])
            if key in seen:continue
            picked.append(r);seen.add(key)
            if len(picked)>=budget:break
        return picked[:budget]
    if groups:
        budget=cap//len(groups)
        for bank in groups.values():
            for r in take(bank,budget):
                key=(r['bpm'],r['numerator'],r['denominator'],r['time'])
                selected.append(r);identities.add(key)
    for r in rows:
        if len(selected)>=cap:break
        key=(r['bpm'],r['numerator'],r['denominator'],r['time'])
        if key not in identities:selected.append(r);identities.add(key)
    return selected,{'old_beats_considered':len(t),'source_compatible_proposals':len(rows)}

def extend(head,prepared,score,gate):
    rows,diagnostic=proposals(head,prepared,score);old=head['active'];result=[]
    for offset in range(0,len(rows),64):
        batch=rows[offset:offset+64]
        children=[child_state(old,r['time'],r['quarter'],r['bpm'],r['numerator'],r['denominator']) for r in batch]
        ends=np.array([r['time'] for r in batch])
        before=score.totals(old['bpm'],old['phase'],old['numerator'],old['denominator'],old['start'],ends)
        after=score.totals([s['bpm'] for s in children],[s['phase'] for s in children],[s['numerator'] for s in children],[s['denominator'] for s in children],ends,score.duration)
        for r,s,pre,post in zip(batch,children,before,after):
            changed_rate=s['bpm']!=old['bpm'];changed_meter=(s['numerator'],s['denominator'])!=(old['numerator'],old['denominator'])
            trace={'required':gate,'permit':True}
            if gate:
                passed,trace=score.gate(old,s,r['evidence_start'],r['evidence_end'],changed_rate,changed_meter)
                if not passed:continue
            if changed_meter:
                # 같은 새 BPM/quarter geometry에서 meter 필요성만 비교합니다.
                rate_only=child_state(old,r['time'],r['quarter'],s['bpm'],old['numerator'],old['denominator'])
                evidence_end=min(score.duration,r['evidence_end'])
                if evidence_end<=r['time']:continue
                role_gain=(score.meter_role_score(s,r['time'],evidence_end)
                    -score.meter_role_score(rate_only,r['time'],evidence_end)-CONFIG['meter_change_cost'])
                trace['quarter_role_meter_gain']=float(role_gain)
                trace['quarter_role_meter_gate']=True
                if role_gain<=0.:continue
            total=head['prefix']+float(pre)+float(post)-r['cost']
            evidence_end=min(score.duration,r['evidence_end'])
            old_evidence=float(score.totals(old['bpm'],old['phase'],old['numerator'],old['denominator'],r['time'],evidence_end)[0])
            new_evidence=float(score.totals(s['bpm'],s['phase'],s['numerator'],s['denominator'],r['time'],evidence_end)[0])
            local_gain=new_evidence-old_evidence-r['cost']
            # Retain locally admitted changes even when constant-tail cost loses.
            # A later return may complete this finite source proposal graph.
            # Compare complete observed prefixes, not improvement over a possibly
            # very poor parent. Otherwise repairing a wrong initial clock can
            # evict a correct short episode solely through its larger delta.
            evidence_mass=0.
            for index,key in enumerate(['beat_weight','bar_weight','pcm_weight']):
                stop=np.searchsorted(score.audio.channels[index][0],evidence_end)
                evidence_mass+=CONFIG[key]*float(score.cumulative[index][stop])
            pending_quality=(head['prefix']+float(pre)-r['cost']+new_evidence)/max(evidence_mass,1e-9)
            event={'time':r['time'],'quarter':r['quarter']}
            if changed_rate:event['bpm']=s['bpm']
            if changed_meter:event.update(numerator=s['numerator'],denominator=s['denominator'])
            result.append({'initial':head['initial'],'source_policy':head['source_policy'],'active':s,'prefix':head['prefix']+float(pre)-r['cost'],
                           'score':total,'events':head['events']+[event],
                           'local_evidence_gain':local_gain,
                           'pending_prefix_quality':pending_quality,
                           'gates':head['gates']+[{'event':event,'source_run':r['source_run'],**trace}]})
    return result,diagnostic

def exact_state_key(head):
    """Only merge states with the same future dynamics and declaration budget."""
    s=head['active']
    return tuple(s[k] for k in ('bpm','numerator','denominator','anchor_time',
        'anchor_quarter','bar_quarter','phase','start'))+(len(head['events']),head['source_policy'])

def fit(events, prepared, pinned, progress=None, timings=None):
    import time, heapq
    if not pinned.get('available'):
        return {'status':'no_source_clock','duration_seconds':float(events['duration']),'events':[]}
    started=time.perf_counter();score=Score(events)
    pulses=[r for r in prepared['pulses'] if r['observed_expected_pulse_fraction']
            >= CONFIG['minimum_proposal_pulse_density']]
    prepared={**prepared,'pulses':pulses}
    from candidate_unit_policy import select_source_unit
    unit_packet=pinned['unit']
    unit=next(u for u in prepared['units'] if u['id']==unit_packet['unit_id'])
    heads=base.initial_heads(prepared,unit,score)
    best=max(heads,key=lambda h:h['score'])
    queue=[((0.,-head['score']),i,head) for i,head in enumerate(heads)];heapq.heapify(queue)
    serial=len(heads);dominance={exact_state_key(head):head['prefix'] for head in heads}
    diagnostics=[];expanded=0;pruned=0;queue_drops=0;best_updates=[]
    # Finite source-derived proposal graph; the resource limits make this
    # approximate. A complete constant tail is a scheduling heuristic only.
    # Pointwise log emissions are nonpositive, so prefix is an upper bound on
    # every completion. This is the only score-based path pruning bound.
    while queue and expanded<CONFIG.get('decoder_expansion_budget',36):
        _,_,head=heapq.heappop(queue)
        if head['prefix']<dominance.get(exact_state_key(head),head['prefix'])-1e-9:continue
        if head['prefix']<=best['score']+1e-9:
            pruned+=1;continue
        if len(head['events'])>=CONFIG['max_declarations']:continue
        children,diag=extend(head,prepared,score,True);expanded+=1
        diagnostics.append(dict(expansion=expanded,children=len(children),**diag))
        for child in children:
            # Stop at the audio end, completing the active affine segment.
            if child['score']>best['score']+1e-9:
                best=child;best_updates.append(dict(expansion=expanded,score=child['score'],events=len(child['events'])))
            key=exact_state_key(child)
            if child['prefix']<=dominance.get(key,-float('inf'))+1e-9:continue
            dominance[key]=child['prefix']
            if child['prefix']<=best['score']+1e-9:pruned+=1;continue
            serial+=1;heapq.heappush(queue,((1.,-child['score']),serial,child))
        limit=CONFIG.get('decoder_queue_budget',128)
        if len(queue)>limit:
            queue_drops+=len(queue)-limit
            queue=heapq.nsmallest(limit,queue);heapq.heapify(queue)
        if progress:progress(expanded,len(queue),len(best['events']))
    result=base.prediction(best,score.duration,'RESEARCH_FULL_L2_ADDITIVE_PATH',unit_packet['unit_id'])
    result.update(search_trace=diagnostics,pinned_initial_preserved=result['initial']==pinned['initial'],
        initial_meter_held=False,constant_tempo_forced=False,full_L2_initial_and_meter_search=True,
        decoder={'segment_cost':'weighted pointwise source log emissions',
        'state':'exact continuous anchor and bar phase, held meter, declaration budget',
        'dominance':'same future state; highest completed prefix',
        'pruning_bound':'nonpositive future log emissions and transition costs',
        'approximate':True,'expansions':expanded,'queue_drops':queue_drops,
        'bound_prunes':pruned,'remaining_queue':len(queue),'best_updates':best_updates,
        'backtrace':'stored parent event chain','empty_expected_ticks_penalized':False})
    timings=timings if timings is not None else {};timings['path_search_seconds']=time.perf_counter()-started
    return result
