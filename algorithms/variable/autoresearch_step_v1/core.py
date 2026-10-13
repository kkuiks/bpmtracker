"""Frozen L2 search with exactly two task restrictions: pin initial, hold meter.

Proposals/extension and path selection are copied from the recorded baseline.
Only meter proposals are removed before candidate ranking/budget truncation.
No shared globals, historical source, guard, scores or budgets are modified.
"""
from experiments.beat_event_map_v1 import core as base
from experiments.beat_event_map_v1.core import nodes, child_state
from experiments.beat_event_map_v1.common import CONFIG as BASE_CONFIG
from experiments.beat_event_map_v1.source import rational
from experiments.beat_event_stability_v1.common import CONFIG as STABILITY_CONFIG
from experiments.beat_event_stability_v1.scoring import Score
from .common import HELD, CONSTANT
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
    if not pinned.get('initial'):
        return {'status': 'no_source_clock', 'duration_seconds': duration, 'events': []}
    return {'format': 'joljak-continuous-beat-map', 'version': 1, 'status': 'map',
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
        compatible=(error<=CONFIG['proposal_phase_tolerance_seconds']+2*run['rms_seconds'])&(t<run['end']+1e-8)
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
                         'evidence_start':float(t[i]),'evidence_end':run['end'],
                         'source_run':{k:run[k] for k in ['channel','start','end','observations','quality']}})
    for run in prepared['pulses']:
        nearest=None
        if getattr(score,'unit_hold',False):
            eligible=[rational(run['pulse_bpm']/f) for f in [.5,1.,2.]
                      if 30<=rational(run['pulse_bpm']/f)<=400]
            if eligible:nearest=min(eligible,key=lambda b:(abs(math.log(b/old['bpm'])),b))
        for factor in CONFIG['pulse_factors']:
            bpm=rational(run['pulse_bpm']/factor)
            if not 30<=bpm<=400 or bpm==old['bpm']:continue
            if getattr(score,'unit_hold',False) and bpm!=nearest:continue
            signatures=[(old['numerator'],old['denominator'])]
            for n,d in signatures:
                add(bpm,n,d,run,factor)
    rows.sort(key=lambda r:-r['proxy'])
    selected=rows[:CONFIG['extension_candidates']-CONFIG['evidence_candidate_reserve']]
    identities={(r['bpm'],r['numerator'],r['denominator'],r['time']) for r in selected}
    for r in sorted(rows,key=lambda r:-r['local_evidence_gain']):
        key=(r['bpm'],r['numerator'],r['denominator'],r['time'])
        if key in identities:continue
        selected.append(r);identities.add(key)
        if len(selected)>=CONFIG['extension_candidates']:break
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
            total=head['prefix']+float(pre)+float(post)-r['cost']
            evidence_end=min(score.duration,r['evidence_end'])
            old_evidence=float(score.totals(old['bpm'],old['phase'],old['numerator'],old['denominator'],r['time'],evidence_end)[0])
            new_evidence=float(score.totals(s['bpm'],s['phase'],s['numerator'],s['denominator'],r['time'],evidence_end)[0])
            local_gain=new_evidence-old_evidence-r['cost']
            if total<=head['score']+1e-6 and local_gain<=0:continue
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
            result.append({'initial':head['initial'],'active':s,'prefix':head['prefix']+float(pre)-r['cost'],
                           'score':total,'events':head['events']+[event],
                           'local_evidence_gain':local_gain,
                           'pending_prefix_quality':pending_quality,
                           'gates':head['gates']+[{'event':event,'source_run':r['source_run'],**trace}]})
    result.sort(key=lambda s:-s['score'])
    selected=result[:CONFIG['map_path_budget']]
    for item in sorted(result,key=lambda s:-s['pending_prefix_quality']):
        if any(item is x for x in selected):continue
        selected.append(item)
        if len(selected)>=CONFIG['map_path_budget']+CONFIG['pending_path_budget']:break
    return selected,diagnostic

def fit(events, prepared, pinned, progress=None, timings=None):
    if not pinned.get('initial'):
        return {'status': 'no_source_clock', 'duration_seconds': float(events['duration']),
                'events': []}
    import time
    timings = timings if timings is not None else {}
    stage_start = time.perf_counter()
    method = HELD
    packet = {'unit_id': pinned.get('unit_id')}
    score = Score(events)
    timings['score_initialization_seconds'] = time.perf_counter() - stage_start
    filtered = 0
    # Exactly the frozen L2 dense-proposal filter.
    # A fast grid fitted to every second/third real observation is a weak
    # subdivision hypothesis, not independent evidence for musical acceleration.
    pulses = [r for r in prepared['pulses'] if r['observed_expected_pulse_fraction']
              >= STABILITY_CONFIG['minimum_proposal_pulse_density']]
    filtered = len(prepared['pulses']) - len(pulses)
    prepared = {**prepared, 'pulses': pulses}
    heads = [pinned_head(prepared, pinned, score)]
    best = max(heads, key=lambda h: h['score'])
    frontier = heads
    search = []
    stagnant = 0
    stage_start = time.perf_counter()
    for depth in range(BASE_CONFIG['max_declarations']):
        next_heads, diagnostics = [], []
        for head in frontier:
            children, details = extend(head, prepared, score, True)
            next_heads.extend(children)
            diagnostics.append(details)
        search.append({'depth': depth, 'parents': len(frontier),
                       'improving_children': len(next_heads),
                       'old_beats_considered': sum(d['old_beats_considered'] for d in diagnostics),
                       'source_compatible_proposals': sum(d.get('source_compatible_proposals', 0)
                                                         for d in diagnostics)})
        if progress:
            progress(depth, len(next_heads), len(best['events']))
        if not next_heads:
            break
        next_heads.sort(key=lambda h: -h['score'])
        frontier, seen = [], set()

        def add(head):
            last = head['events'][-1]
            key = (head['active']['bpm'], head['active']['numerator'],
                   head['active']['denominator'], round(last['time'], 4))
            if key not in seen:
                seen.add(key)
                frontier.append(head)

        for head in next_heads:
            add(head)
            if len(frontier) >= BASE_CONFIG['map_path_budget']:
                break
        for head in sorted(next_heads, key=lambda h: -h['pending_prefix_quality']):
            add(head)
            if len(frontier) >= BASE_CONFIG['map_path_budget'] + BASE_CONFIG['pending_path_budget']:
                break
        winner = max(frontier, key=lambda h: h['score'])
        if winner['score'] > best['score'] + 1e-6:
            best, stagnant = winner, 0
        else:
            stagnant += 1
        if stagnant >= BASE_CONFIG['maximum_stagnant_search_depths']:
            search[-1]['stopped_after_nonimproving_search_depths'] = stagnant
            break
    timings['path_search_seconds'] = time.perf_counter() - stage_start
    result = base.prediction(best, score.duration, method, packet['unit_id'])
    result.update(search_trace=search, filtered_sparse_pulse_proposals=filtered,
                  stability_score='symmetric bar F1 and quarter PCM',
                  constant_tempo_forced=False)
    result['pinned_initial_preserved'] = result['initial'] == pinned['initial']
    result['initial_meter_held'] = True
    return result
