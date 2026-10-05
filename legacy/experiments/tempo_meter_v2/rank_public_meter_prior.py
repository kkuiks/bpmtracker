"""Exploratory notation-prior reranking of frozen source-only meter candidates.

Public annotation counts are group deduplicated. Acoustic z scores are not
calibrated log likelihoods, so the lambda sweep is sensitivity analysis only.
No owner map, score, or primary reference is opened.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import shutil
import numpy as np
from .run_constant_grid11 import digest,save

WEIGHTS=(0.,.1,.25,.5,1.)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source-candidates',type=Path,required=True)
 p.add_argument('--public-grammar-audit',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new ranking output required')
 source=json.loads(a.source_candidates.read_text())
 prior=json.loads(a.public_grammar_audit.read_text())
 if (source.get('source_only') is not True or source.get('reference_read') is not False or
     prior.get('annotation_only') is not True or prior.get('source_audio_acquired') is not False):
  raise ValueError('source-only and annotation-only inputs required')
 candidates=source['candidates']
 z=np.asarray(source['standardized_columns'],dtype=float)
 if len(candidates)!=44 or z.shape!=(44,4):raise ValueError('fixed 44-source-candidate pool required')
 groups=prior['context_distinct_track_counts']
 count2,count6=int(groups['2/4']),int(groups['6/4'])
 # Laplace one pseudo-group per competing written-bar grammar.
 probabilities={2:(count2+1)/(count2+count6+2),
                6:(count6+1)/(count2+count6+2)}
 rows=[]
 for i,c in enumerate(candidates):
  n=int(c['exceptional_bar_quarters'])
  if n not in probabilities:raise ValueError('unsupported exceptional bar')
  rows.append({'candidate_index':i,'exceptional_bar_quarters':n,
   'phase_modulo22':int(c['phase_modulo22']),
   'acoustic_z_sum':float(z[i].sum()),
   'annotation_log_prior':float(math.log(probabilities[n]))})
 rankings={}
 for weight in WEIGHTS:
  scores=np.asarray([r['acoustic_z_sum']+weight*r['annotation_log_prior'] for r in rows])
  order=np.argsort(-scores)
  rankings[str(weight)]={'order':[int(i) for i in order],
   'top':[{**rows[int(i)],'combined_score':float(scores[i])} for i in order[:8]],
   'top_to_second_margin':float(scores[order[0]]-scores[order[1]])}
 out=a.output.resolve();out.mkdir(parents=True)
 snap=out/'source-snapshot';snap.mkdir();shutil.copy2(__file__,snap/Path(__file__).name)
 save(out/'ranking.json',{'schema_version':1,
  'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'source_only_target_audio':True,'target_reference_read':False,
  'public_annotation_only':True,
  'source_candidate_sha256':digest(a.source_candidates),
  'public_audit_sha256':digest(a.public_grammar_audit),
  'prior_distinct_song_counts':{'2/4':count2,'6/4':count6},
  'laplace_probabilities':{'2/4':probabilities[2],'6/4':probabilities[6]},
  'acoustic_score_scale':'sum of four per-candidate standardized source-only columns; not a calibrated log likelihood',
  'prior_weight_sweep':list(WEIGHTS),
  'candidate_rows':rows,'rankings':rankings,
  'runner_sha256':digest(__file__)})
 for weight,result in rankings.items():
  top=result['top'][0]
  print(weight,(top['exceptional_bar_quarters'],top['phase_modulo22']),
        'margin',round(result['top_to_second_margin'],3))
if __name__=='__main__':main()
