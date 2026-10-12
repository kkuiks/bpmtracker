"""Bounded joint search over initial phase, tempo, meter and old-beat declarations.

The old free-phase tables supply rate proposals only. Every likelihood below is
recomputed at the phase dictated by this particular continuous map.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import math
import numpy as np

from .common import CONFIG
from .score_audio import AudioScore
from .map import validate

def rational(value):
    return float(Fraction(float(value)).limit_denominator(CONFIG['rational_denominator']))

def rates_in_window(table, bank, left, right, count):
    time = table['time']; use = (time>=left)&(time<right)
    if not use.any(): use[np.argmin(abs(time-(left+right)/2))] = True
    scores = table['quality'][use].mean(axis=0)
    order = np.argsort(-scores,kind='stable')
    result = []
    for index in order:
        h = bank[int(index)]
        if not any(abs(h['bpm']-r['bpm'])<.01 for r in result):
            result.append({'bpm': h['bpm'], 'score': float(scores[index]), 'index': int(index)})
        if len(result)>=count: break
    return result

def family_proposals(family):
    if not family: return []
    records = [family['audio_only_original_proposal']]
    for layer in family.get('levels',[]):
        if layer.get('best'): records.append(layer['best'])
        records += layer.get('top_candidates',[])[:3]
    return [{'bpm':r['quarter_bpm'], 'phase':r['offset_seconds'], 'score':r['score']} for r in records]

def prepare_source(events, table, bank, family=None):
    audio = AudioScore(events); duration = audio.duration
    early = rates_in_window(table,bank,0,min(duration,CONFIG['initial_window_seconds']),CONFIG['initial_rate_proposals'])
    global_rates = rates_in_window(table,bank,0,duration,CONFIG['initial_rate_proposals'])
    family_values = family_proposals(family)
    rates = set()
    for proposal in early+global_rates:
        for f in CONFIG['pulse_factors']:
            b = rational(proposal['bpm']/f)
            if 30<=b<=400: rates.add(b)
    for proposal in family_values:
        if 30<=proposal['bpm']<=400: rates.add(float(proposal['bpm']))
    initials = []
    quality = table['quality'][(table['time']<CONFIG['initial_window_seconds'])].mean(axis=0)
    global_quality = table['quality'].mean(axis=0)
    rank = .75*quality+.25*global_quality
    for bpm in sorted(rates):
        period = 60/bpm; phases=[]
        def add(value):
            value = float(value)%period
            if not any(min(abs(value-p),period-abs(value-p))<.004 for p in phases): phases.append(value)
        for record in family_values:
            if abs(math.log(record['bpm']/bpm))<.03: add(record['phase'])
        compatible = [i for i,h in enumerate(bank) if min(abs(math.log(h['bpm']/bpm/f)) for f in CONFIG['pulse_factors'])<.025]
        for i in sorted(compatible,key=lambda i:(-rank[i],i)):
            add(bank[i]['phase'])
            if len(phases)>=CONFIG['initial_phase_proposals_per_rate']: break
        if not phases: continue
        for n,d in CONFIG['signatures']:
            bar = period*n*4/d
            for phi in phases[:CONFIG['initial_phase_proposals_per_rate']]:
                for k in range(math.ceil(n*4/d)):
                    offset = (phi+k*period)%bar
                    if offset>1e-8: offset-=bar
                    initials.append({'bpm':bpm,'numerator':n,'denominator':d,'bar_zero_source_seconds':offset})
    values = []
    for start in range(0,len(initials),128):
        batch = initials[start:start+128]
        args = [[p[k] for p in batch] for k in ['bpm','bar_zero_source_seconds','numerator','denominator']]
        first = audio.batch(*args,0,min(duration,CONFIG['initial_window_seconds']))
        whole = audio.batch(*args,0,duration)
        values.extend(zip((.75*first+.25*whole).tolist(),whole.tolist()))
    for p,(quality,whole) in zip(initials,values):
        p['proposal_score']=quality; p['constant_source_score']=whole
    initials.sort(key=lambda p:(-p['proposal_score'],p['bpm'],p['numerator'],p['denominator'],p['bar_zero_source_seconds']))
    # A unit is a discrete metrical role relative to ONE source-created pulse.
    # It is not an arbitrary partition of fine BPM estimates. Fine alternatives
    # remain inside each role and are selected using audio after discarding tap.
    root_pulse=early[0]['bpm'] if early else global_rates[0]['bpm']
    units=[]
    for multiplier in sorted({1/f for f in CONFIG['pulse_factors']}):
        center=root_pulse*multiplier
        if not 30<=center<=400:continue
        candidates=[p for p in initials if abs(math.log(p['bpm']/center))<=CONFIG['initial_rate_radius']]
        if not candidates:continue
        units.append({'id':len(units),'counting_multiplier':multiplier,'audio_root_pulse_bpm':root_pulse,
                      'representative_bpm':center,'initials':candidates[:CONFIG['initial_states_per_unit']],
                      'source_score':candidates[0]['proposal_score']})
    return {'source_only':True,'duration_seconds':duration,'units':units,
            'prepared_before_tap':True,'no_meter_or_tempo_reference_read':True,
            'best_audio_only_unit':max(units,key=lambda u:u['source_score'])['id'] if units else None,
            'source_events':len(events['times'])}

def encode_unit(prepared, tap):
    if not prepared['units']: return {'available':False}
    units=prepared['units']
    unit=(max(units,key=lambda u:u['source_score']) if tap is None else
          min(units,key=lambda u:(abs(math.log(float(tap)/u['representative_bpm'])), -u['source_score'],u['id'])))
    # The numeric tap ends here; it is not copied into the prediction input.
    return {'available':True,'unit_id':unit['id'],'source_prepared_units':True}

@dataclass(frozen=True)
class State:
    initial: dict
    bpm: float
    numerator: int
    denominator: int
    anchor_time: float
    anchor_q: float
    bar_q: float
    events: tuple
    total: float=0.
    last_tempo: float=-1e9
    last_meter: float=-1e9

    @property
    def phase(self): return self.anchor_time+(self.bar_q-self.anchor_q)*60/self.bpm
    def quarter(self,time): return self.anchor_q+(time-self.anchor_time)*self.bpm/60

def initial_state(p):
    initial={k:p[k] for k in ['bpm','numerator','denominator','bar_zero_source_seconds']}
    return State(initial,p['bpm'],p['numerator'],p['denominator'],p['bar_zero_source_seconds'],0.,0.,())

def prune(states, priorities, size):
    order=np.argsort(-np.asarray(priorities),kind='stable');seen=set();counts={};result=[]
    for i in order:
        s=states[int(i)];bar=60/s.bpm*s.numerator*4/s.denominator
        key=(s.bpm,s.numerator,s.denominator,round((s.phase%bar)/.004))
        if key in seen or counts.get(s.bpm,0)>=max(6,size//3): continue
        result.append(s); seen.add(key); counts[s.bpm]=counts.get(s.bpm,0)+1
        if len(result)>=size: break
    return result

def batch_states(audio, states, left, right):
    return audio.batch([s.bpm for s in states],[s.phase for s in states],
                       [s.numerator for s in states],[s.denominator for s in states],left,right)

def prediction_from_state(state,duration,source_score):
    return {'format':'joljak-continuous-beat-map','version':1,'status':'map',
            'duration_seconds':duration,'initial':state.initial,'events':list(state.events),
            'source_score':source_score,'confidence_does_not_mute':True,
            'free_phase_parameters_after_start':0,'beat_definition':'notated denominator beat',
            'tap_numeric_value_retained':False,'meter_predicted_from_audio':True}

def fit(events,table,bank,prepared,packet,changes=True):
    if not packet.get('available') or prepared['source_events']<CONFIG['minimum_source_events']:
        return {'status':'no_source_clock','duration_seconds':prepared['duration_seconds'],'events':[],
                'tap_cannot_supply_phase_or_clock':True}
    unit=prepared['units'][packet['unit_id']]
    if unit['source_score']<CONFIG['minimum_initial_source_score']:
        return {'status':'no_source_clock','duration_seconds':prepared['duration_seconds'],'events':[],
                'tap_cannot_supply_phase_or_clock':True}
    audio=AudioScore(events);duration=audio.duration
    states=[initial_state(p) for p in unit['initials']]
    constant_states=states
    constant_totals=np.zeros(len(constant_states))
    for left in np.arange(0,duration,CONFIG['proposal_step_seconds']):
        right=min(duration,float(left+CONFIG['proposal_step_seconds']))
        constant_totals+=(right-left)*batch_states(audio,constant_states,left,right)
    if not changes:
        winner=states[int(np.argmax(constant_totals))]
        return prediction_from_state(winner,duration,float(max(constant_totals)/duration))
    early=batch_states(audio,states,0,min(duration,CONFIG['lookahead_seconds']))
    priorities=early+np.asarray([p['proposal_score'] for p in unit['initials']])
    states=prune(states,priorities,CONFIG['beam_size'])
    step=CONFIG['proposal_step_seconds'];trace=[]
    for left in np.arange(0,duration,step):
        right=min(duration,float(left+step));length=right-left
        previous=states;old_local=batch_states(audio,previous,left,right)
        base_rates=rates_in_window(table,bank,left,min(duration,left+CONFIG['lookahead_seconds']),CONFIG['local_rate_proposals'])
        proposed=set()
        for r in base_rates:
            for f in CONFIG['pulse_factors']:
                b=rational(r['bpm']/f)
                if 30<=b<=400: proposed.add(b)
        # Rank rate proposals on an audio-created phase, never on a free-phase output.
        # Keep diverse source rates; every child is scored again at its derived phase.
        proposals=sorted(proposed)
        children=[];parent_indices=[];change_times=[];costs=[]
        for pi,s in enumerate(previous):
            children.append(s);parent_indices.append(pi);change_times.append(left);costs.append(0.)
            if left<step: continue
            beat=4/s.denominator
            first=s.bar_q+math.ceil((s.quarter(left)-s.bar_q-1e-8)/beat)*beat
            nodes=[]
            for k in range(CONFIG['local_change_beat_proposals']):
                q=first+k*beat;t=s.anchor_time+(q-s.anchor_q)*60/s.bpm
                if t<right-1e-8 and t>0: nodes.append((t,q))
            for time,q in nodes:
                tempo_allowed=time-max(0,s.last_tempo)>=CONFIG['minimum_tempo_hold_seconds']
                meter_allowed=time-max(0,s.last_meter)>=CONFIG['minimum_meter_hold_seconds']
                combinations=[(s.bpm,n,d) for n,d in CONFIG['signatures'] if meter_allowed and (n,d)!=(s.numerator,s.denominator)]
                if tempo_allowed:
                    combinations += [(b,s.numerator,s.denominator) for b in proposals if b!=s.bpm]
                    # Combined changes are proposed for the common and compound interpretations.
                    if meter_allowed:
                        combinations += [(b,n,d) for b in proposals if b!=s.bpm for n,d in [(3,4),(4,4),(6,8)] if (n,d)!=(s.numerator,s.denominator)]
                for bpm,n,d in combinations:
                    changed_rate=bpm!=s.bpm;changed_meter=(n,d)!=(s.numerator,s.denominator)
                    event={'time':time,'quarter':q}
                    cost=0.
                    if changed_rate:
                        event['bpm']=bpm;cost+=CONFIG['tempo_change_cost_seconds']
                        ratio=bpm/s.bpm
                        if min(abs(ratio/2-1),abs(ratio/.5-1))<=CONFIG['octave_ratio_tolerance']:
                            cost+=CONFIG['octave_change_extra_cost_seconds']
                    if changed_meter:
                        event.update(numerator=n,denominator=d);cost+=CONFIG['meter_change_cost_seconds']
                    child=State(s.initial,bpm,n,d,time,q,q if changed_meter else s.bar_q,s.events+(event,),
                                s.total,time if changed_rate else s.last_tempo,time if changed_meter else s.last_meter)
                    children.append(child);parent_indices.append(pi);change_times.append(time);costs.append(cost)
        starts=np.asarray(change_times);parents=np.asarray(parent_indices);costs=np.asarray(costs)
        # Integrate the preceding piece up to the shared beat and the new piece after it.
        old_prefix=batch_states(audio,[previous[i] for i in parents],left,starts)
        new_tail=batch_states(audio,children,starts,right)
        local=((starts-left)*old_prefix+(right-starts)*new_tail)
        # A hold has no old prefix and retains exactly the same clock.
        totals=np.asarray([s.total for s in children])+local-costs
        ahead=batch_states(audio,children,right,min(duration,right+CONFIG['lookahead_seconds'])) if right<duration else np.zeros(len(children))
        ranked=totals+CONFIG['lookahead_score_seconds']*ahead
        updated=[replace(s,total=float(total)) for s,total in zip(children,totals)]
        states=prune(updated,ranked,CONFIG['beam_size'])
        best=max(states,key=lambda s:s.total)
        trace.append({'start':float(left),'end':right,'best_source_score':float(best.total/max(right,1e-9)),
                      'states_considered':len(children),'confidence_only':True})
    # Preserve the full-song starting hypotheses. A weak opening cannot discard a
    # source-supported initial phase that is corroborated by later source audio.
    winner=max(states,key=lambda s:s.total)
    constant_index=int(np.argmax(constant_totals))
    if constant_totals[constant_index]>winner.total:
        winner=replace(constant_states[constant_index],total=float(constant_totals[constant_index]))
    result=prediction_from_state(winner,duration,winner.total/duration)
    result['source_confidence_trace']=trace
    result['unit_id']=packet['unit_id'];result['search']={'beam_size':CONFIG['beam_size'],'proposal_step_seconds':step}
    check=validate(result)
    if not check['legal']: raise RuntimeError(('Invalid constructed map',check))
    return result
