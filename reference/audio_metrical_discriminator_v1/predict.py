"""Serialize source-only candidate-unit rankings before reference scoring."""
import argparse
from pathlib import Path
import sys
import numpy as np
from .common import FACTORS,LEARNED,HEURISTIC,read,write,digest,guard
from .worker import arrays
from .model import design,scores,heuristic

def one(feat,method,model,packet):
    value=heuristic(feat,method,packet) if method in HEURISTIC else scores(model,design(feat,packet,LEARNED[method]),feat['valid_candidates'])
    chosen=np.argmax(value,axis=1);chosen[~feat['source_available']]=-1
    rows=[]
    for i,t in enumerate(feat['time']):
        index=int(chosen[i]);factor=FACTORS[index] if index>=0 else None
        rows.append({'time':float(t),'source_bpm':float(feat['base_bpm'][i]),'unit_index':index,'factor':factor,
                     'unit_rate_estimate':float(feat['base_bpm'][i]*factor) if factor else None,
                     'source_quality':float(feat['source_quality'][i]),'status':'OK' if index>=0 else 'SOURCE_UNAVAILABLE',
                     'candidate_scores':value[i].tolist()})
    return {'method':method,'rows':rows,'unit_classification_only':True,
            'not_nominal_bpm_phase_or_boundary_prediction':True,'initial_packet':packet,
            'scores_not_calibrated_probabilities':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--shard',type=int,default=0)
    p.add_argument('--shards',type=int,default=1);a=p.parse_args();run=a.run;guard(run)
    freeze=read(run/'model-freeze.json')
    for r in freeze['models']:
        if digest(run/'models'/f"{r['method']}.npz")!=r['model_sha256']:raise RuntimeError('Model changed')
    models={m:arrays(run/'models'/f'{m}.npz') for m in LEARNED};rows=read(run/'source-inputs.json')['samples'][a.shard::a.shards]
    opened=[];active=[False];forbidden=[]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],str):return
        path=args[0];mode=args[1] if isinstance(args[1],str) else ''
        if any(c in mode for c in 'wax+'):return
        if Path(path).suffix not in ['.json','.npz']:return
        opened.append(path)
        if any(s in path for s in ['/references/','labels','evaluation-index','raw-proxies','catalog.json']):
            forbidden.append(path);raise RuntimeError('Reference read during prediction')
    sys.addaudithook(audit);active[0]=True
    try:
        for row in rows:
            ident=row['id'];feat=arrays(run/'features'/f'{ident}.npz')
            for method in list(LEARNED)+HEURISTIC:
                policies=['none','proxy100','proxy97','proxy103'] if method in ['A4_AUDIO_NEURAL_ANCHOR','A2_AUDIO_ANCHOR'] else ['none','proxy100']
                for policy in policies:
                    packet=None if policy=='none' else read(run/'encoded-units'/policy/f'{ident}.json')
                    output=one(feat,method,models.get(method),packet);output['policy']=policy
                    write(run/'predictions'/method/policy/f'{ident}.json',output)
            print('PREDICTED',ident,flush=True)
    finally:active[0]=False
    write(run/'worker-audit'/f'predict-{a.shard}.json',{'actual_read_hook':True,'opened_data_paths':sorted(set(opened)),
                 'forbidden_reads':forbidden,'not_OS_sandbox':True})
    guard(run)

if __name__=='__main__':main()
