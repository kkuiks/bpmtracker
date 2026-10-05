"""Reference-free alternating latent-clock / bar-group / repeat reconstruction."""
import math
import json
import numpy as np
from .observations import initial_periods,pulse_family
from .latent_clock import search,time_at
from .continuous import fit
from .bar_structure import decode,score_path
from .repetition import links,messages,consistency
from .support import infer as infer_support


def objective(path,obs,meter,parameters,graph=()):
    assigned=path['assignments'];q=assigned[:,1];ix=assigned[:,0].astype(int)
    residual=(obs['events'][ix]-time_at(path['clock'],q))/.04
    loss=np.minimum(8.,np.log1p(residual**2)).sum()
    missing=max(0,len(obs['events'])-len(q))
    loss+=missing*parameters.get('clutter_cost',1.)
    loss+=max(0,len(path['clock'])-2)*parameters.get('tempo_change_cost',8.)
    bar_score=meter['base_score']
    repeat_cost=parameters.get('repeat_strength',.1)*consistency(path['clock'],meter['bars'],graph)
    return float(bar_score-loss-repeat_cost)


def map_payload(path,meter,obs,source):
    clock=path['clock'].copy();bars=meter['bars']
    end,support=infer_support(obs,clock)
    period0=(clock[1,1]-clock[0,1])/(clock[1,0]-clock[0,0])
    period1=(clock[-1,1]-clock[-2,1])/(clock[-1,0]-clock[-2,0])
    q0=clock[0,0]-clock[0,1]/period0
    q1=clock[-1,0]+(obs['duration']-clock[-1,1])/period1
    length=4*bars[0]['n']/bars[0]['d']
    start=bars[0]['q']+math.floor((q0-bars[0]['q'])/length)*length
    start=min(start,clock[0,0]);stop=max(q1,bars[-1]['q']+4*bars[-1]['n']/bars[-1]['d'])
    points=[]
    if start<clock[0,0]:points.append([start,float(time_at(clock,start))])
    points.extend(clock.tolist())
    if stop>clock[-1,0]:points.append([stop,float(time_at(clock,stop))])
    events=[]
    for bar in bars:
        signature=(bar['n'],bar['d'],tuple(bar['grouping']))
        if not events or signature!=(events[-1]['numerator'],events[-1]['denominator'],tuple(events[-1]['grouping'])):
            events.append(dict(pulse=bar['q'],numerator=bar['n'],denominator=bar['d'],grouping=bar['grouping'],bar_action='continue'))
    events[0]['pulse']=points[0][0]
    raw=dict(schema_version=1,source=source,clock_knots=[dict(pulse=float(q),source_seconds=float(t)) for q,t in points],
        quarters_per_pulse=dict(numerator=1,denominator=1),bar_anchor_pulse=bars[0]['q'],meter_events=events,
        support_seconds=[[0.,min(end,source['sample_frames']/source['sample_rate'])]],analysis_condition='unhinted',shared_origin_id=None)
    return raw,support


