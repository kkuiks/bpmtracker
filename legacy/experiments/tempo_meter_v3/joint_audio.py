"""One-mix source-only entry for the unadopted joint-clock experiment."""
import argparse
import json
from pathlib import Path
import sys
from .analyzer import analyze
from .run_joint_cached import infer
from .reconstruct_cached import original_clock,load_observations
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--initial-bpm',type=float)
    p.add_argument('--acoustic-checkpoint',type=Path,required=True)
    p.add_argument('--structure-checkpoint',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    a.output.mkdir(parents=True,exist_ok=False)
    row=analyze(a.audio,a.initial_bpm,acoustic_checkpoint=a.acoustic_checkpoint,
                structure_checkpoint=a.structure_checkpoint,cache_root=a.cache_root,output=a.output/'seeds')
    import numpy as np
    folder=a.output/'seeds'
    with np.load(folder/'structural-observations.npz') as z:structure={k:z[k].copy() for k in z.files}
    cache=a.cache_root/(row['source']['sha256']+'.npz')
    receipt=json.loads(cache.with_suffix('.json').read_text())
    if receipt['binding']!=row['feature_binding']:raise ValueError('feature identity changed')
    with np.load(cache) as z:logits,energy=z['logits'].copy(),z['energy'].copy()
    stored=json.loads((folder/'candidate-bank.json').read_text())
    seeds=[dict(name=c['name'],clock=original_clock(c),joint_score=c['score'],original_prediction=c['prediction']) for c in stored]
    results,_,diagnostic=infer(row,seeds,logits,energy,structure)
    selected=a.output/'selected.json';selected.write_text(json.dumps(results['joint']['selected'],indent=2)+'\n')
    record=dict(source=row['source'],selected=dict(path=str(selected.resolve()),sha256=digest(selected)),
                references_available_to_runner=False,acoustic_cache_hit=row['cache_hit'],
                baseline_run=str((folder/'run.json').resolve()),diagnostics=diagnostic,
                experimental_not_promoted=True)
    (a.output/'run.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':main()
