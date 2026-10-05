"""Audit every qualified reference against frozen observations and objective."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from .meter_objective_audit import (reference_problem,objective_arrays,score_path,ideal_observations)
from .meter_search import decode_meter,interpolate
from .reconstruct_cached import load_observations
from .probe_resources import digest


def agreement(gold,actual,end):
    g=[b for b in gold if 0<=b['q']<end]
    a=[b for b in actual if 0<=b['q']<end]
    matched=sum(any(abs(x['q']-y['q'])<1e-4 for y in a) for x in g)
    labels=sum(any(abs(x['q']-y['q'])<1e-4 and (x['n'],x['d'])==(y['n'],y['d']) for y in a) for x in g)
    return dict(reference_bars=len(g),predicted_bars=len(a),matching_boundaries=matched,
                matching_labeled_boundaries=labels,exact_boundaries=matched==len(g)==len(a),
                exact_labeled_boundaries=labels==len(g)==len(a))


def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--event-control',action='store_true')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    a.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((a.baseline/'predictions/manifest.json').read_text())
    record=dict(scope='oracle diagnostic, not automatic performance',rows=[],complete=False,
                baseline_manifest_sha256=digest(a.baseline/'predictions/manifest.json'),
                implementation_sha256={n:digest(Path(__file__).with_name(n)) for n in
                                       ('meter_objective_audit.py','run_objective_audit.py','meter_search.py')})
    for row in manifest['rows']:
        path=a.baseline/'evaluation'/(row['id']+'-reference.json')
        raw=json.loads(path.read_text())['map']
        result=dict(id=row['id'],reference_artifact_sha256=digest(path),source=row['source'])
        clock,gold,scope=reference_problem(raw)
        logits,_,structure=load_observations(row)
        result.update(scope=scope,conditions={})
        if a.event_control:
            from .meter_event import decode_meter as event_decode
            ideal_logits,ideal_head=ideal_observations(clock,gold,logits,structure)
            selected=event_decode(clock,ideal_logits,ideal_head)
            result['event_control_ideal_agreement']=agreement(gold,selected['bars'],clock[-1,0])
        for name,(observations,head) in [('actual',(logits,structure)),
                ('ideal',ideal_observations(clock,gold,logits,structure))]:
            arrays=objective_arrays(clock,observations,head)
            selected=decode_meter(clock,observations,head)
            selected_score=score_path(selected['bars'],arrays)
            expected=selected['score']*max(1,clock[-1,0])
            if abs(selected_score['total']-expected)>1e-6:
                raise AssertionError(('direct score does not reproduce DP',row['id'],name,selected_score['total'],expected))
            try:
                gold_score=score_path(gold,arrays);error=None
                if gold_score['total']>selected_score['total']+1e-6:
                    raise AssertionError(('DP missed higher-scoring gold',row['id'],name))
            except ValueError as exc:
                gold_score=None;error=str(exc)
            result['conditions'][name]=dict(representable=error is None,representation_error=error,
                gold_score=gold_score,selected_score=selected_score,
                gold_minus_selected=gold_score['total']-selected_score['total'] if gold_score else None,
                agreement=agreement(gold,selected['bars'],clock[-1,0]))
        record['rows'].append(result)
        (a.output/'results.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
        print(row['id'],json.dumps({k:dict(gap=round(v['gold_minus_selected'],3) if v['gold_minus_selected'] is not None else None,
            representable=v['representable'],**v['agreement']) for k,v in result['conditions'].items()}),flush=True)
    record['complete']=True
    (a.output/'results.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
