"""Clock selection and rendering, without file I/O or evaluation references."""
from __future__ import annotations

import math
from .common import CONFIG, object_hash
from .evidence import equivalent, harmonic


def source_base(ev):
    for i,t in enumerate(ev.time):
        if t>ev.cfg['seed_deadline']: break
        choices=ev.qualified(i,seed=True)
        if choices:
            groups=ev.groups(i,choices)
            j=groups[0][0]
            return {'audio_base_bpm':ev.bank[j]['bpm'],'time':float(t),'detail':ev.detail(i,j)}
    return {'audio_base_bpm':None,'reason':'NO_SOURCE_SEED_CANDIDATE_BY_DEADLINE'}


def bootstrap(ev, initial):
    base=source_base(ev)
    result={'audio_base_bpm':base['audio_base_bpm'],'base_time':base.get('time'),
            'input':initial,'status':'NO_SEED','seed':None}
    if initial.get('kind')=='unavailable' or base['audio_base_bpm'] is None:
        return dict(result,reason=initial.get('reason',base.get('reason')))
    from experiments.metronome_reconstruction_v1.hinted import encode_tap_level
    from experiments.variable_tempo_interval_consensus_v0.core import quantize
    allowed=[]
    for j,h in enumerate(ev.bank):
        if initial['kind']=='oracle':
            permit=abs(h['bpm']-quantize(initial['initial_bpm']))<=1e-8
        else:
            level=encode_tap_level(base['audio_base_bpm'],h['bpm'])
            permit=level['power'] is not None and level['power']==initial['power']
        if permit: allowed.append(j)
    result['allowed_bank_clocks']=len(allowed)
    if not allowed:
        return dict(result,reason='INITIAL_RATE_OR_UNIT_ABSENT_FROM_FINAL_BANK')
    allowed=set(allowed)
    for i,t in enumerate(ev.time):
        if t>ev.cfg['seed_deadline']: break
        groups=ev.groups(i,[j for j in ev.qualified(i,seed=True) if j in allowed])
        if not groups: continue
        j=groups[0][0]; margin=ev.margin(i,j,groups)
        if margin+1e-12>=ev.cfg['margin']:
            result.update(status='SEEDED',reason='FIRST_ELIGIBLE_INITIAL_CLOCK',
                          seed={'index':j,'time':float(t),'key':ev.bank[j]['key'],
                                'clock':ev.bank[j],'evidence':ev.detail(i,j,True),'margin':margin})
            break
    if not result['seed']: result['reason']='INITIAL_CLOCK_NOT_QUALIFIED_OR_AMBIGUOUS_BY_DEADLINE'
    return result


def _pieces(ev,start,end,status,clock,reason):
    from experiments.variable_tempo_interval_consensus_v0.core import silence_intervals
    boundaries={start,end}
    silent=[]
    for a,b in ev.silence:
        if a<end and b>start:
            a,b=max(a,start),min(b,end)
            boundaries.update((a,b)); silent.append((a,b))
    points=sorted(boundaries)
    for a,b in zip(points,points[1:]):
        is_silent=any(x<=a<y for x,y in silent)
        record={'start':a,'end':b,'status':'UNKNOWN' if is_silent else status,
                'reason':'STRICT_SOURCE_SILENCE' if is_silent else reason}
        if record['status']=='ACCEPTED':
            record.update({k:clock[k] for k in ('key','bpm','phase')},period=60./clock['bpm'])
        yield record


