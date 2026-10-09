"""Separate source worker: candidate preparation, calibration proposals, frozen predictions."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import itertools
from pathlib import Path
import time
import numpy as np
from tools.project_storage import ROOT
from experiments.metronome_reconstruction_v1.infer import make_evidence,broad_candidates
from . import core
from .candidates import prepare,local_phases,pool
from .io import read,write,source_array,validate_source


def assisted(prediction,obs,cfg,initial,policy):
    accepted,ambiguity,scope=core.decision(prediction['episodes'],obs,cfg,initial,policy,prediction.get('initial_anchor_episodes'))
    return dict(prediction,accepted=accepted,ambiguous=ambiguity,initial_information_policy=policy,
                initial_information_scope=scope,initial_information_is_assumed_not_measured=initial is not None)


def prepare_one(argument):
    row,run=argument;run=Path(run);validate_source(row);start=time.perf_counter()
    dest=run/'candidate-banks'/f"{row['id']}.json"
    if dest.exists(): return dict(id=row['id'],cached=True,seconds=0)
    try:
        result=prepare(row,source_array(row['evidence_path']),run,read(ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json'))
        result['status']='prepared';write(dest,result)
        status='prepared'
    except Exception as exc:
        result=dict(status='failed',error=f'{type(exc).__name__}: {exc}',pools={},statistics={});write(dest,result);status='failed'
    return dict(id=row['id'],status=status,seconds=time.perf_counter()-start,
                pool_counts={k:len(v) for k,v in result['pools'].items()})


def features(data,hypotheses,cfg):
    obs=core.observation(data)
    return obs,[f for h in hypotheses if (f:=core.clock_features(obs,h,cfg)) is not None]


def controls_null(run):
    old_config=read(ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json');rows=[]
    for seed in range(12):
        rng=np.random.default_rng(9400+seed); duration=(60,120,300)[seed%3];n=round(duration*50)
        times=[]; t=.137
        while t<duration:
            period=60/rng.choice((65,90,110,135,160,195))
            for j in range(int(rng.integers(3,8))):
                t+=period+rng.normal(0,.01);times.append(t)
            t+=rng.uniform(.0,.35)
        logits=np.full(n,-12.);p=np.minimum(n-1,np.rint(np.array(times)*50).astype(int));logits[p]=rng.uniform(1,5,len(p))
        down=np.full(n,-12.)
        data=dict(beat_logits=logits,downbeat_logits=down,fps=np.array(50),duration_seconds=np.array(duration))
        obs=core.observation(data);evidence=make_evidence(logits,down,duration,old_config)
        rates=[float(r) for r in broad_candidates(evidence,old_config)[0]]
        hs,stats=pool(local_phases(obs,rates,evidence,old_config))
        ident=f'null{seed:02d}';path=run/'null-evidence'/f'{ident}.npz';path.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(path,**data);write(run/'null-banks'/f'{ident}.json',dict(hypotheses=hs,statistics=stats))
        rows.append(dict(id=ident,evidence_path=str(path),duration_seconds=duration))
    write(run/'null-source-inputs.json',dict(samples=rows,meaning='No persistent declared clock; structured transient coincidences',
          non_silent_coherent_placebo_cannot_be_rejected_from_logits_alone=True))


def calibration_one(argument):
    row,run,configs,initial=argument;run=Path(run);start=time.perf_counter();validate_source(row)
    bank=read(run/'candidate-banks'/f"{row['id']}.json");data=source_array(row['evidence_path'])
    for epsilon in sorted({cfg['epsilon'] for cfg in configs.values()}):
        obs,fs=features(data,bank.get('pools',{}).get('broad_phase',[]),dict(core.DEFAULT,epsilon=epsilon))
        for name,values in configs.items():
            if values['epsilon']!=epsilon:continue
            cfg={**core.DEFAULT,**values}
            result=core.support_prediction(obs,fs,cfg)
            for policy in ('none','initial_unit','initial_exact'):
                pred=result if policy=='none' else assisted(result,obs,cfg,initial,policy)
                write(run/'calibration-predictions'/name/policy/f"{row['id']}.json",pred)
    return dict(id=row['id'],seconds=time.perf_counter()-start,configs=len(configs))


def frozen_one(argument):
    row,run,config,initial=argument;run=Path(run);start=time.perf_counter();validate_source(row)
    bank=read(run/'candidate-banks'/f"{row['id']}.json");data=source_array(row['evidence_path']);obs=core.observation(data)
    obsfeatures={};base=None;completed=[]
    for condition,pool_name,global_mode,refinement in [
        ('A_GLOBAL_MATCHED','final',True,None),('A_INTERVAL_FIXED','final',False,None),
        ('A_RETAINED','retained',False,None),('A_BROAD_PHASE','broad_phase',False,None),
        ('A_PHASOR','phasor',False,None),('A_PHASE_REFIT','final',False,'phase'),('A_RATE_PHASE_REFIT','final',False,'rate_phase'),
        ('A_GLOBAL_MATCHED_128','final',True,None),('A_INTERVAL_FIXED_128','final',False,None),
        ('A_INTERVAL_NO_PERIOD_GUARD','final',False,None)]:
        hs=bank.get('pools',{}).get(pool_name,[])
        if condition.endswith('_128'): hs=hs[:128]
        cache_key=(pool_name,len(hs))
        if cache_key not in obsfeatures: obsfeatures[cache_key]=[f for h in hs if (f:=core.clock_features(obs,h,config)) is not None]
        condition_config=dict(config,period_guard=False) if condition=='A_INTERVAL_NO_PERIOD_GUARD' else config
        result=core.support_prediction(obs,obsfeatures[cache_key],condition_config,global_mode,refinement)
        result.update(condition=condition,candidate_statistics=bank.get('statistics',{}).get(pool_name,{}),candidate_preparation_status=bank['status'])
        for policy in ('none','initial_unit','initial_exact'):
            pred=result if policy=='none' else assisted(result,obs,condition_config,initial,policy)
            write(run/'frozen-predictions'/condition/policy/f"{row['id']}.json",pred)
        completed.append(condition)
    original=bank.get('original',{})
    eps=[]
    if original.get('quarter_bpm'):
        p=original['period_seconds'];meter=original['time_signature']['numerator'];bar=original['offset_seconds']%(meter*p)
        eps=[dict(start=0.,end=obs['duration'],bpm=original['quarter_bpm'],period=p,phase=bar%p,bar_phase=bar,
                  bar_period=meter*p,bar_status='SUPPORTED',rank=original['score'],quality=original['score'],
                  integral_score=original['score']*obs['duration'],provenance='unchanged_Original')]
    write(run/'frozen-predictions/O_FROZEN/none'/f"{row['id']}.json",dict(status=original.get('status','missing'),accepted=eps,episodes=eps,
          ambiguous=[],initial_information_policy='none',initial_information_scope=None,reference_fields_read=False,
          original_time_signature=original.get('time_signature'),full_tempo_map_returned=False))
    return dict(id=row['id'],seconds=time.perf_counter()-start,conditions=completed,policies=3,status=bank['status'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--stage',choices=['prepare','calibration','frozen'],required=True);p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    if not read(a.run/'controls-v1.json')['mandatory_passed']:raise ValueError('Logical controls not passed')
    rows=read(a.run/'source-inputs.json')['samples'];protocol=read(a.run/'protocol.json')
    for row in rows:validate_source(row)
    initial={r['id']:{k:v for k,v in r.items() if k!='id'} for r in read(a.run/'assumed-initial-inputs.json')['rows']}
    if a.stage=='prepare':
        jobs=[(row,str(a.run)) for row in rows];function=prepare_one
    elif a.stage=='calibration':
        # Twelve predeclared configurations, below the approved maximum24.
        if not (a.run/'null-source-inputs.json').exists():controls_null(a.run)
        configs={f'e{int(epsilon*1000)}-q{int(threshold*100)}-n{minimum}':dict(epsilon=epsilon,quality_threshold=threshold,minimum_quarters=minimum,margin=.05,minimum_score=.5)
                 for epsilon,threshold,minimum in itertools.product((.02,.04),(.55,.70,.85),(4,8))}
        # Empirical full-scan null maxima include source-derived phase search and512-clock caps.
        null_maxima={name:[] for name in configs}
        for row in read(a.run/'null-source-inputs.json')['samples']:
            data=source_array(row['evidence_path']);hs=read(a.run/'null-banks'/f"{row['id']}.json")['hypotheses']
            for epsilon in (.02,.04):
                obs,fs=features(data,hs,dict(core.DEFAULT,epsilon=epsilon))
                for name,values in configs.items():
                    if values['epsilon']!=epsilon:continue
                    prediction=core.support_prediction(obs,fs,{**core.DEFAULT,**values})
                    null_maxima[name].append(max((e['integral_score'] for e in prediction['episodes']),default=0.))
        for name in configs:
            configs[name]['minimum_score']=max(.5,float(np.quantile(null_maxima[name],.95)))
        write(a.run/'calibration-configurations.json',configs)
        write(a.run/'whole-search-null-calibration.json',dict(maxima=null_maxima,minimum_score_rule='max(.5, empirical95th full-scan maximum)',
              not_formal_probability_or_error_guarantee=True,null_inputs=12))
        calibration=set(protocol['calibration_ids']);jobs=[(row,str(a.run),configs,initial.get(row['id'])) for row in rows if row['id'] in calibration];function=calibration_one
    else:
        from .review import check_freeze
        check_freeze(a.run)
        config={**core.DEFAULT,**read(a.run/'selected-config.json')['configuration']}
        jobs=[(row,str(a.run),config,initial.get(row['id'])) for row in rows];function=frozen_one
    receipts=[];failures=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool_exec:
        futures={pool_exec.submit(function,job):job[0]['id'] for job in jobs}
        for future in as_completed(futures):
            ident=futures[future]
            try: result=future.result();receipts.append(result);print(a.stage,len(receipts),'/',len(jobs),json_print(result),flush=True)
            except Exception as exc:
                result=dict(id=ident,status='exception',error=f'{type(exc).__name__}: {exc}');receipts.append(result);failures.append(result);print(a.stage,'ERROR',json_print(result),flush=True)
            write(a.run/f'{a.stage}-receipt.json',dict(completed=False,expected_sources=len(jobs),rows=receipts,exceptions=failures,reference_files_read=False))
    write(a.run/f'{a.stage}-receipt.json',dict(completed=len(receipts)==len(jobs),expected_sources=len(jobs),rows=receipts,exceptions=failures,reference_files_read=False))
    if failures:raise SystemExit(1)


def json_print(value):
    import json
    return json.dumps(value,ensure_ascii=False)


if __name__=='__main__':main()
