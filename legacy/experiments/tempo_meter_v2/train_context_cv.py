"""Song-group validation for the 125-quarter downbeat model.

Ten reviewed songs supply train/validation labels. The eleventh held-out song's
reference file is never opened by this runner, including for hyperparameters.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import numpy as np
import torch
from torch import nn
from .constant_grid import _probability
from .run_constant_grid11 import digest,read_bound,save
from .tempo_segments import _sample
from .train_cross_song_downbeat import label_barlines
from .train_context_downbeat import (ContextDownbeat,song_features,shorten_bars,
                                     HIDDEN,POS_WEIGHT,SEED)

EPOCHS=(10,20,30,40)
THRESHOLDS=(.4,.5,.6,.7)

def f1(y,p,threshold):
 guessed=p>=threshold
 y=np.asarray(y,dtype=bool)
 tp=int(np.count_nonzero(y&guessed))
 fp=int(np.count_nonzero(~y&guessed))
 fn=int(np.count_nonzero(y&~guessed))
 return 2*tp/(2*tp+fp+fn) if tp+fp+fn else 1.


def learn(rows,augment,epochs,seed,device,validation=None):
 torch.manual_seed(seed)
 rng=np.random.default_rng(seed)
 model=ContextDownbeat(rows[0]['x'].shape[1]).to(device)
 optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
 loss_fn=nn.BCEWithLogitsLoss(pos_weight=torch.tensor(POS_WEIGHT,device=device))
 records=[]
 for epoch in range(1,epochs+1):
  model.train();losses=[]
  for i in rng.permutation(len(rows)):
   row=rows[int(i)];x,y=row['x'],row['y']
   if augment:x,y,_=shorten_bars(x,y,rng)
   x_t=torch.from_numpy(x.T.copy()).unsqueeze(0).to(device)
   y_t=torch.from_numpy(y.astype(np.float32)).unsqueeze(0).to(device)
   optimizer.zero_grad(set_to_none=True)
   value=loss_fn(model(x_t),y_t)
   value.backward();nn.utils.clip_grad_norm_(model.parameters(),1.)
   optimizer.step();losses.append(float(value.detach().cpu()))
  if epoch in EPOCHS:
   entry={'epoch':epoch,'mean_training_loss':float(np.mean(losses))}
   if validation is not None:
    model.eval();scores=[]
    with torch.inference_mode():
     for item in validation:
      x_t=torch.from_numpy(item['x'].T.copy()).unsqueeze(0).to(device)
      p=torch.sigmoid(model(x_t))[0].cpu().numpy()
      scores.append({'id':item['id'],
        'f1_by_threshold':{str(thr):f1(item['y'],p,thr) for thr in THRESHOLDS}})
    entry['validation_songs']=scores
   records.append(entry)
 return model,records


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
 observed=json.loads(a.final1_manifest.read_text())
 template=json.loads(a.template_evidence.read_text())
 if (catalog.get('track_count')!=11 or not predictions.get('complete') or
     predictions.get('references_available_to_runner') is not False or
     not observed.get('complete') or template.get('reference_read') is not False):
  raise ValueError('eleven source-only input bindings required')
 by={x['id']:x for x in catalog['tracks']}
 pred_by={x['id']:x for x in predictions['rows']}
 obs_by={x['id']:x for x in observed['rows']}
 if set(by)!=set(pred_by) or set(by)!=set(obs_by) or a.heldout_id not in by:
  raise ValueError('track set mismatch')
 training=[];inputs=[]
 for track_id in sorted(by):
  fm_path=a.phrase_root/track_id/'manifest.json'
  fm=json.loads(fm_path.read_text())
  if fm.get('reference_used') is not False:raise ValueError('feature used reference')
  source=pred_by[track_id]['source']
  if not(source['sha256']==fm['audio']['sha256']==obs_by[track_id]['source']['sha256']):
   raise ValueError('source differs across inputs')
  feature_path=read_bound(fm['features'])
  logit_path=read_bound(obs_by[track_id]['observations'][0]['logits'])
  with np.load(feature_path) as feat,np.load(logit_path) as logits:
   vector=np.asarray(feat['vectors'],dtype=float)
   times=np.asarray(feat['beat_times_seconds'][:len(vector)],dtype=float)
   probability=_sample(_probability(logits['downbeat']),float(logits['fps']),times)
  x=song_features(vector,probability)
  meta={'id':track_id,'source_sha256':source['sha256'],
        'feature_manifest_sha256':digest(fm_path),
        'feature_sha256':digest(feature_path),
        'final1_logits_sha256':digest(logit_path),
        'heldout':track_id==a.heldout_id}
  if track_id==a.heldout_id:
   heldout={'id':track_id,'x':x,'times':times}
  else:
   binding=by[track_id]['accepted_tempo_map']
   reference=json.loads(read_bound(binding).read_text())
   y=label_barlines(times,reference['downbeats_seconds'])
   first_step=next((z['time_seconds'] for z in reference['tempo_events'][1:]
                    if z['time_seconds']>0),None)
   if first_step is not None:
    mask=times<first_step-1.
    x,y,probability=x[mask],y[mask],probability[mask]
   if len(y)<30 or y.sum()<4:raise ValueError('training song too short')
   training.append({'id':track_id,'x':x,'y':y,'raw':probability})
   meta.update({'training_reference_sha256':binding['sha256'],
                'training_quarters':len(y),'training_bars':int(y.sum()),
                'first_tempo_step_cut_seconds':first_step})
  inputs.append(meta)
 names=sorted(x['id'] for x in training)
 if len(names)!=10:raise ValueError('ten labeled groups required')
 folds=[names[i::5] for i in range(5)]
 device=torch.device(a.device)
 cv=[]
 for augmented in (False,True):
  for fold_index,valid_ids in enumerate(folds):
   valid=[x for x in training if x['id'] in valid_ids]
   train=[x for x in training if x['id'] not in valid_ids]
   _,records=learn(train,augmented,max(EPOCHS),SEED+fold_index+(100 if augmented else 0),device,valid)
   cv.append({'augmented':augmented,'fold':fold_index,
              'validation_ids':valid_ids,'checkpoints':records})
   print('cv','augmented' if augmented else 'plain','fold',fold_index,
         'valid',valid_ids,flush=True)
 ranks=[]
 for augmented in (False,True):
  for epoch in EPOCHS:
   for threshold in THRESHOLDS:
    scores=[]
    for fold in cv:
     if fold['augmented']!=augmented:continue
     check=next(z for z in fold['checkpoints'] if z['epoch']==epoch)
     scores += [x['f1_by_threshold'][str(threshold)] for x in check['validation_songs']]
    if len(scores)!=10:raise ValueError('incomplete grouped validation')
    ranks.append({'augmented':augmented,'epoch':epoch,'threshold':threshold,
                  'macro_song_f1':float(np.mean(scores)),
                  'per_song_f1':scores})
 ranks.sort(key=lambda z:(-z['macro_song_f1'],z['epoch'],
                          abs(z['threshold']-.5),z['augmented']))
 selected=ranks[0]
 baseline={str(t):float(np.mean([f1(x['y'],x['raw'],t) for x in training]))
           for t in THRESHOLDS}
 final_model,history=learn(training,selected['augmented'],selected['epoch'],
                           SEED+500,device)
 final_model.eval()
 with torch.inference_mode():
  x_t=torch.from_numpy(heldout['x'].T.copy()).unsqueeze(0).to(device)
  probabilities=torch.sigmoid(final_model(x_t))[0].cpu().numpy()
 lo,hi=template['source_detected_pulse_region']
 if not(0<lo<hi<len(probabilities)):raise ValueError('heldout phrase missing')
 candidates=[]
 for old in template['candidates']:
  n,phase=old['exceptional_bar_quarters'],old['phase_modulo22']
  offsets=[0]+[n+4*i for i in range((22-n)//4)]
  bars=np.asarray([q for q in range(lo,hi) if (q-phase)%22 in offsets])
  mask=np.zeros(hi-lo,dtype=bool);mask[bars-lo]=True
  clipped=np.clip(probabilities[lo:hi],1e-6,1-1e-6)
  candidates.append({'exceptional_bar_quarters':n,'phase_modulo22':phase,
    'mean_probability_at_bars':float(probabilities[bars].mean()),
    'negative_log_likelihood_per_quarter':-float(np.mean(
       np.where(mask,np.log(clipped),np.log1p(-clipped))))})
 out=a.output.resolve();out.mkdir(parents=True)
 snap=out/'source-snapshot';snap.mkdir()
 shutil.copy2(__file__,snap/Path(__file__).name)
 np.savez_compressed(out/'heldout-prediction.npz',
  quarter_times_seconds=heldout['times'],downbeat_probability=probabilities,
  cv_selected_threshold=np.array(selected['threshold']))
 weights=out/'context-model.pt';torch.save(final_model.cpu().state_dict(),weights)
 result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'heldout_id':a.heldout_id,'heldout_reference_read':False,
  'scope':'group-validated beat-context observation; not full meter map',
  'catalog_sha256':digest(a.catalog),
  'prediction_manifest_sha256':digest(a.prediction_manifest),
  'final1_manifest_sha256':digest(a.final1_manifest),
  'template_evidence_sha256':digest(a.template_evidence),
  'training_inputs':inputs,'folds':folds,
  'model_config':{'epochs_tested':EPOCHS,'thresholds_tested':THRESHOLDS,
   'positive_class_weight':POS_WEIGHT,'hidden':HIDDEN,
   'augmentation':'remove one/two internal beats from selected4/4 training bars'},
  'cv_ranking':ranks,'cv_raw_final1_macro_f1':baseline,
  'cv_fold_evidence':cv,'selected':selected,
  'final_training_history':history,
  'model_weights_sha256':digest(weights),
  'heldout_prediction_sha256':digest(out/'heldout-prediction.npz'),
  'heldout_phrase_pulses':[lo,hi],
  'template_candidates':candidates,
  'runner_sha256':digest(__file__),'torch_version':torch.__version__,
  'device':a.device}
 save(out/'manifest.json',result)
 print('selected',selected['augmented'],selected['epoch'],selected['threshold'],
       'CV F1',round(selected['macro_song_f1'],4),'raw',baseline,flush=True)
 for key in ('mean_probability_at_bars','negative_log_likelihood_per_quarter'):
  order=sorted(candidates,key=lambda z:z[key],reverse=key.startswith('mean'))
  print(key,[(z['exceptional_bar_quarters'],z['phase_modulo22']) for z in order[:7]],flush=True)

if __name__=='__main__':main()
