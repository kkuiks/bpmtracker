"""One audio file -> factored experimental musical timeline."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch

from .audio_features import digest,extract
from .observer import predict,model_filename
from .prediction import analyse


def main():
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--acoustic-checkpoint',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',default='cpu')
    p.add_argument('--event-policy',choices=('learned','frozen'),default='learned')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);tick=time.perf_counter()
    source,cache,receipt=extract(a.audio,a.acoustic_checkpoint,a.cache_root,device=a.device)
    with np.load(cache) as z:f,b,e=z['features'].copy(),z['logits'].copy(),z['energy'].copy()
    package=torch.load(a.model,map_location='cpu',weights_only=False);torch.set_num_threads(1)
    if package['model_source_sha256']!=digest(Path(__file__).with_name(model_filename(package))):raise ValueError('model implementation binding differs')
    mark=time.perf_counter();fields=predict(f,b,e,package,device=a.device,event_policy=a.event_policy);observation_seconds=time.perf_counter()-mark
    mark=time.perf_counter();result=analyse(fields,source);decode_seconds=time.perf_counter()-mark
    if result['physical_timeline'] is not None:
        (a.output/'timeline.json').write_text(json.dumps(result['physical_timeline'],indent=2,allow_nan=False)+'\n')
    (a.output/'selected.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    record=dict(source=source,acoustic=receipt,model_sha256=digest(a.model),event_policy=a.event_policy,prediction_status=result['status'],physical_timeline_retained=result['physical_timeline'] is not None,observation_seconds=observation_seconds,decode_seconds=decode_seconds,total_seconds=time.perf_counter()-tick,references_available=False,experimental_not_promoted=True,native_windows_validated=False)
    (a.output/'run.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
    if result['status']=='decode_failed':raise SystemExit(2)


if __name__=='__main__':main()
