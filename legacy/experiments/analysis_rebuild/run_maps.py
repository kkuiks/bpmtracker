"""Reference-free whole-source runner for the new product inference service."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch

from services.analysis.observer import predict,model_filename
from services.analysis.prediction import analyse


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--event-policy',choices=('learned','frozen'),default='learned')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);torch.set_num_threads(1)
    inputs=json.loads(a.input.read_text());package=torch.load(a.checkpoint,map_location='cpu',weights_only=False)
    if not inputs['complete'] or inputs['references_available_to_runner']:raise ValueError('source-only inputs required')
    if package['model_source_sha256']!=digest(Path('services/analysis')/model_filename(package)):raise ValueError('model implementation differs')
    names=['model.py','cadence_model.py','observer.py','clock.py','timeline.py','legacy_export.py','prediction.py'];bindings={name:digest(Path('services/analysis')/name) for name in names}
    records=[]
    for row in inputs['rows']:
        path=Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['source']['sha256']+'.npz');receipt=json.loads(path.with_suffix('.json').read_text())
        if receipt['binding']!=row['feature_binding'] or digest(path)!=receipt['feature_sha256'] or digest(row['audio'])!=row['source']['sha256']:raise ValueError('source/cache binding differs')
        with np.load(path) as z:f,b,e=z['features'].copy(),z['logits'].copy(),z['energy'].copy()
        tick=time.perf_counter();fields=predict(f,b,e,package,event_policy=a.event_policy);observation_seconds=time.perf_counter()-tick
        tick=time.perf_counter()
        prediction=analyse(fields,row['source']);status=prediction['status']
        if status=='decode_failed':
            expected={'insufficient quarter observations':'insufficient source events','no positive quarter clock':'no valid latent clock','nonmonotonic continuous clock':'no valid latent clock','no resolved meter proposal':'no terminal bar paths','unresolved first bar':'no terminal bar paths'}
            native=prediction['error'];prediction.update(error=expected[native],native_reason=native)
        decode_seconds=time.perf_counter()-tick;folder=a.output/row['id'];folder.mkdir();selected=folder/'selected.json'
        selected.write_text(json.dumps(prediction,indent=2,allow_nan=False)+'\n')
        record={k:row[k] for k in ['id','title','audio','source','initial_bpm','initial_bpm_source','feature_binding']}
        record.update(selected=dict(path=str(selected.resolve()),sha256=digest(selected)),runtime_seconds=observation_seconds+decode_seconds,observation_seconds=observation_seconds,decode_seconds=decode_seconds,checkpoint_sha256=digest(a.checkpoint),event_policy=a.event_policy,prediction_status=status,actual_guide_used=False,references_available_to_runner=False)
        records.append(record)
        manifest=dict(complete=False,input_sha256=digest(a.input),checkpoint_sha256=digest(a.checkpoint),implementation_sha256=bindings,event_policy=a.event_policy,references_available_to_runner=False,expected_source_count=len(inputs['rows']),successful_map_count=sum(r['prediction_status']=='rendered' for r in records),failure_count=sum(r['prediction_status']=='decode_failed' for r in records),rows=records)
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(row['id'],status,round(record['runtime_seconds'],3),flush=True)
    manifest['complete']=True;(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
