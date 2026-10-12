"""Completion evidence requested as part of this research experiment."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .common import METHODS,PRIOR,read,write,digest,guard
from experiments.variable_clock_composition_v1.common import guard as prior_guard

def canonical(pred):
    p=dict(pred);p.pop('policy',None)
    return json.dumps(p,sort_keys=True,ensure_ascii=False,allow_nan=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run);prior_guard(PRIOR)
    bad=[path for path,sha in read(run/'input-freeze.json')['hashes'].items() if digest(path)!=sha]
    if bad:raise RuntimeError('Frozen inputs changed: '+str(bad))
    ids=sorted(p.stem for p in (run/'predictions/R2_ROLES_BARS/proxy100').glob('*.json'))
    pairs=[];missing=[]
    for ident in ids:
        pred=[read(run/'predictions/R2_ROLES_BARS'/policy/f'{ident}.json') for policy in ['proxy97','proxy100','proxy103']]
        packets=[read(run/'encoded-units'/policy/f'{ident}.json') for policy in ['proxy97','proxy100','proxy103']]
        same_input=packets[0]==packets[1]==packets[2]
        same_output=canonical(pred[0])==canonical(pred[1])==canonical(pred[2])
        pairs.append({'id':ident,'same_discrete_input':same_input,'same_complete_prediction_except_policy_label':same_output})
        if same_input and not same_output:raise RuntimeError('Same-layer tap contract failed')
        for method in METHODS:
            for policy in ['none','proxy100']:
                path=run/'predictions'/method/policy/f'{ident}.json'
                if not path.exists():missing.append(str(path))
        receipt=read(run/'source-receipts'/f'{ident}.json')
        if digest(run/'tables'/f'{ident}.npz')!=receipt['table_sha256'] or digest(run/'states'/f'{ident}.json')!=receipt['states_sha256']:
            raise RuntimeError('Prepared source state changed')
    audits=[read(p) for p in (run/'worker-audit').glob('*.json')]
    forbidden=[p for d in audits for p in d['forbidden_reads']]
    if missing or forbidden:raise RuntimeError('Incomplete predictions or forbidden reference read')
    write(run/'completion-review.json',{'predicted_inputs':ids,'prediction_count':len(list((run/'predictions').glob('*/*/*.json'))),
          'expected_methods':list(METHODS),'missing_predictions':missing,'source_read_audits':len(audits),
          'forbidden_reference_reads':forbidden,'same_layer_checks':pairs,
          'input_hashes_unchanged':len(read(run/'input-freeze.json')['hashes']),
          'new_and_prior_code_frozen_unchanged':True,'app_runtime_and_model_replacement':False,
          'actual_human_taps_measured':False})
    print('AUDITED',len(ids),'inputs',flush=True)

if __name__=='__main__':main()