def analyze(obs,source,initial_bpm=None,*,parameters=None,repetition='none',known_links=None,beam=32,rounds=2,cache=None):
    parameters={} if parameters is None else parameters
    observation_identity=id(obs)
    physical_duration=source['sample_frames']/source['sample_rate']
    if abs(obs['duration']-physical_duration)>1/obs['fps']+1e-6:
        raise ValueError('source/frame duration mismatch')
    obs=dict(obs,duration=physical_duration)
    periods,anchor=initial_periods(obs);periods,guide=pulse_family(periods,anchor,initial_bpm)
    graph=links(obs) if repetition=='automatic' else known_links if repetition=='oracle' else []
    graph=[] if graph is None else graph
    cache={} if cache is None else cache
    binding=(source['sha256'],json.dumps(parameters,sort_keys=True),json.dumps(guide,sort_keys=True),beam,observation_identity)
    if cache.get('binding',binding)!=binding:raise ValueError('comparison cache binding mismatch')
    cache['binding']=binding
    candidates=[];history=[];decoded=cache.setdefault('decoded',{})
    def structure_for(clock,feedback=None):
        key=(clock.tobytes(),None if feedback is None else tuple(x.tobytes() for x in feedback))
        if key not in decoded:decoded[key]=decode(clock,obs,parameters,repeat_targets=feedback)
        return decoded[key]
    if 'initial_candidates' not in cache:
        for proposal in periods:
            paths=search(obs,proposal['period'],beam=beam,change_cost=parameters.get('tempo_change_cost',8.),max_paths=3)
            for path in paths:
                fitted,receipt=fit(path,obs,penalty=parameters.get('segmentation_penalty',.025))
                path=dict(path,clock=fitted)
                meter=structure_for(fitted)
                for alternative in [meter,*meter.get('alternatives',[])]:
                    candidates.append(dict(path=path,meter=alternative,score=objective(path,obs,alternative,parameters,graph),period=proposal['period']))
        cache['initial_candidates']=[dict(c) for c in candidates]
    else:
        candidates=[dict(c,score=objective(c['path'],obs,c['meter'],parameters,graph)) for c in cache['initial_candidates']]
    if not candidates:raise ValueError('no coherent hypotheses')
    candidates.sort(key=lambda c:c['score'],reverse=True)
    for iteration in range(rounds):
        next_candidates=list(candidates)
        for old in candidates[:2]:
            path,meter=old['path'],old['meter']
            q=np.array([b['q'] for b in meter['bars']]);t=time_at(path['clock'],q)
            # The new search can change musical coordinates AND change points;
            # bar feedback is part of that competition, not only final ranking.
            expanded=search(obs,old['period'],beam=beam,change_cost=parameters.get('tempo_change_cost',8.),bar_constraints=(q,t),max_paths=2)
            for new in [path,*expanded]:
                clock,receipt=fit(new,obs,meter['bars'],penalty=parameters.get('segmentation_penalty',.025))
                trial=dict(new,clock=clock)
                feedback=messages(clock,meter['bars'],graph)
                structure=structure_for(clock,feedback)
                score=objective(trial,obs,structure,parameters,graph)
                for alternative in [structure,*structure.get('alternatives',[])]:
                    alternative_score=objective(trial,obs,alternative,parameters,graph)
                    next_candidates.append(dict(path=trial,meter=alternative,score=alternative_score,period=old['period']))
        next_candidates.sort(key=lambda c:c['score'],reverse=True)
        history.append(dict(iteration=iteration,before=candidates[0]['score'],after=next_candidates[0]['score']))
        improvement=next_candidates[0]['score']-candidates[0]['score']
        candidates=next_candidates[:4]
        if improvement<=1e-8:break
    from experiments.analysis_legacy.music_map_contract import prepare_map,render_bars
    valid=[];failures=[]
    for candidate in candidates:
        try:
            raw,support=map_payload(candidate['path'],candidate['meter'],obs,source)
            raw['analysis_condition']='user_bpm_guided' if initial_bpm is not None else 'unhinted'
            if render_bars(prepare_map(raw))['status']!='rendered':raise ValueError('nonrenderable bar path')
        except (ValueError,KeyError) as exc:failures.append(str(exc));continue
        valid.append(dict(map=raw,source_only=True,reference_read=False,
            diagnostics=dict(score=candidate['score'],guide=guide,beam=beam,alternating_history=history,
                assigned_events=len(candidate['path']['assignments']),observed_events=len(obs['events']),
                latent_coordinates=candidate['path']['assignments'].tolist(),rhythmic_bars=candidate['meter']['bars'],
                support_states=support,repetition_mode=repetition,repetition_edges=graph,
                confidence_calibrated=False,invalid_candidates=failures)))
    if not valid:raise ValueError('no valid final map: '+str(failures))
    return valid[0],valid[1:]
