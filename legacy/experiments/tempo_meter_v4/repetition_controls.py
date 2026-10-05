"""Known-correspondence upper-bound controls; no automatic-repeat claim."""
import argparse
import json
from pathlib import Path
import numpy as np
from .fixtures import fixture
from .bar_structure import decode
from .repetition import messages,consistency
from .calibrate_controls import error


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    obs,clock,gold=fixture([(4,4)]*16)
    t=obs['times'];first=t<16.3;obs['down'][first]*=.3
    for q in np.arange(1,32,4):
        bump=.40*np.exp(-.5*((t-(.3+q*.5))/.02)**2)
        obs['down']=np.maximum(obs['down'],bump)
    links=[dict(a=.3+q*.5,b=.3+(q+32)*.5,weight=1.) for q in np.arange(2,32,4)]
    baseline=decode(clock,obs);rows=[]
    for strength in (0.,.1,1.,4.,8.):
        params=dict(repeat_strength=strength)
        best=baseline;best_score=best['base_score']-strength*consistency(clock,best['bars'],links)
        for _ in range(3):
            candidate=decode(clock,obs,params,repeat_targets=messages(clock,best['bars'],links))
            score=candidate['base_score']-strength*consistency(clock,candidate['bars'],links)
            if score<=best_score+1e-8:break
            best,best_score=candidate,score
        rows.append(dict(strength=strength,wrong_labeled_bar_events=error(gold,best['bars']),score=best_score))
    result=dict(scope='constructed weak-first/clear-second repeated section; exact links are diagnostic only',rows=rows,
                baseline_error=error(gold,baseline['bars']),automatic_correspondence_accuracy_measured=False)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
