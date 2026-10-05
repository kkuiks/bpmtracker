"""Actual held-group excerpt-map checkpoint selection; full-song tests separate."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import numpy as np
import soundfile as sf
import torch
from .production_observations import inputs,predict_values
from .observations import prepare
from .analyzer import analyze
from experiments.tempo_meter_v3.probe_resources import digest


# These errors describe an ordinary inability to decode the supplied evidence.
# Contract violations, adapter bugs and malformed observations must still raise.
EXPECTED_DECODE_FAILURES=frozenset({
    'insufficient source events',
    'empty latent-coordinate beam',
    'no valid latent clock',
    'no coherent hypotheses',
    'no terminal bar paths',
})


def prepare_cases(rows,output,prefix_seconds=64.,include_change_excerpts=True):
    output.mkdir(parents=True,exist_ok=False);cases=[]
    for row in rows:
        duration=row['source']['sample_frames']/row['source']['sample_rate']
        spans=[('prefix',0.,min(prefix_seconds,duration))]
        original=json.loads(Path(row['reference_map']).read_text())['map']
        knots=original['clock_knots'];rates=[60*(b['pulse']-a['pulse'])/(b['source_seconds']-a['source_seconds']) for a,b in zip(knots,knots[1:])]
        changes=[knots[i+1]['source_seconds'] for i in range(len(rates)-1) if abs(rates[i+1]-rates[i])>1e-6 and 0<knots[i+1]['source_seconds']<duration]
        if include_change_excerpts and changes and changes[0]>=prefix_seconds:
            center=changes[0];lo=max(0.,center-prefix_seconds/2);hi=min(duration,lo+prefix_seconds)
            spans.append(('first-tempo-change',lo,hi))
        if row['id']=='walker_he-will-hold-me-fast':spans.append(('ending',duration-64.,duration))
        for label,lo,hi in spans:
            lo=float(np.floor(lo*50)/50)
            sr=row['source']['sample_rate'];first=round(lo*sr);last=round(hi*sr);lo=first/sr;hi=last/sr
            folder=output/(row['id']+'-'+label);folder.mkdir()
            signal,_=sf.read(row['audio'],start=first,stop=last,dtype='float32',always_2d=True)
            audio=folder/'source.wav';sf.write(audio,signal,sr,subtype='FLOAT')
            source=dict(sha256=digest(audio),sample_rate=sr,sample_frames=last-first)
            n=int(np.ceil((hi-lo)*50));indices=np.clip(np.round((lo+np.arange(n)/50)*50).astype(int),0,None)
            with np.load(row['features']) as z:
                arrays={key:z[key][np.minimum(indices,len(z[key])-1)].copy() for key in ['features','logits','energy']}
            cache=folder/'observations.npz';np.savez_compressed(cache,**arrays)
            reference=deepcopy(json.loads(Path(row['reference_map']).read_text())['map']);reference['source']=source
            for knot in reference['clock_knots']:knot['source_seconds']-=lo
            reference['support_seconds']=[[max(0,a-lo),min(hi-lo,b-lo)] for a,b in reference['support_seconds'] if min(hi,b)>max(lo,a)]
            refpath=folder/'reference.json';refpath.write_text(json.dumps(dict(map=reference),indent=2)+'\n')
            tails=[[max(0,a-lo),min(hi-lo,b-lo)] for a,b in row['no_grid'] if min(hi,b)>max(lo,a)]
            cases.append(dict(id=row['id']+'-'+label,parent_id=row['id'],group=row['group'],source=source,
                initial_bpm=row['initial_bpm'],observations=str(cache.resolve()),observations_sha256=digest(cache),
                reference=str(refpath.resolve()),reference_sha256=digest(refpath),no_grid=tails,
                unknown_outside_support=row['id']=='rwc_p002',parent_source_sha256=row['source']['sha256'],
                source_span_seconds=[lo,hi],acoustic_evidence='frozen whole-source observations sliced into source-relative excerpt; not re-encoded cropped audio'))
    (output/'manifest.json').write_text(json.dumps(dict(rows=cases,role='partial actual-map validation, not whole-song generalization'),indent=2)+'\n')
    return cases


def evaluate(checkpoint,cases,parameters,output):
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.tempo_meter_v3.evaluate_reviewed import score_extra
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters
    if parameters.get('downbeat_capacity',False):
        from .capacity_emissions import install
        install()
    selected_decoder=analyze
    if parameters.get('coordinate_refinement',False):
        from .coordinate_analyzer import install
        selected_decoder=install()
    package=torch.load(checkpoint,map_location='cpu',weights_only=False)
    if 'train_ids' not in package:raise ValueError('checkpoint training provenance unavailable')
    held_ids={r['parent_id'] for r in cases}
    if not package.get('tiny_fit',False) and held_ids&set(package['train_ids']):
        raise ValueError('held validation sources were used to fit this checkpoint')
    output.mkdir(parents=True,exist_ok=False)
    predictions=[];started=time.perf_counter()
    for row in cases:
        if digest(row['observations'])!=row['observations_sha256']:raise ValueError('validation observations changed')
        with np.load(row['observations']) as z:
            features=z['features'].copy();base=z['logits'].copy();energy=z['energy'].copy()
        x=inputs(features,base,energy);logits=predict_values(x,base,package)
        obs=prepare(logits[:,:2],energy,features=features)
        obs['quarter_probability_supervision']=True
        obs['acoustic_beat']=1/(1+np.exp(-np.clip(base[:,0],-30,30)))
        obs['grid_probability']=1/(1+np.exp(-np.clip(logits[:,2],-30,30)))
        try:
            pred,_=selected_decoder(obs,row['source'],row['initial_bpm'],parameters=parameters,repetition='none',beam=32)
        except ValueError as exc:
            if str(exc) not in EXPECTED_DECODE_FAILURES:raise
            pred=dict(status='decode_failed',error=str(exc),map=None,source_only=True,
                reference_read=False,observed_events=len(obs['events']),
                selection_contribution=0.,fallback_used=False)
        path=output/(row['id']+'-prediction.json');path.write_text(json.dumps(pred,indent=2)+'\n')
        predictions.append(dict(id=row['id'],prediction=str(path.resolve()),sha256=digest(path)))
        print('validation prediction',Path(checkpoint).parent.name,Path(checkpoint).name,row['id'],flush=True)
    # Freeze every source-only prediction before opening this checkpoint's maps.
    (output/'predictions.json').write_text(json.dumps(dict(complete=True,checkpoint_sha256=digest(checkpoint),prediction_stage_reference_read=False,rows=predictions),indent=2)+'\n')
    results=[]
    for row,pred in zip(cases,predictions):
        if digest(row['reference'])!=row['reference_sha256']:raise ValueError('validation reference changed')
        reference=prepare_map(json.loads(Path(row['reference']).read_text())['map']);prediction=json.loads(Path(pred['prediction']).read_text())
        tail=row['no_grid'][0] if row['no_grid'] else None
        oracle=score_extra(reference,dict(map=reference),tail,row['unknown_outside_support'])
        if not oracle['all_gates_pass']:raise ValueError('validation reference self-score failed '+row['id'])
        if prediction.get('status')=='decode_failed':
            result=dict(status='decode_failed',error=prediction['error'],
                scores={key:None for key in oracle['scores']},
                gates={key:False for key in oracle['gates']},all_gates_pass=False,
                map_metrics_computed=False)
            contribution=0.
        else:
            result=score_extra(reference,prediction,tail,row['unknown_outside_support'])
            contribution=float(np.mean(list(result['scores'].values())))
        results.append(dict(id=row['id'],parent_id=row['parent_id'],group=row['group'],
            score=result,selection_contribution=contribution))
    # Predeclared common map criterion: equal-source average of six fixed gates.
    # Includes true/false change F1 rather than rewarding a constant map alone.
    source_values={}
    for row in results:source_values.setdefault(row['parent_id'],[]).append(row['selection_contribution'])
    values=[float(np.mean(v)) for v in source_values.values()]
    record=dict(checkpoint=str(Path(checkpoint).resolve()),checkpoint_sha256=digest(checkpoint),
        map_selection_value=float(np.mean(values)),per_source_selection_values={k:float(np.mean(v)) for k,v in source_values.items()},rows=results,runtime_seconds=time.perf_counter()-started,
        role='actual held-group partial maps; not unseen or whole-song accuracy',frame_loss_used_for_selection=False,
        decode_failures=sum(row['score'].get('status')=='decode_failed' for row in results),
        failure_policy='Expected decode failure contributes zero to fixed equal-source selection; map metrics unavailable; no fallback')
    (output/'scores.json').write_text(json.dumps(record,indent=2)+'\n');return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--training',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'));torch.set_num_threads(1)
    manifest=json.loads(a.manifest.read_text());rows=[r for r in manifest['rows'] if r['split']=='validation']
    train=[r for r in manifest['rows'] if r['split']=='train']
    training=json.loads((a.training/'training.json').read_text())
    if not training['complete'] or training['tiny_fit']:raise ValueError('complete main-training run required')
    if training['manifest_sha256']!=digest(a.manifest):raise ValueError('training/validation manifest differs')
    if {r['group'] for r in train}&{r['group'] for r in rows}:raise ValueError('held group leakage')
    train_ids={r['id'] for r in train}
    for run in training['rows']:
        for checkpoint in run['checkpoints']:
            package=torch.load(checkpoint,map_location='cpu',weights_only=False)
            if package.get('tiny_fit',False) or set(package.get('train_ids',[]))!=train_ids:
                raise ValueError('checkpoint fitting rows differ from bound training manifest')
            if package['seed']!=run['seed']:raise ValueError('checkpoint seed binding differs')
    a.output.mkdir(parents=True,exist_ok=False);cases=prepare_cases(rows,a.output/'cases')
    params=json.loads(a.parameters.read_text())['selected']
    reports=[];seeds=[]
    for run in training['rows']:
        candidates=[]
        for checkpoint in sorted(run['checkpoints']):
            result=evaluate(checkpoint,cases,params,a.output/f"{run['seed']}-{Path(checkpoint).stem}")
            candidates.append(result);reports.append(result)
        chosen=max(candidates,key=lambda c:(c['map_selection_value'],-int(Path(c['checkpoint']).stem.split('-')[-1])))
        seeds.append(dict(seed=run['seed'],selected=chosen['checkpoint'],sha256=chosen['checkpoint_sha256'],map_selection_value=chosen['map_selection_value']))
    selected=max(seeds,key=lambda s:(s['map_selection_value'],-s['seed']))
    value=dict(complete=True,manifest_sha256=digest(a.manifest),parameters_sha256=digest(a.parameters),
        seed_results=seeds,selected=selected,checkpoint_comparisons=reports,
        decoder_and_targets_shared=True,criterion='equal-source mean of six unchanged strict scores; fixed prefixes, Walker ending and first material-tempo-change excerpt; expected decode failures contribute zero',
        validation_scope='Daybreak3 + Walker + RWC + State Shirt: six known held-from-weight-fit sources, eight excerpts; not full-song or unseen',
        later_full_comparison='Fourteen train and six held-group songs must be reported separately; selected seed is validation selected, not test selected')
    (a.output/'selection.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(seeds,indent=2),flush=True)


if __name__=='__main__':main()
