"""Offline supervised chronological model; select later on actual maps."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time
import numpy as np
import torch
from torch.nn import functional as F

from services.analysis.model import ChronologicalModel, feature_inputs


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest', type=Path, required=True);p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=600);p.add_argument('--tiny', action='store_true');p.add_argument('--seed', type=int, default=20261002)
    p.add_argument('--cadence',action='store_true')
    a=p.parse_args();torch.set_num_threads(1);torch.manual_seed(a.seed);np.random.seed(a.seed);random.seed(a.seed)
    selected_inputs=feature_inputs;model_type=ChronologicalModel;model_source='services/analysis/model.py'
    if a.cadence:
        from services.analysis.cadence_model import CadenceModel,feature_inputs as cadence_inputs
        selected_inputs=cadence_inputs;model_type=CadenceModel;model_source='services/analysis/cadence_model.py'
    manifest=json.loads(a.manifest.read_text());rows=[r for r in manifest['rows'] if r['split']=='train']
    if a.tiny:rows=[r for r in rows if r['id'] in {'ntm_archspire_liminal-cypher','forrester-savell-karnivool'}]
    a.output.mkdir(parents=True, exist_ok=False);data=[]
    for row in rows:
        assert digest(row['features'])==row['feature_sha256'] and digest(row['targets'])==row['targets_sha256']
        with np.load(row['features']) as z:features,base,energy=z['features'].copy(),z['logits'].copy(),z['energy'].copy()
        with np.load(row['targets']) as z:target={k:z[k].copy() for k in z.files}
        count=min(len(base), 48*50) if a.tiny else len(base)
        x=selected_inputs(features[:count],base[:count],energy[:count])
        model_base=np.column_stack([base[:count],x[:,-3]]) if a.cadence else base[:count]
        data.append(dict(x=x,base=model_base.astype(np.float32),targets={k:v[:count] for k,v in target.items()},id=row['id']))
    count=sum(len(r['x']) for r in data)
    mean=sum(r['x'].sum(0,dtype=np.float64) for r in data)/count
    second=sum((r['x']**2).sum(0,dtype=np.float64) for r in data)/count
    std=np.maximum(np.sqrt(np.maximum(second-mean**2,0)), .01)
    for row in data:row['x']=((row['x']-mean)/std).astype(np.float32)
    denominator_counts=np.ones(5)
    for row in data:
        target=row['targets'];denominator_counts+=np.bincount(target['denominator'][target['musical_mask']>.5],minlength=5)
    class_weights=(denominator_counts.max()/denominator_counts)**.5;class_weights=np.minimum(class_weights,10)
    device='cuda' if torch.cuda.is_available() else 'cpu';model=model_type().to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=5e-4,weight_decay=1e-4)
    positive=torch.tensor([2.,8.,1.],device=device);cw=torch.tensor(class_weights,dtype=torch.float32,device=device)
    checkpoints=[];tick=time.perf_counter()
    for step in range(1,a.steps+1):
        row=random.choice(data);width=min(1600,len(row['x']));start=random.randrange(len(row['x'])-width+1);sl=slice(start,start+width)
        x=torch.from_numpy(row['x'][sl]).unsqueeze(0).to(device);base=torch.from_numpy(row['base'][sl]).unsqueeze(0).to(device)
        target={k:torch.from_numpy(v[sl]).to(device) for k,v in row['targets'].items()}
        output=model(x,base)[0];mask=target['mask'];music=target['musical_mask']
        event=F.binary_cross_entropy_with_logits(output[:,:3],target['y'],pos_weight=positive,reduction='none')
        event=(event*mask[:,None]).sum()/max(float(mask.sum())*3,1)
        rate=((output[:,3]-target['log_bpm'])**2*music).sum()/max(float(music.sum()),1)
        unit=(F.cross_entropy(output[:,4:],target['denominator'],weight=cw,reduction='none')*music).sum()/max(float(music.sum()),1)
        loss=event+3*rate+.2*unit;optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5.);optimizer.step()
        if step%100==0:print(step,float(loss.detach()),flush=True)
        if step in {min(400,a.steps),a.steps}:
            package=dict(state_dict={k:v.detach().cpu() for k,v in model.state_dict().items()},mean=mean.astype(np.float32),std=std.astype(np.float32),positive_weights=[2.,8.,1.],class_weights=class_weights.tolist(),seed=a.seed,step=step,manifest_sha256=digest(a.manifest),train_ids=[r['id'] for r in rows],tiny=a.tiny,model_source_sha256=digest(model_source),model_variant='cadence_relative' if a.cadence else 'absolute_rate',unseen_generalization_claim=False)
            path=a.output/('step-'+str(step)+'.pt');torch.save(package,path);checkpoints.append(dict(path=str(path.resolve()),sha256=digest(path),step=step))
    record=dict(complete=True,seed=a.seed,steps=a.steps,tiny=a.tiny,device=device,manifest_sha256=digest(a.manifest),train_ids=[r['id'] for r in rows],runtime_seconds=time.perf_counter()-tick,checkpoints=checkpoints,criterion='Training loss is diagnostic only; no checkpoint selection by loss',source_sha256=digest(__file__))
    (a.output/'training.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))


if __name__=='__main__':main()