def predict(ev, shared_bootstrap, arm):
    cfg=ev.cfg; seed=shared_bootstrap['seed']; current=seed['index'] if seed else None
    spans=[]; traces=[]; changes=[]; phase_pending=None; bpm_pending=None
    def pending_update(old,j,i):
        same=old is not None and equivalent(ev.bank[old['anchor']],ev.bank[j],ev.start[i],ev.time[i],cfg)
        return {'anchor':old['anchor'] if same else j,'candidate':j,'count':old['count']+1 if same else 1,
                'started':old['started'] if same else float(ev.time[i])}
    for i,t in enumerate(ev.time):
        t=float(t); end=min(ev.duration,t+cfg['step']); reason='BEFORE_SEED' if seed else 'NO_SEED'
        status='UNKNOWN'; selected=None; drift=None; reset=None; groups=[]
        before=current
        if seed and t>=seed['time']:
            choices=ev.qualified(i); groups=ev.groups(i,choices)
            silent=bool(ev.obs['silent'][min(int(t*50),len(ev.obs['silent'])-1)]) if len(ev.obs['silent']) else False
            if silent:
                reason='STRICT_SOURCE_SILENCE'; reset='SILENCE'; phase_pending=bpm_pending=None
            elif t==seed['time']:
                selected=current; status='ACCEPTED'; reason='SHARED_SEED'
            elif arm=='C1_STATELESS':
                if not groups: reason='NO_OUTPUT_QUALIFIED_CLOCK'
                else:
                    candidate=groups[0][0]
                    if ev.margin(i,candidate,groups)+1e-12>=cfg['margin']:
                        selected=candidate; current=candidate; status='ACCEPTED'; reason='INDEPENDENT_BEST'
                    else: status='AMBIGUOUS'; reason='INDEPENDENT_MARGIN_TOO_SMALL'
            elif current in choices:
                selected=current; status='ACCEPTED'; reason='CURRENT_SUPPORTED'; reset='CURRENT_RECOVERED'
                phase_pending=bpm_pending=None
            else:
                reps=[g[0] for g in groups]
                strong=[j for j in reps if ev.G[i,j]>=cfg['change_G']-1e-12 and
                        ev.count[i,j]>=cfg['seed_count'] and
                        ev.S[i,j]-ev.S[i,current]>=cfg['margin']-1e-12 and
                        ev.margin(i,j,groups)>=cfg['margin']-1e-12]
                phases=[j for j in strong if abs(ev.bank[j]['bpm']-ev.bank[current]['bpm'])<=1e-8 and j!=current]
                if phases:
                    j=phases[0]; phase_pending=pending_update(phase_pending,j,i); bpm_pending=None
                    reason='PHASE_CONFIRMING'
                    if phase_pending['count']>=cfg['confirm_steps']:
                        current=j; selected=j; status='ACCEPTED'; reason='PHASE_REANCHOR'
                        phase_pending=None
                else:
                    phase_pending=None
                    j=None
                    if arm=='C2_CONTINUITY' and ev.G[i,current]<cfg['keep_G']:
                        for candidate in strong:
                            if ev.S[i,candidate]<cfg['seed_S']-1e-12 or harmonic(ev.bank[candidate],ev.bank[current],cfg):
                                continue
                            candidate_drift=ev.drift(i,current,candidate)
                            if candidate_drift['passed']:
                                j=candidate; drift=candidate_drift; break
                            if drift is None: drift=candidate_drift
                    if j is None:
                        reset='NO_QUALIFIED_CHANGE'; bpm_pending=None
                        reason='HOLD_WEAK' if arm=='C2_CONTINUITY' else 'HOLD_BPM_LOCKED'
                    else:
                        bpm_pending=pending_update(bpm_pending,j,i); reason='BPM_CONFIRMING'
                        if bpm_pending['count']>=cfg['confirm_steps']:
                            current=j; selected=j; status='ACCEPTED'; reason='BPM_CHANGE'; bpm_pending=None
            if reason in ('PHASE_REANCHOR','BPM_CHANGE'):
                changes.append({'time':t,'kind':reason,'before':ev.bank[before],'after':ev.bank[current]})
        for piece in _pieces(ev,t,end,status,ev.bank[selected] if selected is not None else None,reason):
            if spans and spans[-1]['end']==piece['start'] and all(spans[-1].get(k)==piece.get(k) for k in ('status','reason','key')):
                spans[-1]['end']=piece['end']
            else: spans.append(piece)
        traces.append({'t':t,'status':status,'reason':reason,'remembered':ev.detail(i,current,True) if seed and t>=seed['time'] else None,
                       'selected':ev.bank[selected]['key'] if selected is not None else None,
                       'top':[dict(ev.detail(i,g[0]),margin=ev.margin(i,g[0],groups),equivalent_keys=[ev.bank[j]['key'] for j in g]) for g in groups[:3]],
                       'phase_pending':phase_pending,'bpm_pending':bpm_pending,'pending_reset':reset,'drift':drift})
    accepted=[{k:v for k,v in s.items() if k not in ('status','reason')} for s in spans if s['status']=='ACCEPTED']
    # Adjacent accepted pieces with the same physical clock may be merged; gaps remain.
    merged=[]
    for s in accepted:
        if merged and merged[-1]['end']==s['start'] and all(merged[-1][k]==s[k] for k in ('bpm','phase','key')):
            merged[-1]['end']=s['end']
        else: merged.append(s)
    prediction={'status':shared_bootstrap['status'],'reason':shared_bootstrap.get('reason'),
                'accepted':merged,'ambiguous':[s for s in spans if s['status']=='AMBIGUOUS'],
                'spans':spans,'changes':changes,'bootstrap_hash':object_hash(shared_bootstrap),
                'full_tempo_map_returned':False,'meter_inference':False,'reference_fields_read':False,
                'actual_human_taps_collected':False,'offline_inference':True}
    return prediction,traces
