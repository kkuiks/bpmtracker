"""Source-only cycle-bootstrap robustness of a repeated meter-template ranking."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import numpy as np
from .phase_switch_meter import local_drum_attacks
from .run_constant_grid11 import digest, read_bound, save


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--template-evidence',type=Path,required=True)
 p.add_argument('--prediction',type=Path,required=True)
 p.add_argument('--drum-stem',type=Path,required=True)
 p.add_argument('--adtof-activations',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new output required')
 prior=json.loads(a.template_evidence.read_text())
 if prior.get('source_only') is not True or prior.get('reference_read') is not False:
  raise ValueError('source-only template pool required')
 pred=json.loads(a.prediction.read_text())
 grid=np.asarray(pred['beat_times_seconds'],dtype=float)
 lo,hi=prior['source_detected_pulse_region']
 cycles=(hi-lo)//22
 if cycles<6:raise ValueError('at least six complete motif cycles required')
 positions=np.arange(lo,lo+cycles*22)
 attack=[]
 for block in np.array_split(positions,int(np.ceil(len(positions)/32))):
  strength,_=local_drum_attacks(a.drum_stem,grid[block],low=30,high=160,radius=.05)
  attack.extend(strength.tolist())
 drum=np.asarray(attack)
 with np.load(a.adtof_activations) as arr:
  activation=arr['activations'][0]
  fps=float(arr['fps'])
  labels=[int(x) for x in arr['labels']]
 if labels.index(42)!=3:raise ValueError('ADTOF closed-hat channel differs')
 hat=[]
 for time in grid[positions]:
  i=int(round(time*fps))
  hat.append(float(activation[max(0,i-5):min(len(activation),i+6),3].max()))
 hat=np.asarray(hat)
 candidates=[]
 for prior_row in prior['candidates']:
  n=prior_row['exceptional_bar_quarters'];phase=prior_row['phase_modulo22']
  offsets=[0]+[n+4*i for i in range((22-n)//4)]
  if offsets[-1]>=22:raise ValueError('invalid 22-quarter template')
  per_cycle=[]
  for cycle in range(cycles):
   where=np.asarray([j for j in range(cycle*22,(cycle+1)*22)
                     if (positions[j]-phase)%22 in offsets],dtype=int)
   per_cycle.append([float(drum[where].mean()),float(hat[where].mean())])
  candidates.append({'exceptional_bar_quarters':n,'phase_modulo22':phase,
                     'per_cycle_means':per_cycle})
 values=np.asarray([r['per_cycle_means'] for r in candidates])
 if values.shape!=(44,cycles,2):raise ValueError('expected 44 complete templates')
 rng=np.random.default_rng(20260927)
 repetitions=2000
 wins=np.zeros((44,3),dtype=int)
 margins=[]
 for _ in range(repetitions):
  sample=rng.integers(0,cycles,size=cycles)
  means=values[:,sample,:].mean(axis=1)
  z=(means-means.mean(axis=0))/(means.std(axis=0)+1e-12)
  for j,score in enumerate((z[:,0],z[:,1],z.mean(axis=1))):
   order=np.argsort(-score)
   wins[order[0],j]+=1
   if j==2:margins.append(float(score[order[0]]-score[order[1]]))
 means=values.mean(axis=1);z=(means-means.mean(axis=0))/(means.std(axis=0)+1e-12)
 joint=z.mean(axis=1);order=np.argsort(-joint)
 result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'source_only':True,'reference_read':False,
  'source_sha256':pred['map']['source']['sha256'],
  'prediction_sha256':digest(a.prediction),
  'template_pool_sha256':digest(a.template_evidence),
  'drum_stem_sha256':digest(a.drum_stem),
  'adtof_activations_sha256':digest(a.adtof_activations),
  'region_used_quarter_indices':[lo,lo+cycles*22],
  'complete_cycles':cycles,'bootstrap_repetitions':repetitions,
  'random_seed':20260927,
  'features':['derived_drums_30_160hz_positive_flux','finished_mix_adtof_closed_hat'],
  'selection':'mean of per-feature standardized candidate scores',
  'candidate_order':[int(i) for i in order],
  'top_to_second_joint_margin_z':float(joint[order[0]]-joint[order[1]]),
  'bootstrap_joint_margin_p05_p50_p95':np.quantile(margins,[.05,.5,.95]).tolist(),
  'candidates':[{**r,'scores':means[i].tolist(),
                 'joint_z_score':float(joint[i]),
                 'bootstrap_win_fraction':(wins[i]/repetitions).tolist()}
                for i,r in enumerate(candidates)],
  'runner_sha256':digest(__file__)}
 out=a.output.resolve();out.mkdir(parents=True)
 snap=out/'source-snapshot';snap.mkdir();shutil.copy2(__file__,snap/Path(__file__).name)
 save(out/'bootstrap.json',result)
 print('top',[(candidates[i]['exceptional_bar_quarters'],candidates[i]['phase_modulo22'],
               round(float(joint[i]),3),round(float(wins[i,2]/repetitions),3)) for i in order[:8]])

if __name__=='__main__':main()
