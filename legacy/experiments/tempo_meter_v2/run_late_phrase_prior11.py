"""Render a bounded late repeated-meter proposal using public notation prior.

This experimental candidate is not a selected/default route. Only the frozen
source-only candidate ranking and external annotation-only prior are read;
owner maps are opened later by the separate eleven-song scorer.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
from .run_constant_grid11 import digest,read_bound,save

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis_legacy'))
from music_map_contract import prepare_map,render_bars


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--selected-manifest',type=Path,required=True)
 p.add_argument('--source-candidates',type=Path,required=True)
 p.add_argument('--public-prior-ranking',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new output required')
 selected=json.loads(a.selected_manifest.read_text())
 evidence=json.loads(a.source_candidates.read_text())
 ranking=json.loads(a.public_prior_ranking.read_text())
 if (not selected.get('complete') or len(selected.get('rows',[]))!=11 or
     selected.get('references_available_to_runner') is not False or
     evidence.get('source_only') is not True or
     evidence.get('reference_read') is not False or
     ranking.get('target_reference_read') is not False or
     ranking['source_candidate_sha256']!=digest(a.source_candidates)):
  raise ValueError('frozen source-only inputs required')
 target_id=evidence['selected_track_id']
 matched=[r for r in selected['rows'] if r['id']==target_id]
 if len(matched)!=1:raise ValueError('source-detected target not in eleven tracks')
 row=matched[0]
 original=read_bound(row['prediction'])
 if digest(original)!=evidence['input_sha256']['grid']:
  raise ValueError('repeated phrase grid changed')
 base=json.loads(original.read_text())
 if base['map']['source']!=row['source']:
  raise ValueError('audio source clock differs')
 order=ranking['rankings']['1.0']['order']
 chosen=ranking['candidate_rows'][order[0]]
 n=chosen['exceptional_bar_quarters'];phase=chosen['phase_modulo22']
 if n not in (2,6) or (22-n)%4:
  raise ValueError('unsupported 22-quarter phrase grammar')
 lo,hi=evidence['source_detected_pulse_region']
 starts=[q for q in range(lo,hi) if q%22==phase and q+n<hi]
 if len(starts)<6 or any(b-a!=22 for a,b in zip(starts,starts[1:])):
  raise ValueError('stable repeated exceptional bars required')
 result=deepcopy(base)
 previous=int(result['map']['meter_events'][-1]['numerator'])
 if len(result['map']['meter_events'])!=1 or previous!=2:
  raise ValueError('this pilot requires the bound constant 2/4 control')
 events=list(result['map']['meter_events'])
 def event(q,size):
  return {'pulse':float(q),'numerator':size,'denominator':4,
          'grouping':[1]*size,'bar_action':'continue'}
 for start in starts:
  if n!=previous:events.append(event(start,n))
  events.append(event(start+n,4))
  previous=4
 result['map']['meter_events']=events
 bars=render_bars(prepare_map(result['map']))
 if bars['status']!='rendered':raise ValueError('candidate cannot render')
 result['bar_starts_seconds']=bars['bar_events_seconds']
 result['diagnostics']['constant_grid_only']=False
 result['diagnostics']['public_meter_prior_pilot']={
  'source_only_target_audio':True,'target_reference_read':False,
  'source_detected_region_pulses':[lo,hi],
  'public_prior_weight':1.,
  'selected_grammar':{'exceptional_bar_quarters':n,'phase_modulo22':phase},
  'exceptional_bar_start_pulses':starts,
  'limitation':'external annotations lack source audio; no confidence calibration'}
 out=a.output.resolve();out.mkdir(parents=True)
 snapshot=out/'source-snapshot';snapshot.mkdir()
 shutil.copy2(__file__,snapshot/Path(__file__).name)
 binding=save(out/'predictions'/f'{target_id}.json',result)
 ledger={'schema_version':1,'complete':True,'references_available_to_runner':False,
  'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'input_sha256':{'selected_manifest':digest(a.selected_manifest),
   'source_candidates':digest(a.source_candidates),
   'public_prior_ranking':digest(a.public_prior_ranking)},
  'runner_sha256':digest(__file__),
  'target_id':target_id,'experimental_not_selected':True,
  'rows':[{'id':r['id'],'source':r['source'],
   'prediction':binding if r['id']==target_id else r['prediction'],
   'selected_input':r['prediction']} for r in selected['rows']]}
 save(out/'prediction-manifest.json',ledger)
 print(target_id,'public-prior grammar',n,'/4 phase',phase,'repetitions',len(starts),
       'meter declarations',len(events))
if __name__=='__main__':main()
