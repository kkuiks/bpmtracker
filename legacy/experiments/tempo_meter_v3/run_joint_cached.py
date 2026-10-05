"""Frozen-observation comparison: event reward, new ranking, joint refitting.

References are deliberately absent. Selection uses one coherent map, with a
fixed pulse family selected from the original bank by the permitted scalar.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import numpy as np
from .analyzer import declared_map
from .clock_search import select_pulse_level,initial_pulse_rate
from .meter_search import decode_meter as original_meter
from .meter_event import decode_meter
from .joint_clock import evaluate,refine,peaks
from .reconstruct_cached import load_observations,original_clock,musical_hash
from .probe_resources import digest

ARMS=('event','ranking','joint')
FILES=('run_joint_cached.py','joint_clock.py','meter_event.py','clock_search.py','meter_search.py','analyzer.py','reconstruct_cached.py')


def allowed_names(seeds,guide):
    _,decision=select_pulse_level(seeds,guide)
    if guide is None or decision.get('hint_conflict'):return {c['name'] for c in seeds},decision
    units=np.array([.25,1/3,.5,2/3,1.,1.5,2.,3.,4.,6.,8.])
    anchor=decision['anchor_bpm'];unit=decision['selected_pulse_multiplier']
    allowed={c['name'] for c in seeds if float(units[np.argmin(abs(np.log2(initial_pulse_rate(c)/anchor/units)))])==unit}
    return allowed,decision


def serialize(candidate,row,structure,logits,energy,decision,arm):
    from experiments.analysis_legacy.music_map_contract import prepare_map,render_bars
    duration=row['source']['sample_frames']/row['source']['sample_rate']
    raw,tail=declared_map(candidate,row['source'],duration,structure,logits,energy)
    raw['analysis_condition']='user_bpm_guided' if row.get('initial_bpm') is not None else 'unhinted'
    prepared=prepare_map(raw)
    if render_bars(prepared)['status']!='rendered':raise ValueError('invalid full bar map')
    return dict(map=raw,source_only=True,reference_read=False,
        diagnostics=dict(clock_family=candidate['name'],joint_score=float(candidate['score']),
                         clock_fit=dict(segments=len(candidate['clock'])-1),meter_search=candidate['meter']['diagnostics'],
                         tail=tail,initial_bpm=row.get('initial_bpm'),pulse_level_selection=decision,
                         intervention=arm,confidence_calibrated=False,
                         local_refitting=candidate.get('history',[])))


def infer(row,seeds,logits,energy,structure):
    """Callable on arbitrary bound source observations and automatic seeds."""
    observed=peaks(logits,structure);allowed,decision=allowed_names(seeds,row.get('initial_bpm'))
    decision={**decision,'anchor_and_membership_frozen_before_intervention':True}
    banks={arm:[] for arm in ARMS};replays=0
    for seed in seeds:
        clock=seed['clock']
        old=original_meter(clock,logits,structure)
        raw,_=declared_map(dict(clock=clock,meter=old),row['source'],row['source']['sample_frames']/row['source']['sample_rate'],structure,logits,energy)
        if musical_hash(raw)!=musical_hash(seed['original_prediction']['map']):raise ValueError('frozen candidate replay differs')
        replays+=1
        current=evaluate(clock,logits,structure,observed)
        current['name']=seed['name']
        event=dict(current,score=seed['joint_score']+.35*(current['meter']['score']-old['score']))
        banks['event'].append(event);banks['ranking'].append(current)
    banks['joint']=list(banks['ranking'])
    # Bound computation with three source-ranked seeds, never reference scores.
    shortlist=sorted([c for c in banks['ranking'] if c['name'] in allowed],key=lambda c:c['score'],reverse=True)[:3]
    trials=[]
    for candidate in shortlist:
        revised=refine(candidate['clock'],logits,structure,observed)
        revised['name']=candidate['name']
        if any(h['accepted'] for h in revised['history']):banks['joint'].append(revised)
        trials.append(dict(name=candidate['name'],history=revised['history'],final_score=revised['score']))
    results={};all_candidates={}
    for arm,bank in banks.items():
        ordered=sorted(bank,key=lambda c:(c['name'] in allowed,c['score']),reverse=True)
        valid=[];invalid=[]
        for c in ordered:
            try:pred=serialize(c,row,structure,logits,energy,decision,arm)
            except (ValueError,TypeError,KeyError) as exc:
                invalid.append(dict(name=c['name'],error=str(exc)));continue
            valid.append(dict(name=c['name'],score=c['score'],prediction=pred))
        if not valid:raise ValueError('no valid candidate')
        results[arm]=dict(selected=valid[0]['prediction'],invalid=invalid,
                         selected_seed=valid[0]['name'],guide_invariance={})
        for offset in (-1,1):
            guide=row.get('initial_bpm')
            if guide is None:continue
            other,_=allowed_names(seeds,guide+offset)
            ordered_valid=sorted(valid,key=lambda c:(c['name'] in other,c['score']),reverse=True)
            results[arm]['guide_invariance'][str(offset)]=musical_hash(ordered_valid[0]['prediction']['map'])==musical_hash(valid[0]['prediction']['map'])
        all_candidates[arm]=valid
    return results,all_candidates,dict(legacy_replays=replays,joint_trials=trials,
                                       event_counts={k:len(v) for k,v in observed.items()})


def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    source_path=a.baseline/'predictions/manifest.json';source=json.loads(source_path.read_text())
    assert source['complete'] and source['references_available_to_runner'] is False
    a.output.mkdir(parents=True,exist_ok=False)
    manifests={arm:dict(complete=False,references_available_to_runner=False,
        baseline_manifest_sha256=digest(source_path),input_sha256=source['input_sha256'],
        implementation_sha256={n:digest(Path(__file__).with_name(n)) for n in FILES},rows=[]) for arm in ARMS}
    for arm in ARMS:(a.output/arm).mkdir()
    for index,row in enumerate(source['rows']):
        started=time.perf_counter()
        if digest(row['audio'])!=row['source']['sha256']:raise ValueError('audio binding changed')
        bank_path=Path(row['selected']['path']).parent/'candidate-bank.json'
        stored=json.loads(bank_path.read_text())
        seeds=[dict(name=c['name'],clock=original_clock(c),joint_score=c['score'],original_prediction=c['prediction']) for c in stored]
        logits,energy,structure=load_observations(row)
        results,banks,receipt=infer(row,seeds,logits,energy,structure)
        for arm in ARMS:
            folder=a.output/arm/f'{index:02d}';folder.mkdir()
            path=folder/'selected.json';path.write_text(json.dumps(results[arm]['selected'],indent=2,allow_nan=False)+'\n')
            (folder/'candidates.json').write_text(json.dumps(banks[arm],indent=2,allow_nan=False)+'\n')
            (folder/'diagnostics.json').write_text(json.dumps(dict(**receipt,invalid=results[arm]['invalid'],guide_invariance=results[arm]['guide_invariance']),indent=2)+'\n')
            record={k:row[k] for k in ('id','title','audio','source','initial_bpm','initial_bpm_source','model_sha256','acoustic_checkpoint_sha256','feature_binding')}
            record.update(selected=dict(path=str(path.resolve()),sha256=digest(path)),references_available_to_runner=False,
                          guide_invariance=results[arm]['guide_invariance'],original_bank_sha256=digest(bank_path),
                          runtime_seconds=time.perf_counter()-started,runtime_scope='shared comparison CPU time, not additive across arms',legacy_candidates_reproduced=receipt['legacy_replays'])
            manifests[arm]['rows'].append(record)
            (a.output/arm/'manifest.json').write_text(json.dumps(manifests[arm],indent=2)+'\n')
        print(row['id'],round(time.perf_counter()-started,2),{k:v['selected_seed'] for k,v in results.items()},flush=True)
    for arm in ARMS:
        manifests[arm]['complete']=True
        (a.output/arm/'manifest.json').write_text(json.dumps(manifests[arm],indent=2)+'\n')


if __name__=='__main__':main()
