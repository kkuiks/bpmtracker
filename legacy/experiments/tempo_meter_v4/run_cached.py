"""Run the document route on bound audio observations, with no references."""
import argparse
import json
from pathlib import Path
import sys
import time
import resource
import numpy as np
from .observations import prepare
from .analyzer import analyze
from experiments.tempo_meter_v3.probe_resources import digest


def load(row,cache_root):
    path=cache_root/(row['source']['sha256']+'.npz')
    receipt=json.loads(path.with_suffix('.json').read_text())
    if receipt['binding']!=row['feature_binding'] or digest(path)!=receipt['feature_sha256']:
        raise ValueError('acoustic observation binding differs')
    with np.load(path) as z:
        logits,energy,features=z['logits'].copy(),z['energy'].copy(),z['features'].copy()
    return prepare(logits,energy,features=features)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,default=Path('data/cache/tempo-meter-v3/acoustic-v1'))
    p.add_argument('--repetition',choices=['none','automatic'],default='none')
    p.add_argument('--limit',type=int);p.add_argument('--beam',type=int,default=32)
    a=p.parse_args();sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    inputs=json.loads(a.input.read_text());assert inputs['complete'] and inputs['references_available_to_runner'] is False
    calibration=json.loads(a.parameters.read_text());assert calibration['validation_pass']
    a.output.mkdir(parents=True,exist_ok=False)
    record=dict(complete=False,references_available_to_runner=False,input_sha256=digest(a.input),
        parameters_sha256=digest(a.parameters),implementation_sha256={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')},
        repetition=a.repetition,rows=[])
    for i,row in enumerate(inputs['rows'][:a.limit]):
        start=time.perf_counter()
        if digest(row['audio'])!=row['source']['sha256']:raise ValueError('audio changed')
        obs=load(row,a.cache_root)
        selected,alternatives=analyze(obs,row['source'],row.get('initial_bpm'),parameters=calibration['selected'],repetition=a.repetition,beam=a.beam)
        folder=a.output/f'{i:02d}';folder.mkdir()
        path=folder/'selected.json';path.write_text(json.dumps(selected,indent=2,allow_nan=False)+'\n')
        (folder/'alternatives.json').write_text(json.dumps(alternatives,indent=2,allow_nan=False)+'\n')
        result={k:row[k] for k in ('id','title','audio','source','initial_bpm','initial_bpm_source','feature_binding')}
        result.update(selected=dict(path=str(path.resolve()),sha256=digest(path)),runtime_seconds=time.perf_counter()-start,
            max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,references_available_to_runner=False,
            acoustic_model_changed=False,old_clock_candidates_used=False)
        record['rows'].append(result)
        (a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
        print(row['id'],round(result['runtime_seconds'],3),'seconds',len(selected['map']['meter_events']),'meter events',len(selected['map']['clock_knots'])-1,'tempo spans',flush=True)
    record['complete']=True;(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
