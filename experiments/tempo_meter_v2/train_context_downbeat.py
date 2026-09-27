"""Compare plain and meter-augmented beat-context models on one held-out song.

The target song's accepted map is never opened. Other reviewed songs are
training data only; their old selected predictions are never rescored here.
This is an observation experiment, not a complete musical-map analyzer.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from .constant_grid import _probability
from .run_constant_grid11 import digest, read_bound, save
from .tempo_segments import _sample
from .train_cross_song_downbeat import label_barlines

SEED=20260927
EPOCHS=40
HIDDEN=64
POS_WEIGHT=3.0

class ResidualContext(nn.Module):
 def __init__(self,channels,dilation):
  super().__init__()
  self.net=nn.Sequential(nn.Conv1d(channels,channels,3,padding=dilation,dilation=dilation),
                         nn.GELU(),nn.Dropout(.15))
 def forward(self,x):return x+self.net(x)

class ContextDownbeat(nn.Module):
 def __init__(self,features):
  super().__init__()
  self.net=nn.Sequential(nn.Conv1d(features,HIDDEN,5,padding=2),nn.GELU(),
    *(ResidualContext(HIDDEN,d) for d in (1,2,4,8,16)),
    nn.Conv1d(HIDDEN,1,1))
 def forward(self,x):return self.net(x).squeeze(1)


def song_features(vector,probability):
 v=np.asarray(vector,dtype=float)
 p=np.asarray(probability,dtype=float)
 if v.ndim!=2 or len(v)!=len(p) or not np.isfinite(v).all() or not np.isfinite(p).all():
  raise ValueError('finite paired beat features required')
 med=np.median(v,axis=0)
 spread=np.maximum(np.median(np.abs(v-med),axis=0)*1.4826,.05)
 z=np.clip((v-med)/spread,-5,5)
 return np.column_stack((z,p)).astype(np.float32)


def shorten_bars(x,y,rng):
 """Splice some known 4-quarter training bars into 2/3-quarter examples."""
 starts=np.flatnonzero(y)
 available=[int(a) for a,b in zip(starts,starts[1:]) if b-a==4]
 if not available:return x,y,0
 count=min(max(1,len(available)//32),5)
 chosen=rng.choice(available,size=min(count,len(available)),replace=False)
 keep=np.ones(len(y),dtype=bool)
 for start in chosen:
  if rng.random()<.5:keep[start+3]=False
  else:keep[start+2:start+4]=False
 return x[keep],y[keep],int(len(chosen))


def train_arm(rows,augment,device):
 torch.manual_seed(SEED+(1 if augment else 0))
 rng=np.random.default_rng(SEED+(1 if augment else 0))
 model=ContextDownbeat(rows[0]['x'].shape[1]).to(device)
 optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
 criterion=nn.BCEWithLogitsLoss(pos_weight=torch.tensor(POS_WEIGHT,device=device))
 history=[]
 for epoch in range(EPOCHS):
  model.train();losses=[];shortened=0
  for index in rng.permutation(len(rows)):
   row=rows[int(index)];x,y=row['x'],row['y']
   if augment:
    x,y,count=shorten_bars(x,y,rng);shortened+=count
   x_t=torch.from_numpy(x.T.copy()).unsqueeze(0).to(device)
   y_t=torch.from_numpy(y.astype(np.float32)).unsqueeze(0).to(device)
   optimizer.zero_grad(set_to_none=True)
   logits=model(x_t)
   loss=criterion(logits,y_t)
   loss.backward()
   nn.utils.clip_grad_norm_(model.parameters(),1.)
   optimizer.step()
   losses.append(float(loss.detach().cpu()))
  history.append({'epoch':epoch+1,'mean_training_loss':float(np.mean(losses)),
                  'synthetically_shortened_bars':shortened})
  if (epoch+1)%10==0:print('augmented' if augment else 'plain','epoch',epoch+1,
                         'loss',round(float(np.mean(losses)),4),flush=True)
 return model,history


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--heldout-id',required=True)
 p.add_argument('--catalog',type=Path,required=True)
 p.add_argument('--prediction-manifest',type=Path,required=True)
 p.add_argument('--phrase-root',type=Path,required=True)
 p.add_argument('--final1-manifest',type=Path,required=True)
 p.add_argument('--template-evidence',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--device',choices=('cpu','cuda'),default='cuda')
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new output required')
 if a.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
 torch.set_num_threads(4)
 torch.backends.cudnn.deterministic=True
 torch.backends.cudnn.benchmark=False
 catalog=json.loads(a.catalog.read_text())
 predictions=json.loads(a.prediction_manifest.read_text())
 observations=json.loads(a.final1_manifest.read_text())
 template=json.loads(a.template_evidence.read_text())
 if (catalog.get('track_count')!=11 or not predictions.get('complete') or
     predictions.get('references_available_to_runner') is not False or
     not observations.get('complete') or template.get('reference_read') is not False):
  raise ValueError('complete source-only target inputs required')
 by_id={r['id']:r for r in catalog['tracks']}
 pred_by={r['id']:r for r in predictions['rows']}
 obs_by={r['id']:r for r in observations['rows']}
 if set(by_id)!=set(pred_by) or set(by_id)!=set(obs_by) or a.heldout_id not in by_id:
  raise ValueError('eleven input identities differ')
 train=[];inputs=[]
 for track_id in sorted(by_id):
  feature_manifest_path=a.phrase_root/track_id/'manifest.json'
  fm=json.loads(feature_manifest_path.read_text())
  if fm.get('reference_used') is not False:raise ValueError('source feature used reference')
  source=pred_by[track_id]['source']
  if not(source['sha256']==fm['audio']['sha256']==obs_by[track_id]['source']['sha256']):
   raise ValueError('source identity differs')
  fpath=read_bound(fm['features'])
  lpath=read_bound(obs_by[track_id]['observations'][0]['logits'])
  with np.load(fpath) as feat,np.load(lpath) as logits:
   vector=np.asarray(feat['vectors'],dtype=float)
   times=np.asarray(feat['beat_times_seconds'][:len(vector)],dtype=float)
   probability=_sample(_probability(logits['downbeat']),float(logits['fps']),times)
  x=song_features(vector,probability)
  input_row={'id':track_id,'source_sha256':source['sha256'],
   'feature_manifest_sha256':digest(feature_manifest_path),
   'feature_sha256':digest(fpath),'final1_logits_sha256':digest(lpath),
   'heldout':track_id==a.heldout_id}
  if track_id==a.heldout_id:
   heldout={'id':track_id,'x':x,'times':times}
  else:
   ref_binding=by_id[track_id]['accepted_tempo_map']
   reference=json.loads(read_bound(ref_binding).read_text())
   y=label_barlines(times,reference['downbeats_seconds'])
   first_step=next((e['time_seconds'] for e in reference['tempo_events'][1:]
                   if e['time_seconds']>0),None)
   if first_step is not None:
    valid=times<first_step-1.
    x,y=x[valid],y[valid]
   if len(y)<30 or y.sum()<4:raise ValueError('training song too short')
   train.append({'id':track_id,'x':x,'y':y})
   input_row.update({'training_reference_sha256':ref_binding['sha256'],
                     'training_quarters':len(y),'training_bars':int(y.sum()),
                     'first_tempo_step_cut_seconds':first_step})
  inputs.append(input_row)
 lo,hi=template['source_detected_pulse_region']
 if not (0<lo<hi<len(heldout['times'])):raise ValueError('heldout phrase not covered')
 out=a.output.resolve();out.mkdir(parents=True)
 snap=out/'source-snapshot';snap.mkdir();shutil.copy2(__file__,snap/Path(__file__).name)
 device=torch.device(a.device)
 arms=[]
 for augmented in (False,True):
  name='augmented' if augmented else 'plain'
  model,history=train_arm(train,augmented,device)
  model.eval()
  with torch.inference_mode():
   tensor=torch.from_numpy(heldout['x'].T.copy()).unsqueeze(0).to(device)
   probs=torch.sigmoid(model(tensor))[0].cpu().numpy()
  npz=out/f'{name}-heldout.npz'
  np.savez_compressed(npz,quarter_times_seconds=heldout['times'],
    downbeat_probability=probs,source_frame_offset=np.array(0))
  weights=out/f'{name}-model.pt'
  torch.save(model.cpu().state_dict(),weights)
  candidates=[]
  for old in template['candidates']:
   n,phase=old['exceptional_bar_quarters'],old['phase_modulo22']
   offsets=[0]+[n+4*i for i in range((22-n)//4)]
   bars=np.asarray([q for q in range(lo,hi) if (q-phase)%22 in offsets])
   mask=np.zeros(hi-lo,dtype=bool);mask[bars-lo]=True
   clipped=np.clip(probs[lo:hi],1e-6,1-1e-6)
   nll=-float(np.mean(np.where(mask,np.log(clipped),np.log1p(-clipped))))
   candidates.append({'exceptional_bar_quarters':n,'phase_modulo22':phase,
     'mean_probability_at_bars':float(probs[bars].mean()),
     'negative_log_likelihood_per_quarter':nll})
  arms.append({'name':name,'source_only_heldout':True,
   'weights_sha256':digest(weights),'probabilities_sha256':digest(npz),
   'training_history':history,'template_candidates':candidates})
  for key in ('mean_probability_at_bars','negative_log_likelihood_per_quarter'):
   order=sorted(candidates,key=lambda z:z[key],reverse=key.startswith('mean'))
   print(name,key,[(z['exceptional_bar_quarters'],z['phase_modulo22']) for z in order[:5]],flush=True)
 result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'heldout_id':a.heldout_id,'heldout_reference_read':False,
  'scope':'beat-context model observation; not a complete map',
  'catalog_sha256':digest(a.catalog),
  'prediction_manifest_sha256':digest(a.prediction_manifest),
  'final1_manifest_sha256':digest(a.final1_manifest),
  'template_evidence_sha256':digest(a.template_evidence),
  'training_inputs':inputs,
  'model_config':{'seed':SEED,'epochs':EPOCHS,'hidden':HIDDEN,
    'positive_class_weight':POS_WEIGHT,'optimizer':'AdamW lr .001 weight_decay .01',
    'receptive_field_quarters':125,'augmentation':'remove last one or two internal beats from selected training 4-quarter bars'},
  'heldout_phrase_pulses':[lo,hi],
  'runner_sha256':digest(__file__),'torch_version':torch.__version__,
  'device':a.device,'arms':arms}
 save(out/'manifest.json',result)
 print('training songs',len(train),'heldout',a.heldout_id)
if __name__=='__main__':main()
