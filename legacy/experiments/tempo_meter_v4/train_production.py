"""Three-seed actual-map observation fit; checkpoint selection happens on maps."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from .production_observations import ObservationModel,CONFIG,inputs
from .observations import local_peaks,refined_times,sigmoid
from experiments.tempo_meter_v3.probe_resources import digest

POSITIVE_WEIGHTS=[2.,8.,1.]


def load(row):
    if digest(row['features'])!=row['feature_sha256'] or digest(row['targets'])!=row['targets_sha256']:raise ValueError('learning data changed')
    with np.load(row['features']) as z:
        base=z['logits'].copy();x=inputs(z['features'],base,z['energy'])
    with np.load(row['targets']) as z:y=z['y'].copy();mask=z['mask'].copy()
    return x,base,y,mask


def fit(rows,seed,steps,output,*,tiny=False):
    torch.set_num_threads(1);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
    generator=np.random.default_rng(seed);data={r['id']:load(r) for r in rows}
    if tiny:data={k:tuple(v[:2400] for v in item) for k,item in data.items()}
    means=np.concatenate([x[::10] for x,_,_,_ in data.values()])
    mean=means.mean(0);std=np.maximum(means.std(0),.1)
    model=ObservationModel().cuda();optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    output.mkdir(parents=True,exist_ok=False);started=time.perf_counter();history=[]
    def batch(step):
        examples=[]
        for _ in range(2):
            pool=[r for r in rows if r.get('no_grid')] if not tiny and step%5==0 and _==1 else rows
            row=pool[int(generator.integers(len(pool)))];x,base,y,mask=data[row['id']]
            start=int(generator.integers(max(1,len(x)-2048+1)))
            if pool is not rows:
                negatives=np.flatnonzero((y[:,2]==0)&(mask>0))
                if len(negatives):start=int(np.clip(negatives[0]-1024+generator.integers(-256,257),0,max(0,len(x)-2048)))
            end=min(len(x),start+2048)
            examples.append(((x[start:end]-mean)/std,base[start:end],y[start:end],mask[start:end]))
        return [torch.from_numpy(np.stack(item)).cuda() for item in zip(*examples)]
    for step in range(1,steps+1):
        model.train();x,base,y,mask=batch(step);optimizer.zero_grad(set_to_none=True)
        value=F.binary_cross_entropy_with_logits(model(x,base),y,reduction='none',pos_weight=torch.tensor(POSITIVE_WEIGHTS,device=x.device))
        channel_weights=torch.tensor([1.,1.,.2],device=x.device)
        loss=(value*mask[:,:,None]*channel_weights).sum()/(2.2*mask.sum()).clamp(min=1)
        if not torch.isfinite(loss):raise ValueError('nonfinite loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5.);optimizer.step()
        if step%100==0 or step==steps:
            record=dict(step=step,train_loss=float(loss.detach()),elapsed_seconds=time.perf_counter()-started)
            history.append(record);print(seed,record,flush=True)
            (output/'history.json').write_text(json.dumps(history,indent=2)+'\n')
        if step in {steps//4,steps}:
            package=dict(state_dict=model.state_dict(),mean=mean.tolist(),std=std.tolist(),config=CONFIG,
                step=step,seed=seed,positive_weights=POSITIVE_WEIGHTS,train_ids=[r['id'] for r in rows],
                selection='not selected by frame loss; pending held-group actual-map validation',tiny_fit=tiny)
            torch.save(package,output/f'step-{step}.pt')
    del model;torch.cuda.empty_cache()
    return dict(seed=seed,steps=steps,elapsed_seconds=time.perf_counter()-started,checkpoints=[str(p.resolve()) for p in output.glob('step-*.pt')])


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--steps',type=int,default=800);p.add_argument('--tiny',action='store_true');a=p.parse_args()
    manifest=json.loads(a.manifest.read_text());train=[r for r in manifest['rows'] if r['split']=='train']
    validation=[r for r in manifest['rows'] if r['split']=='validation']
    if {r['group'] for r in train}&{r['group'] for r in validation}:raise ValueError('group leakage')
    a.output.mkdir(parents=True,exist_ok=False)
    if a.tiny:
        chosen=['ntm_archspire_liminal-cypher','forrester-savell-karnivool'];train=[r for r in train if r['id'] in chosen]
        if len(train)!=2:raise ValueError('tiny diagnostic rows unavailable')
    results=[]
    for seed in ([20261001] if a.tiny else [20261001,20261002,20261003]):
        results.append(fit(train,seed,a.steps,a.output/str(seed),tiny=a.tiny))
    value=dict(complete=True,rows=results,manifest_sha256=digest(a.manifest),tiny_fit=a.tiny,
        known_development_material=True,unseen_generalization_claim=False,
        frame_loss_checkpoint_selection=False,decoder_and_targets_shared_across_seeds=True,
        no_new_acoustic_encoder=True,field_masks='No tempo regression, grouping or class-meter supervision',
        model_implementation_sha256=digest(Path(__file__).with_name('production_observations.py')))
    (a.output/'training.json').write_text(json.dumps(value,indent=2)+'\n')


if __name__=='__main__':main()
