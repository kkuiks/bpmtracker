"""Three controlled learned arms with separate tempo/meter change supervision."""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import time
import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from .probe_resources import digest
from .train_structure import targets as old_targets, soft_events


def observed_bar_ids(logits):
    """Source-only downbeat proposals; not fixed output bar boundaries."""
    values=logits[:,1];peaks=np.flatnonzero((values[1:-1]>values[:-2])&(values[1:-1]>=values[2:])&(values[1:-1]>0))+1
    selected=[]
    for peak in peaks:
        if selected and peak-selected[-1]<6:
            if values[peak]>values[selected[-1]]:selected[-1]=int(peak)
        else:selected.append(int(peak))
    return np.searchsorted(selected,np.arange(len(values)),side='right').astype(np.int64)


class CompareModel(nn.Module):
    def __init__(self,arm):
        super().__init__();self.arm=arm;self.input=nn.Linear(1282 if arm=='B' else 514,128)
        layer=lambda:nn.TransformerEncoderLayer(128,4,512,.1,batch_first=True,norm_first=True)
        self.frames=nn.TransformerEncoder(layer(),2 if arm=='C' else 4,enable_nested_tensor=False)
        if arm=='C':
            self.bars=nn.TransformerEncoder(layer(),2,enable_nested_tensor=False)
            self.merge=nn.Linear(256,128)
        self.events=nn.Linear(128,5)
        self.numerator=nn.Linear(128,32);self.denominator=nn.Linear(128,5);self.tempo=nn.Linear(128,1)

    def position(self,n,device,dtype):
        t=torch.arange(n,device=device,dtype=dtype)[:,None]
        f=torch.exp(torch.arange(0,128,2,device=device,dtype=dtype)*(-math.log(10000.)/128))
        out=torch.zeros((n,128),device=device,dtype=dtype);out[:,0::2]=torch.sin(t*f);out[:,1::2]=torch.cos(t*f);return out

    def forward(self,x,padding,bar_ids):
        h=self.input(x);h=self.frames(h+self.position(h.shape[1],h.device,h.dtype),src_key_padding_mask=padding)
        if self.arm=='C':
            size=int(bar_ids.max().item())+1;index=bar_ids[:,:,None].expand(-1,-1,128)
            pooled=h.new_zeros((h.shape[0],size,128));pooled.scatter_add_(1,index,h.masked_fill(padding[:,:,None],0))
            count=h.new_zeros((h.shape[0],size,1));count.scatter_add_(1,bar_ids[:,:,None],(~padding)[:,:,None].to(h.dtype))
            pooled=pooled/count.clamp(min=1);bar_mask=count[:,:,0]==0
            pooled=self.bars(pooled+self.position(size,h.device,h.dtype),src_key_padding_mask=bar_mask)
            pooled=pooled.masked_fill(bar_mask[:,:,None],0)
            h=self.merge(torch.cat([h,torch.gather(pooled,1,index)],-1))
        return dict(events=self.events(h),numerator=self.numerator(h),denominator=self.denominator(h),tempo=self.tempo(h).squeeze(-1))


def targets(row,count):
    y,mask,num,den,tempo,valid=old_targets(row,count);times=np.arange(count)/12.5
    events=np.zeros((count,5),np.float32);weights=np.zeros_like(events);events[:,:4]=y;weights[:,:4]=mask
    label=row['labels'];support=(times>=label['support'][0])&(times<=label['support'][1])
    meter_changes=[m['time_seconds'] for m in label['meter'][1:]] if label['meter_known'] else []
    events[:,2]=soft_events(times,meter_changes,.2)
    weights[:,2]=support*row['weight'] if label['meter_known'] and row['dataset']!='rwc' else 0
    tempo_changes=[b['time_seconds'] for a,b in zip(label['tempo'],label['tempo'][1:]) if abs(b['bpm_quarter']-a['bpm_quarter'])>1e-6]
    events[:,4]=soft_events(times,tempo_changes,.2);weights[:,4]=support*row['weight'] if row['dataset']!='rwc' else 0
    if not label['meter_known']:num[:]=-100;den[:]=-100
    for lo,hi in label.get('no_grid',[]):
        ix=(times>=lo)&(times<hi);events[ix,:]=0;weights[ix,:]=row['weight'];num[ix]=-100;den[ix]=-100
    return events,weights,num,den,tempo,valid


def objective(output,batch):
    x,y,mask,num,den,tempo,valid,padding,bars=batch
    positive=torch.tensor([3.,12.,12.,1.,12.],device=x.device)
    importance=torch.tensor([.5,1.,.3,.2,.3],device=x.device)
    bce=F.binary_cross_entropy_with_logits(output['events'],y,reduction='none',pos_weight=positive)
    loss=(bce*mask*importance).sum()/mask.sum().clamp(min=1)
    for name,target in [('numerator',num),('denominator',den)]:
        known=(target!=-100)&(valid>0)
        if known.any():loss+=.2*(F.cross_entropy(output[name][known],target[known],reduction='none')*valid[known]).sum()/valid[known].sum()
    loss+=.15*(F.smooth_l1_loss(output['tempo'],tempo,reduction='none')*valid).sum()/valid.sum().clamp(min=1)
    return loss


