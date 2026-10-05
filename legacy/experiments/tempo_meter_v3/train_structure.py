"""Bounded first structure-learning run with composition-held-out validation."""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from .features import Extractor
from .structure_model import StructureModel,CONFIG
from .synthetic_learning import create
from .probe_resources import digest


def soft_events(times,points,sigma=.075):
    if not len(points):return np.zeros(len(times),np.float32)
    points=np.sort(np.asarray(points));idx=np.searchsorted(points,times)
    distance=np.minimum(abs(times-points[np.clip(idx,0,len(points)-1)]),abs(times-points[np.clip(idx-1,0,len(points)-1)]))
    return np.exp(-.5*(distance/sigma)**2).astype(np.float32)


def targets(row,count):
    times=np.arange(count)/12.5;label=row['labels'];start,end=label['support']
    valid=(times>=start)&(times<=end)
    y=np.zeros((count,4),np.float32);mask=np.zeros_like(y)
    y[:,0]=soft_events(times,label['beats']);mask[:,0]=valid
    if label['meter_known']:
        y[:,1]=soft_events(times,label['bars']);mask[:,1]=valid
    changes=[m['time_seconds'] for m in label['meter'][1:]]
    for a,b in zip(label['tempo'],label['tempo'][1:]):
        if abs(np.log2(b['bpm_quarter']/a['bpm_quarter']))>.02:changes.append(b['time_seconds'])
    if row['dataset']!='rwc':y[:,2]=soft_events(times,changes,.20);mask[:,2]=valid
    y[:,3]=valid;mask[:,3]=valid
    for lo,hi in label.get('no_grid',[]):
        where=(times>=lo)&(times<hi);mask[where,:]=1;y[where,:]=0
    numerator=np.full(count,-100,np.int64);denominator=numerator.copy()
    for i,m in enumerate(label['meter']):
        stop=label['meter'][i+1]['time_seconds'] if i+1<len(label['meter']) else end
        ix=valid&(times>=m['time_seconds'])&(times<stop)
        if 1<=m['numerator']<=32 and m['denominator'] in CONFIG['denominators']:
            numerator[ix]=m['numerator']-1;denominator[ix]=CONFIG['denominators'].index(m['denominator'])
    tempo=np.zeros(count,np.float32)
    for i,m in enumerate(label['tempo']):
        stop=label['tempo'][i+1]['time_seconds'] if i+1<len(label['tempo']) else end
        tempo[(times>=m['time_seconds'])&(times<stop)]=np.log2(m['bpm_quarter']/120)
    return y,mask*row['weight'],numerator,denominator,tempo,valid.astype(np.float32)*row['weight']


