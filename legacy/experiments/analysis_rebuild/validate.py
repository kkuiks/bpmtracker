"""Compare new checkpoints on exactly the preserved actual held excerpts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch

from services.analysis.observer import predict
from services.analysis.prediction import analyse


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(checkpoint, cases, output, *, event_policy='learned'):
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.tempo_meter_v3.evaluate_reviewed import score_extra
    package=torch.load(checkpoint,map_location='cpu',weights_only=False)
    if package['tiny'] or {r['parent_id'] for r in cases}&set(package['train_ids']):raise ValueError('held-source fitting leakage')
    output.mkdir(parents=True,exist_ok=False);predictions=[];tick=time.perf_counter()
    for row in cases:
        if digest(row['observations'])!=row['observations_sha256']:raise ValueError('held observations changed')
        with np.load(row['observations']) as z:f,b,e=z['features'].copy(),z['logits'].copy(),z['energy'].copy()
        fields=predict(f,b,e,package,event_policy=event_policy)
        pred=analyse(fields,row['source'])
        path=output/(row['id']+'-prediction.json');path.write_text(json.dumps(pred,indent=2,allow_nan=False)+'\n')
        predictions.append(dict(id=row['id'],path=str(path.resolve()),sha256=digest(path)))
    (output/'predictions.json').write_text(json.dumps(dict(complete=True,checkpoint_sha256=digest(checkpoint),event_policy=event_policy,references_read_by_predictor=False,rows=predictions),indent=2)+'\n')
    scores=[]
    for row,pred in zip(cases,predictions):
        if digest(row['reference'])!=row['reference_sha256']:raise ValueError('held reference changed')
        reference=prepare_map(json.loads(Path(row['reference']).read_text())['map']);prediction=json.loads(Path(pred['path']).read_text())
        tail=row['no_grid'][0] if row['no_grid'] else None
        oracle=score_extra(reference,dict(map=reference),tail,row['unknown_outside_support'])
        if not oracle['all_gates_pass']:raise ValueError('held reference self-score failed')
        if prediction.get('status')=='decode_failed':
            score=dict(status='decode_failed',scores=dict.fromkeys(oracle['scores'],None),gates=dict.fromkeys(oracle['gates'],False),all_gates_pass=False);value=0.
        else:score=score_extra(reference,prediction,tail,row['unknown_outside_support']);value=float(np.mean(list(score['scores'].values())))
        scores.append(dict(id=row['id'],parent_id=row['parent_id'],score=score,selection_contribution=value))
    grouped={}
    for row in scores:grouped.setdefault(row['parent_id'],[]).append(row['selection_contribution'])
    result=dict(checkpoint=str(checkpoint.resolve()),checkpoint_sha256=digest(checkpoint),map_selection_value=float(np.mean([np.mean(v) for v in grouped.values()])),per_source_selection_values={k:float(np.mean(v)) for k,v in grouped.items()},rows=scores,runtime_seconds=time.perf_counter()-tick,passing_excerpts=sum(r['score']['all_gates_pass'] for r in scores),failure_count=sum(r['score'].get('status')=='decode_failed' for r in scores),criterion='Same six strict scores, equal source weighting, failures zero; no frame-loss selection',scope='Known held-from-fit partial maps; not unseen or full-song success')
    result['event_policy']=event_policy
    (output/'scores.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,required=True);p.add_argument('--training-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--event-policy',choices=('learned','frozen'),default='learned')
    a=p.parse_args();sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'));torch.set_num_threads(1);a.output.mkdir(parents=True,exist_ok=False)
    cases=json.loads(a.cases.read_text())['rows'];results=[];seeds=[]
    for training_path in sorted(a.training_root.glob('*/training.json')):
        training=json.loads(training_path.read_text());assert training['complete'] and not training['tiny'];reports=[]
        for checkpoint in training['checkpoints']:
            path=Path(checkpoint['path']);assert digest(path)==checkpoint['sha256']
            result=evaluate(path,cases,a.output/(str(training['seed'])+'-'+path.stem),event_policy=a.event_policy);results.append(result);reports.append(result)
            print(training['seed'],checkpoint['step'],result['map_selection_value'],result['passing_excerpts'],flush=True)
        best=max(reports,key=lambda r:(r['map_selection_value'],-int(Path(r['checkpoint']).stem.split('-')[-1])))
        seeds.append(dict(seed=training['seed'],selected=best['checkpoint'],sha256=best['checkpoint_sha256'],map_selection_value=best['map_selection_value']))
    if not seeds:raise ValueError('no complete training runs')
    selected=max(seeds,key=lambda r:(r['map_selection_value'],-r['seed']))
    record=dict(complete=True,cases_sha256=digest(a.cases),seed_results=seeds,selected=selected,checkpoint_comparisons=results,criterion='Predeclared strict equal-source map mean; earlier checkpoint/lower seed resolve ties',whole_source_scores_used_for_selection=False)
    record['event_policy']=a.event_policy
    (a.output/'selection.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(selected,indent=2))


if __name__=='__main__':main()
