"""Task-authorized completion, leakage and same-discrete-tap controls."""
import argparse,json
from pathlib import Path
from .common import LEARNED,HEURISTIC,DEVELOPMENT,VALIDATION,PRIOR,read,write,digest,guard
from experiments.variable_clock_composition_v1.common import guard as prior_guard
from experiments.metrical_clock_roles_v1.common import guard as role_guard

def canonical(pred):
    p=dict(pred);p.pop('policy',None);return json.dumps(p,sort_keys=True,allow_nan=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run);prior_guard(PRIOR)
    role_guard(PRIOR.parents[1]/'metrical_clock_roles_v1/20261011T060446Z-v1')
    bad=[path for path,sha in read(run/'input-freeze.json')['hashes'].items() if digest(path)!=sha]
    if bad:raise RuntimeError('Frozen input changed')
    if set(DEVELOPMENT)&set(VALIDATION):raise RuntimeError('Learning split overlaps')
    sources=read(run/'source-inputs.json')['samples'];same=[];missing=[]
    for row in sources:
        ident=row['id'];receipt=read(run/'feature-receipts'/f'{ident}.json')
        if digest(run/'features'/f'{ident}.npz')!=receipt['sha256']:raise RuntimeError('Source feature changed')
        packets=[read(run/'encoded-units'/p/f'{ident}.json') for p in ['proxy97','proxy100','proxy103']]
        for method in ['A4_AUDIO_NEURAL_ANCHOR','A2_AUDIO_ANCHOR']:
            pred=[read(run/'predictions'/method/p/f'{ident}.json') for p in ['proxy97','proxy100','proxy103']]
            equivalent=packets[0]==packets[1]==packets[2];equal=canonical(pred[0])==canonical(pred[1])==canonical(pred[2])
            same.append({'id':ident,'method':method,'same_discrete_input':equivalent,'same_complete_output_except_policy':equal})
            if equivalent and not equal:raise RuntimeError('Same discrete input changed prediction')
        for method in list(LEARNED)+HEURISTIC:
            for policy in ['none','proxy100']:
                path=run/'predictions'/method/policy/f'{ident}.json'
                if not path.exists():missing.append(str(path))
    freeze=read(run/'model-freeze.json')
    for r in freeze['models']:
        if digest(run/'models'/f"{r['method']}.npz")!=r['model_sha256'] or digest(run/'models'/f"{r['method']}.json")!=r['metadata_sha256']:raise RuntimeError('Model changed after fitting freeze')
    audits=[read(p) for p in (run/'worker-audit').glob('*.json')]
    forbidden=[p for a in audits for p in a.get('forbidden_reads',[])]
    if missing or forbidden:raise RuntimeError('Incomplete predictions or forbidden read')
    write(run/'completion-review.json',{'source_inputs':len(sources),'new_prediction_count':len(list((run/'predictions').glob('*/*/*.json'))),
          'input_hashes_unchanged':len(read(run/'input-freeze.json')['hashes']),
          'source_and_models_frozen_unchanged':True,'prior_implementations_unchanged':True,
          'song_split_disjoint':True,'development_songs':DEVELOPMENT,'validation_songs':VALIDATION,
          'validation_labels_read_during_training':False,'forbidden_reference_reads':forbidden,
          'same_layer_checks':same,'not_app_runtime_or_full_clock_validation':True})
    print('AUDITED',len(sources),flush=True)

if __name__=='__main__':main()