def loss(outputs,batch):
    x,y,mask,num,den,tempo,valid,pad=batch
    bce=F.binary_cross_entropy_with_logits(outputs['events'],y,reduction='none',pos_weight=torch.tensor([3.,12.,12.,1.],device=x.device))
    weights=torch.tensor([.5,1.,.3,.2],device=x.device)
    value=(bce*mask*weights).sum()/mask.sum().clamp(min=1)
    for key,target in [('numerator',num),('denominator',den)]:
        known=target!=-100
        if known.any():value=value+.2*F.cross_entropy(outputs[key][known],target[known])
    value=value+.15*(F.smooth_l1_loss(outputs['tempo'],tempo,reduction='none')*valid).sum()/valid.sum().clamp(min=1)
    return value


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--steps',type=int,default=800)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4);torch.manual_seed(20260930);rng=np.random.default_rng(20260930)
    source=json.loads(a.manifest.read_text());rows=source['rows']+create(a.output/'synthetic',32)
    train=[r for r in rows if r['split']=='train'];val=[r for r in rows if r['split']=='validation']
    if {r['group'] for r in train}&{r['group'] for r in val}:raise ValueError('group leakage')
    extractor=Extractor(a.checkpoint)
    for row in rows:
        row['cache']=str(a.cache_root/(row['audio_sha256']+'.npz'))
        m=extractor.extract(row['audio'],row['cache'])
        if m['binding']['source_sha256']!=row['audio_sha256']:raise ValueError('learning source changed')
        print('features',row['id'],round(m['elapsed_seconds'],2),flush=True)
    del extractor;torch.cuda.empty_cache()
    (a.output/'learning-manifest.json').write_text(json.dumps(dict(rows=rows,source_manifest_sha256=digest(a.manifest),primary20_used=False),indent=2)+'\n')
    @lru_cache(maxsize=8)
    def load(path):
        with np.load(path) as z:return np.concatenate([z['features'][::4].astype(np.float32),z['logits'][::4]],1)
    total=0;sums=np.zeros(514);squares=np.zeros(514)
    for row in train:
        x=load(row['cache'])[::5].astype(np.float64);total+=len(x);sums+=x.sum(0);squares+=(x*x).sum(0)
    mean=(sums/total).astype(np.float32);std=np.sqrt(np.maximum(squares/total-mean*mean,.01)).astype(np.float32)
    target_cache={r['id']:targets(r,len(load(r['cache']))) for r in rows}
    def window(row,first):
        x=(load(row['cache'])-mean)/std;n=min(400,len(x)-first)
        values=[x,*target_cache[row['id']]];defaults=[0,0,0,-100,-100,0,0]
        cropped=[]
        for v,default in zip(values,defaults):
            w=np.full((400,*v.shape[1:]),default,dtype=v.dtype);w[:n]=v[first:first+n];cropped.append(w)
        return (*cropped,np.arange(400)>=n)
    def tensor_batch(examples):return tuple(torch.from_numpy(np.stack(items)).cuda() for items in zip(*examples))
    validation=[window(r,first) for r in val for first in range(0,len(load(r['cache'])),400)]
    model=StructureModel().cuda();optimizer=torch.optim.AdamW(model.parameters(),lr=2e-4,weight_decay=.01)
    best=float('inf');history=[];started=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for step in range(1,a.steps+1):
        model.train();examples=[]
        for k in range(4):
            pool=[r for r in train if (r['dataset']=='procedural')==(k%2==0)]
            row=pool[int(rng.integers(len(pool)))];length=len(load(row['cache']))
            examples.append(window(row,int(rng.integers(max(1,length-400+1)))))
        batch=tensor_batch(examples);optimizer.zero_grad(set_to_none=True)
        value=loss(model(batch[0],batch[-1]),batch)
        if not torch.isfinite(value):raise ValueError('nonfinite training loss')
        value.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
        if step%100==0 or step==a.steps:
            model.eval();scores=[]
            with torch.inference_mode():
                for i in range(0,len(validation),4):
                    v=tensor_batch(validation[i:i+4]);scores.append(float(loss(model(v[0],v[-1]),v)))
            score=float(np.mean(scores));history.append(dict(step=step,train_loss=float(value.detach()),validation_loss=score,elapsed_seconds=time.perf_counter()-started))
            if score<best:
                best=score
                torch.save(dict(state_dict=model.state_dict(),mean=mean.tolist(),std=std.tolist(),config=CONFIG,
                    selected_step=step,validation_loss=score,learning_manifest_sha256=digest(a.output/'learning-manifest.json'),
                    primary20_used_for_training=False),a.output/'best.pt')
            (a.output/'history.json').write_text(json.dumps(history,indent=2)+'\n');print('training',history[-1],flush=True)
    result=dict(complete=True,training_rows=len(train),validation_rows=len(val),steps=a.steps,best_validation_loss=best,
        elapsed_seconds=time.perf_counter()-started,peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        checkpoint_sha256=digest(a.output/'best.pt'),primary20_used_for_training=False,
        scope='small external/weak and procedural pilot; validation loss is not unseen studio map accuracy')
    (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
