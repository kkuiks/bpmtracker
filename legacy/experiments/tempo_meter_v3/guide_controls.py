"""Replay only discrete guide selection from frozen, audio-derived candidates.

No clock, phase, change boundary or acoustic score is refitted. This is exactly
the selector used by the analyzer, including binary and compound pulse families.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np
from .clock_search import select_pulse_level
from .probe_resources import digest


def map_hash(value):
    value=deepcopy(value);value.pop('analysis_condition',None)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    manifest=json.loads(a.manifest.read_text())
    if not manifest['complete']:raise ValueError('complete predictions required')
    a.output.mkdir(parents=True);all_results=[];unhinted=[]
    for index,row in enumerate(manifest['rows']):
        folder=Path(row['selected']['path']).parent
        path=folder/'candidate-bank.json';stored=json.loads(path.read_text())
        bank=[]
        for item in stored:
            knots=item['prediction']['map']['clock_knots']
            bank.append(dict(name=item['name'],joint_score=item['score'],clock=np.array([[k['pulse'],k['source_seconds']] for k in knots]),prediction=item['prediction']))
        hint=row['initial_bpm'];results=[]
        for label,value in [('none',None),('minus_one',hint-1),('exact',hint),('plus_one',hint+1),('half',hint/2),('double',hint*2)]:
            chosen,decision=select_pulse_level(bank,value);candidate=chosen[0]
            record=dict(condition=label,guide=value,selected=candidate['name'],musical_map_sha256=map_hash(candidate['prediction']['map']),decision=decision)
            results.append(record)
            if value is None:
                prediction=deepcopy(candidate['prediction']);prediction['map']['analysis_condition']='unhinted'
                prediction['diagnostics'].update(initial_bpm=None,pulse_level_selection=decision,alternative_rank=0)
                output=a.output/f'{index:02d}-unhinted.json';output.write_text(json.dumps(prediction,indent=2)+'\n')
                unhinted.append(dict(id=row['id'],title=row['title'],source=row['source'],selected=dict(path=str(output.resolve()),sha256=digest(output))))
        by_condition={r['condition']:r for r in results}
        selected=json.loads(Path(row['selected']['path']).read_text())
        assert map_hash(selected['map'])==by_condition['exact']['musical_map_sha256'],'selector replay differs from real inference'
        stable=len({by_condition[c]['musical_map_sha256'] for c in ('minus_one','exact','plus_one')})==1
        all_results.append(dict(id=row['id'],candidate_bank_sha256=digest(path),nearby_hint_map_identical=stable,conditions=results))
    (a.output/'sensitivity.json').write_text(json.dumps(dict(complete=True,clocks_refitted=False,rows=all_results),indent=2)+'\n')
    (a.output/'manifest.json').write_text(json.dumps(dict(complete=True,references_available_to_runner=False,condition='unhinted_exact_selector_replay_no_new_inference',rows=unhinted),indent=2)+'\n')
    print(json.dumps({r['id']:r['nearby_hint_map_identical'] for r in all_results}))

if __name__=='__main__':main()
