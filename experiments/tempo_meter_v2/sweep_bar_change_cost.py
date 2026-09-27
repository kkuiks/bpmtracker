"""Freeze a bounded meter-transition-cost sweep without reading references."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import numpy as np
from .bar_sequence import decode_bar_sequence
from .run_constant_grid11 import digest, read_bound, save

COSTS=(.35,.5,.75,1.,1.5,2.,3.,4.,6.,8.,12.)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--base-manifest',type=Path,required=True)
 p.add_argument('--track-id',required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.output.exists():raise FileExistsError('new sweep output required')
 m=json.loads(a.base_manifest.read_text())
 if not m.get('complete') or m.get('references_available_to_runner') is not False:
  raise ValueError('source-only baseline manifest required')
 rows=[x for x in m['rows'] if x['id']==a.track_id]
 if len(rows)!=1:raise ValueError('exactly one track required')
 row=rows[0]
 base=json.loads(read_bound(row['prediction']).read_text())
 if base['map']['source']!=row['source']:raise ValueError('source geometry differs')
 with np.load(read_bound(row['logits'])) as arrays:
  down=arrays['downbeat'];fps=float(arrays['fps'])
 official=json.loads(read_bound(row['official']).read_text())
 observations=(official['methods']['official']['prediction']
               if 'methods' in official else official)
 out=a.output.resolve();out.mkdir(parents=True)
 snap=out/'source-snapshot';snap.mkdir()
 for path in (Path(__file__),Path(__file__).with_name('bar_sequence.py')):
  shutil.copy2(path,snap/path.name)
 candidates=[]
 for cost in COSTS:
  result=decode_bar_sequence(base,down,fps,observations['downbeats_seconds'],
                             meter_change_cost=cost)
  binding=save(out/'predictions'/f'meter-cost-{cost:g}.json',result)
  candidates.append({'meter_change_cost':cost,
     'selected_meter_changes':result['diagnostics']['bar_sequence']['selected_meter_changes'],
     'prediction':binding})
 save(out/'prediction-manifest.json',{'schema_version':1,'complete':True,
   'source_only':True,'reference_read':False,
   'created_at_utc':datetime.now(timezone.utc).isoformat(),
   'track_id':a.track_id,'source':row['source'],
   'base_manifest_sha256':digest(a.base_manifest),
   'base_prediction':row['prediction'],'logits':row['logits'],
   'official_observations':row['official'],
   'implementation_sha256':{name:digest(snap/name) for name in
      ('sweep_bar_change_cost.py','bar_sequence.py')},
   'candidate_costs':list(COSTS),'candidates':candidates})
 print([(r['meter_change_cost'],r['selected_meter_changes']) for r in candidates])
if __name__=='__main__':main()
