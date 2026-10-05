"""Repeat-strength validation on a separate meter and an adverse riff link."""
import argparse
import json
from pathlib import Path
import numpy as np
from .fixtures import fixture
from .bar_structure import decode
from .repetition import messages,consistency
from .calibrate_controls import error


def solve(obs,clock,links,strength):
    parameters=dict(repeat_strength=strength)
    baseline=decode(clock,obs,parameters)
    candidates=[baseline,*baseline.get('alternatives',[])]
    best=max(candidates,key=lambda c:c['base_score']-strength*consistency(clock,c['bars'],links))
    score=best['base_score']-strength*consistency(clock,best['bars'],links)
    for _ in range(3):
        result=decode(clock,obs,parameters,repeat_targets=messages(clock,best['bars'],links))
        alternatives=[result,*result.get('alternatives',[])]
        candidate=max(alternatives,key=lambda c:c['base_score']-strength*consistency(clock,c['bars'],links))
        newscore=candidate['base_score']-strength*consistency(clock,candidate['bars'],links)
        if newscore<=score+1e-8:break
        best,score=candidate,newscore
    return best


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    reports=[]
    for meter in [(4,4),(3,4)]:
        obs,clock,gold=fixture([meter]*16);length=4*meter[0]/meter[1];half=8*length
        mask=obs['times']<.3+half*.5;obs['down'][mask]*=.3
        for q in np.arange(1,half,length):
            obs['down']=np.maximum(obs['down'],.4*np.exp(-.5*((obs['times']-(.3+q*.5))/.02)**2))
        edges=[dict(a=.3+q*.5,b=.3+(q+half)*.5,weight=1.) for q in np.arange(1.5,half,length)]
        for strength in [0.,.1,1.,4.,8.]:
            result=solve(obs,clock,edges,strength)
            reports.append(dict(case='weak_repeat_'+str(meter),strength=strength,wrong_events=error(gold,result['bars'])))
    obs,clock,gold=fixture([(4,4)]*16)
    false_edges=[dict(a=.3+q*.5,b=.3+(q+1.75)*.5,weight=1.) for q in np.arange(2,48,4)]
    for strength in [4.,8.]:
        result=solve(obs,clock,false_edges,strength)
        reports.append(dict(case='adverse_nonbar_riff_links',strength=strength,wrong_events=error(gold,result['bars'])))
    passing=[s for s in [4.,8.] if all(r['wrong_events']==0 for r in reports if r['strength']==s)]
    value=dict(rows=reports,selected=min(passing) if passing else 0.,validation_pass=bool(passing),
        oracle_links_are_diagnostic=True,automatic_links_not_yet_evaluated=True)
    a.output.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))


if __name__=='__main__':main()
