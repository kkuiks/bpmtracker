"""Joint bar-phase completion and tempo-preserving suffix selection.

All candidates retain the identical physical quarter clock and tempo events.
Only the global initial bar origin and trailing meter-only declarations vary.
Quarter/PCM terms and the shared initial prior are therefore cancelled instead
of allowing a nominal bar relabelling to change physical-clock evidence.
"""
import math,time
from source_scores import MapScorer,geometry,geometry_key
from experiments.continuous_beat_map_v1.map import validate

METHODS={'phase_completed_suffix':False,'phase_completed_suffix_mdl':True}

def candidates(prediction):
    initial=prediction['initial'];bpm=initial['bpm'];period=60./bpm
    length=initial['numerator']*4./initial['denominator']
    if abs(length-round(length))>1e-9:raise ValueError('Initial meter has a nonintegral quarter bar; unsupported phase completion')
    floor=max([0]+[i+1 for i,e in enumerate(prediction['events']) if 'bpm' in e])
    pool={}
    for n in range(floor,len(prediction['events'])+1):
        for rotation in range(round(length)):
            phase=(initial['bar_zero_source_seconds']+rotation*period)%(length*period)
            if phase>1e-8:phase-=length*period
            shift=round((initial['bar_zero_source_seconds']-phase)/period)
            if abs(initial['bar_zero_source_seconds']-phase-shift*period)>1e-7:raise ValueError('Rotation changed quarter phase')
            # Quarter labels move with the initial origin. Physical event
            # times/BPMs remain exact; meter resets retain their physical phase.
            events=[{**event,'quarter':event['quarter']+shift} for event in prediction['events'][:n]]
            value={'initial':{**initial,'bar_zero_source_seconds':phase},'events':events}
            key=geometry_key(value)
            if key in pool:continue
            native={**prediction,**value}
            # A quarter rotation can cross the old half-note beat lattice of
            # an initial x/2 section. Such a transition is outside the native
            # old-beat contract; reject that candidate, retaining the source.
            if not validate(native)['legal']:continue
            pool[key]={'candidate_index':len(pool),'geometry':value,'rotation_quarters':rotation,
                       'quarter_label_shift':shift,'retained_events':n}
    if not pool:raise ValueError('No legal bar-phase completion')
    return list(pool.values())

def refine_map(events,prediction):
    start=time.perf_counter();pool=candidates(prediction)
    scorer=MapScorer(events,{'units':[]});rows=[]
    for row in pool:
        result=scorer.score(row['geometry'],initial_family_prior=0.)
        part=result['components']['role']
        bar=sum(part[k] for k in ('bar','expected_bar','meter_prior','transition'))
        scores={'phase_completed_suffix':bar,'phase_completed_suffix_mdl':bar-result['boundary_code']}
        rows.append({**row,'scores':scores,'components':{k:part[k] for k in ('bar','expected_bar','meter_prior','transition')},
                     'boundary_code':result['boundary_code']})
    selections={}
    for method in METHODS:
        # Preserve the original rotation on exact score ties.
        best=max(rows,key=lambda r:(r['scores'][method],-r['retained_events'],-r['rotation_quarters']))
        selections[method]={'candidate_index':best['candidate_index'],'score':best['scores'][method]}
    return {'source_only':True,'reference_read':False,'quarter_clock_and_tempos_preserved':True,
            'duration_seconds':prediction['duration_seconds'],'candidates':rows,'selections':selections,
            'elapsed_seconds':time.perf_counter()-start}