def train(arm,learning,output,mert_cache,steps):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);torch.set_num_threads(4);torch.manual_seed(20260930);rng=np.random.default_rng(20260930)
    rows=json.loads(learning.read_text())['rows'];training=[r for r in rows if r['split']=='train'];validation_rows=[r for r in rows if r['split']=='validation']
    if {r['group'] for r in training}&{r['group'] for r in validation_rows}:raise ValueError('split leakage')
    @lru_cache(maxsize=16)
    def load(path,source_hash):
        with np.load(path) as z:logits=z['logits'][::4].copy();x=np.concatenate([z['features'][::4].astype(np.float32),logits],1)
        bars=observed_bar_ids(logits)
        if arm=='B':
            with np.load(mert_cache/(source_hash+'.npz')) as z:extra=z['features'].astype(np.float32)
            if len(extra)!=len(x):raise ValueError('feature alignment mismatch')
            x=np.concatenate([x,extra],1)
        return x,bars
    dim=1282 if arm=='B' else 514;sums=np.zeros(dim);squares=np.zeros(dim);count=0
    for row in training:
        x,_=load(row['cache'],row['audio_sha256']);x=x[::5].astype(np.float64);sums+=x.sum(0);squares+=(x*x).sum(0);count+=len(x)
    mean=(sums/count).astype(np.float32);std=np.sqrt(np.maximum(.01,squares/count-mean*mean)).astype(np.float32)
    labels={r['id']:targets(r,len(load(r['cache'],r['audio_sha256'])[0])) for r in rows}
    def window(row,start):
        x,bars=load(row['cache'],row['audio_sha256']);n=min(400,len(x)-start);x=(x-mean)/std
        cropped=[]
        for value,default in zip([x,*labels[row['id']]],[0,0,0,-100,-100,0,0]):
            dest=np.full((400,*value.shape[1:]),default,dtype=value.dtype);dest[:n]=value[start:start+n];cropped.append(dest)
        bi=np.zeros(400,np.int64);bi[:n]=bars[start:start+n]-bars[start];bi[n:]=bi[n-1]
        return (*cropped,np.arange(400)>=n,bi)
    def batch(examples):return tuple(torch.from_numpy(np.stack(v)).cuda() for v in zip(*examples))
    validation=[window(r,start) for r in validation_rows for start in range(0,len(load(r['cache'],r['audio_sha256'])[0]),400)]
    model=CompareModel(arm).cuda();optimizer=torch.optim.AdamW(model.parameters(),lr=2e-4,weight_decay=.01)
    best=float('inf');history=[];start_time=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for step in range(1,steps+1):
        examples=[]
        for i in range(4):
            pool=[r for r in training if (r['dataset']=='procedural')==(i%2==0)]
            row=pool[int(rng.integers(len(pool)))];length=len(load(row['cache'],row['audio_sha256'])[0]);examples.append(window(row,int(rng.integers(max(1,length-400+1)))))
        v=batch(examples);model.train();optimizer.zero_grad(set_to_none=True);loss=objective(model(v[0],v[-2],v[-1]),v)
        if not torch.isfinite(loss):raise ValueError('nonfinite learning loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
        if step%100==0 or step==steps:
            model.eval();scores=[]
            with torch.inference_mode():
                for i in range(0,len(validation),4):
                    v=batch(validation[i:i+4]);scores.append(float(objective(model(v[0],v[-2],v[-1]),v)))
            score=float(np.mean(scores));history.append(dict(step=step,train_loss=float(loss.detach()),validation_loss=score,elapsed_seconds=time.perf_counter()-start_time))
            if score<best:
                best=score;torch.save(dict(arm=arm,state_dict=model.state_dict(),mean=mean.tolist(),std=std.tolist(),selected_step=step,
                    validation_loss=score,learning_manifest_sha256=digest(learning),primary20_used_for_training=False,
                    implementation_sha256=digest(__file__),event_heads=['quarter','downbeat','meter_change','grid','tempo_change']),output/'best.pt')
            (output/'history.json').write_text(json.dumps(history,indent=2)+'\n');print(arm,history[-1],flush=True)
    record=dict(arm=arm,complete=True,training_rows=len(training),validation_rows=len(validation_rows),steps=steps,
                best_validation_loss=best,elapsed_seconds=time.perf_counter()-start_time,peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                checkpoint_sha256=digest(output/'best.pt'),primary20_used_for_training=False)
    (output/'result.json').write_text(json.dumps(record,indent=2)+'\n')


def predict(features,logits,checkpoint,extra=None):
    package=torch.load(checkpoint,map_location='cuda',weights_only=False);arm=package['arm'];model=CompareModel(arm).cuda();model.load_state_dict(package['state_dict']);model.eval()
    x=np.concatenate([features[::4].astype(np.float32),logits[::4]],1);bars=observed_bar_ids(logits[::4])
    if arm=='B':
        if extra is None or len(extra)!=len(x):raise ValueError('bound MERT frames required')
        x=np.concatenate([x,extra.astype(np.float32)],1)
    x=(x-np.asarray(package['mean'],np.float32))/np.asarray(package['std'],np.float32);outputs={}
    with torch.inference_mode():
        for core in range(0,len(x),300):
            lo=max(0,core-50);hi=min(len(x),core+350);end=min(len(x),core+300)
            tx=torch.from_numpy(x[lo:hi]).cuda()[None];bi=torch.from_numpy(bars[lo:hi]-bars[lo]).cuda()[None]
            y=model(tx,torch.zeros((1,hi-lo),dtype=torch.bool,device='cuda'),bi)
            for name,value in y.items():
                v=value[0].cpu().numpy()
                if name not in outputs:outputs[name]=np.zeros((len(x),*v.shape[1:]),np.float32)
                outputs[name][core:end]=v[core-lo:end-lo]
    outputs['tempo_change']=outputs['events'][:,4].copy();outputs['events']=outputs['events'][:,:4]
    return outputs


def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['A','B','C'],required=True);p.add_argument('--learning',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mert-cache',type=Path,default=Path('data/cache/tempo-meter-v3/mert-v2'));p.add_argument('--steps',type=int,default=800);a=p.parse_args()
    train(a.arm,a.learning,a.output,a.mert_cache,a.steps)


if __name__=='__main__':main()
