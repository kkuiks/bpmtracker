"""Self-calibrate downbeat accents on one mix without any owner map.

Two acoustic models supply only high-confidence pseudo-labels outside a
source-detected repeated phrase. The held-out phrase is ranked afterward.
This is a diagnostic observation, not a full meter-map predictor.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from .constant_grid import _probability
from .run_constant_grid11 import digest, read_bound, save
from .tempo_segments import _sample


def drum_features(path, times):
 with np.load(path) as a:
  values=a['activations'][0]
  fps=float(a['fps'])
  labels=[int(x) for x in a['labels']]
 if labels != [35,38,47,42,49]:raise ValueError('five-class drum vocabulary changed')
 return np.asarray([values[max(0,int(round(t*fps))-5):
              min(len(values),int(round(t*fps))+6)].max(axis=0)
              for t in times],dtype=float)


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--prediction',type=Path,required=True)
 p.add_argument('--phrase-manifest',type=Path,required=True)
 p.add_argument('--template-evidence',type=Path,required=True)
 p.add_argument('--beatthis0',type=Path,required=True)
 p.add_argument('--beatthis1',type=Path,required=True)
 p.add_argument('--adtof-mix',type=Path,required=True)
 p.add_argument('--adtof-drums',type=Path,required=True)
 p.add_argument('--deps-root',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new output required')
 sys.path.append(str(a.deps_root.resolve()))
 import sklearn
 from sklearn.decomposition import PCA
 from sklearn.linear_model import LogisticRegression
 from sklearn.pipeline import make_pipeline
 from sklearn.preprocessing import StandardScaler
 pred=json.loads(a.prediction.read_text())
 manifest=json.loads(a.phrase_manifest.read_text())
 pool=json.loads(a.template_evidence.read_text())
 if manifest.get('reference_used') is not False or pool.get('reference_read') is not False:
  raise ValueError('all acoustic inputs must be source-only')
 if pred['map']['source']['sha256'] != manifest['audio']['sha256']:
  raise ValueError('source identity changed')
 with np.load(read_bound(manifest['features'])) as feat:
  vector=np.asarray(feat['vectors'],dtype=float)
  grid=np.asarray(feat['beat_times_seconds'][:len(vector)],dtype=float)
 if not np.allclose(grid,np.asarray(pred['beat_times_seconds'][:len(grid)]),atol=1e-8):
  raise ValueError('audio features and candidate grid differ')
 observations=[]
 for path in (a.beatthis0,a.beatthis1):
  with np.load(path) as model:
   observations.append(_sample(_probability(model['downbeat']),float(model['fps']),grid))
 lo,hi=pool['source_detected_pulse_region']
 if not(0<lo<hi<len(grid)):raise ValueError('repeated region not inside full grid')
 median=np.median(vector,axis=0)
 scale=np.maximum(np.median(np.abs(vector-median),axis=0)*1.4826,.05)
 normalized=np.clip((vector-median)/scale,-5,5)
 pc=PCA(n_components=12,random_state=0).fit_transform(normalized)
 index=np.arange(len(pc))
 before=pc[np.maximum(index-1,0)]
 after=pc[np.minimum(index+1,len(pc)-1)]
 x=np.hstack((pc,pc-before,pc-after,
              drum_features(a.adtof_mix,grid),drum_features(a.adtof_drums,grid)))
 p0,p1=observations
 positive=(p0>=.95)&(p1>=.95)
 negative=(p0<=.05)&(p1<=.05)
 outside=(index<lo)|(index>=hi)
 train=outside&(positive|negative)
 if positive[train].sum()<20 or negative[train].sum()<40:
  raise ValueError('insufficient independent pseudo-labels')
 y=positive[train].astype(int)
 model=make_pipeline(StandardScaler(),LogisticRegression(
     C=.1,class_weight='balanced',max_iter=1000,random_state=0))
 model.fit(x[train],y)
 calibrated=model.predict_proba(x)[:,1]
 rows=[]
 for candidate in pool['candidates']:
  n,phase=candidate['exceptional_bar_quarters'],candidate['phase_modulo22']
  offsets=[0]+[n+4*i for i in range((22-n)//4)]
  bars=np.asarray([q for q in range(lo,hi) if (q-phase)%22 in offsets])
  mask=np.zeros(hi-lo,dtype=bool);mask[bars-lo]=True
  probs=np.clip(calibrated[lo:hi],1e-6,1-1e-6)
  likelihood=float(np.mean(np.where(mask,np.log(probs),np.log1p(-probs))))
  rows.append({'exceptional_bar_quarters':n,'phase_modulo22':phase,
               'mean_probability_at_bars':float(calibrated[bars].mean()),
               'negative_log_likelihood_per_quarter':-likelihood})
 out=a.output.resolve();out.mkdir(parents=True)
 snapshot=out/'source-snapshot';snapshot.mkdir()
 shutil.copy2(__file__,snapshot/Path(__file__).name)
 np.savez_compressed(out/'full-source-probability.npz',quarter_times_seconds=grid,
  downbeat_probability=calibrated,train_mask=train,pseudo_positive=positive,
  pseudo_negative=negative)
 result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'source_only':True,'reference_read':False,
  'source_sha256':pred['map']['source']['sha256'],
  'input_sha256':{k:digest(v) for k,v in
   (('prediction',a.prediction),('phrase_manifest',a.phrase_manifest),
    ('template_evidence',a.template_evidence),('beatthis0',a.beatthis0),
    ('beatthis1',a.beatthis1),('adtof_mix',a.adtof_mix),
    ('adtof_drums',a.adtof_drums))},
  'heldout_phrase_pulses':[lo,hi],
  'training_pseudo_positive_count':int(y.sum()),
  'training_pseudo_negative_count':int(len(y)-y.sum()),
  'model':'PCA12 on unsupervised source spectra plus two five-class ADTOF views; class-balanced L2 logistic C=.1',
  'pseudo_label_policy':'outside held-out phrase; both Beat This probabilities >=.95 for positive or <=.05 for negative',
  'template_rows':rows,
  'full_source_probability_sha256':digest(out/'full-source-probability.npz'),
  'runner_sha256':digest(__file__),'sklearn_version':sklearn.__version__}
 save(out/'manifest.json',result)
 for key in ('mean_probability_at_bars','negative_log_likelihood_per_quarter'):
  order=sorted(rows,key=lambda z:z[key],reverse=(key=='mean_probability_at_bars'))
  print(key,[(r['exceptional_bar_quarters'],r['phase_modulo22'],round(r[key],3)) for r in order[:8]])
 print('pseudo labels',int(y.sum()),int(len(y)-y.sum()))

if __name__=='__main__':main()
