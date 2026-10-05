"""Execution-only parallel wrapper around the frozen held-map validation.

Case preparation, prediction, scoring, source averaging and tie rules are those
of validate_production. Parallel scheduling never participates in selection.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from contextlib import redirect_stdout,redirect_stderr
import json
import multiprocessing
import os
from pathlib import Path
import sys
import torch
from .validate_production import prepare_cases,evaluate
from experiments.tempo_meter_v3.probe_resources import digest


def job(checkpoint,cases,parameters,output):
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'));torch.set_num_threads(1)
    with Path(str(output)+'.log').open('w') as stream,redirect_stdout(stream),redirect_stderr(stream):
        return evaluate(checkpoint,cases,parameters,Path(output))


def select(training,reports):
    """Preserve the frozen per-seed step tie, followed by the seed tie."""
    seeds=[]
    for run in training['rows']:
        candidates=[reports[str(Path(p).resolve())] for p in sorted(run['checkpoints'])]
        chosen=max(candidates,key=lambda c:(c['map_selection_value'],-int(Path(c['checkpoint']).stem.split('-')[-1])))
        seeds.append(dict(seed=run['seed'],selected=chosen['checkpoint'],sha256=chosen['checkpoint_sha256'],map_selection_value=chosen['map_selection_value']))
    return seeds,max(seeds,key=lambda s:(s['map_selection_value'],-s['seed']))


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True);p.add_argument('--parameters',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=3)
    p.add_argument('--resume',action='store_true');a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'));torch.set_num_threads(1)
    manifest=json.loads(a.manifest.read_text());rows=[r for r in manifest['rows'] if r['split']=='validation']
    train=[r for r in manifest['rows'] if r['split']=='train'];training_path=a.training/'training.json'
    training=json.loads(training_path.read_text())
    if not training['complete'] or training['tiny_fit']:raise ValueError('complete main-training run required')
    if training['manifest_sha256']!=digest(a.manifest):raise ValueError('training/validation manifest differs')
    if {r['group'] for r in train}&{r['group'] for r in rows}:raise ValueError('held group leakage')
    train_ids={r['id'] for r in train};jobs=[];checkpoint_bindings={}
    for run in training['rows']:
        for checkpoint in sorted(run['checkpoints']):
            package=torch.load(checkpoint,map_location='cpu',weights_only=False)
            if package.get('tiny_fit',False) or set(package.get('train_ids',[]))!=train_ids:
                raise ValueError('checkpoint fitting rows differ from bound training manifest')
            if package['seed']!=run['seed']:raise ValueError('checkpoint seed binding differs')
            checkpoint=str(Path(checkpoint).resolve());checkpoint_bindings[checkpoint]=digest(checkpoint)
            jobs.append((run['seed'],checkpoint))
    parameters=json.loads(a.parameters.read_text())['selected']
    names=['validate_parallel.py','validate_production.py','production_observations.py','observations.py','analyzer.py']
    if parameters.get('downbeat_capacity',False):names+=['capacity_emissions.py','capacity_support.py','capacity_fit.py','capacity_objective.py','capacity_vocabulary.py','learned_support.py','fast_structure.py']
    if parameters.get('coordinate_refinement',False):names+=['coordinate_analyzer.py']
    bindings=dict(manifest_sha256=digest(a.manifest),training_sha256=digest(training_path),parameters_sha256=digest(a.parameters),
        implementation_sha256={n:digest(Path(__file__).with_name(n)) for n in names},checkpoint_sha256=checkpoint_bindings,
        workers=a.workers,execution_only=True,decoder_and_scoring_changed=False)
    a.output.mkdir(parents=True,exist_ok=a.resume);execution=a.output/'execution.json'
    if execution.exists():
        previous=json.loads(execution.read_text())
        if previous['bindings']!=bindings:raise ValueError('parallel validation resume binding differs')
        cases_path=a.output/'cases/manifest.json'
        if digest(cases_path)!=previous['cases_manifest_sha256']:raise ValueError('validation cases changed')
        cases=json.loads(cases_path.read_text())['rows']
    else:
        cases=prepare_cases(rows,a.output/'cases');cases_path=a.output/'cases/manifest.json'
        execution.write_text(json.dumps(dict(bindings=bindings,cases_manifest_sha256=digest(cases_path)),indent=2)+'\n')
    for case in cases:
        if digest(case['observations'])!=case['observations_sha256'] or digest(case['reference'])!=case['reference_sha256']:
            raise ValueError('bound validation case changed')
    reports={};pending=[]
    for seed,checkpoint in jobs:
        output=a.output/f'{seed}-{Path(checkpoint).stem}'
        attempts=sorted(a.output.glob(f'{seed}-{Path(checkpoint).stem}-attempt-*'),key=lambda path:int(path.name.rsplit('-',1)[-1]))
        completed=next((path for path in [output,*attempts] if (path/'scores.json').exists()),None)
        if completed is not None:
            record=json.loads((completed/'scores.json').read_text())
            if record['checkpoint_sha256']!=checkpoint_bindings[checkpoint]:raise ValueError('completed checkpoint binding differs')
            for row in json.loads((completed/'predictions.json').read_text())['rows']:
                if digest(row['prediction'])!=row['sha256']:raise ValueError('completed validation prediction changed')
            reports[checkpoint]=record
        else:
            attempt=1
            while output.exists():
                attempt+=1;output=a.output/f'{seed}-{Path(checkpoint).stem}-attempt-{attempt}'
            pending.append((checkpoint,output))
    def progress():
        record=dict(complete=len(reports)==len(jobs),expected_checkpoint_jobs=len(jobs),completed_checkpoint_jobs=len(reports),
            completed=[dict(checkpoint=p,sha256=checkpoint_bindings[p],map_selection_value=r['map_selection_value']) for p,r in reports.items()])
        destination=a.output/'progress.json';temp=destination.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');os.replace(temp,destination)
    progress()
    # Fresh spawned processes isolate adapter state and release each job's caches.
    with ProcessPoolExecutor(max_workers=a.workers,mp_context=multiprocessing.get_context('spawn'),max_tasks_per_child=1) as executor:
        futures={executor.submit(job,checkpoint,cases,parameters,output):checkpoint for checkpoint,output in pending}
        for future in as_completed(futures):
            checkpoint=futures[future];reports[checkpoint]=future.result();progress()
            print('validation checkpoint complete',checkpoint,len(reports),'/',len(jobs),flush=True)
    seeds,selected=select(training,reports)
    ordered=[reports[str(Path(checkpoint).resolve())] for run in training['rows'] for checkpoint in sorted(run['checkpoints'])]
    value=dict(complete=True,manifest_sha256=digest(a.manifest),parameters_sha256=digest(a.parameters),
        seed_results=seeds,selected=selected,checkpoint_comparisons=ordered,
        decoder_and_targets_shared=True,criterion='equal-source mean of six unchanged strict scores; fixed prefixes, Walker ending and first material-tempo-change excerpt; expected decode failures contribute zero',
        validation_scope='Daybreak3 + Walker + RWC + State Shirt: six known held-from-weight-fit sources, eight excerpts; not full-song or unseen',
        later_full_comparison='Fourteen train and six held-group songs must be reported separately; selected seed is validation selected, not test selected',
        execution_wrapper=dict(module='experiments.tempo_meter_v4.validate_parallel',sha256=digest(Path(__file__)),workers=a.workers,
            reused_functions='validate_production.prepare_cases and evaluate; selection and weighting unchanged'))
    (a.output/'selection.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(seeds,indent=2),flush=True)


if __name__=='__main__':main()
