"""Select common transition parameters on separate constructed control sets."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from .fixtures import fixture
from .bar_structure import decode


def error(gold,actual):
    keys=lambda rows:{(round(b['q'],5),b['n'],b['d']) for b in rows if b['q']>=0}
    g,a=keys(gold),keys(actual)
    return len(g-a)+len(a-g)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    implementation={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    training=[('four_missing',dict(signatures=[(4,4)]*16,missing_bars=range(5,10))),
              ('four_short',dict(signatures=[(4,4)]*4+[(2,4)]+[(4,4)]*4))]
    validation=[('three_missing',dict(signatures=[(3,4)]*14,missing_bars=range(4,8))),
                ('compound',dict(signatures=[(6,8)]*10)),('odd',dict(signatures=[(7,8)]*10)),
                ('long',dict(signatures=[(31,4)]*3)),
                ('short_other',dict(signatures=[(3,4)]*4+[(1,4)]+[(3,4)]*4))]
    candidates=[]
    for cost in [2.,4.,8.,12.]:
        params=dict(meter_change_cost=cost,rhythm_change_cost=1.,weak_quarter_cost=.12,
                    tempo_change_cost=8.,segmentation_penalty=.025,repeat_strength=.1)
        scores=[]
        for name,kwargs in training:
            obs,clock,gold=fixture(**kwargs);actual=decode(clock,obs,params)['bars']
            scores.append(dict(id=name,wrong_events=error(gold,actual)))
        candidates.append(dict(parameters=params,training=scores,total=sum(x['wrong_events'] for x in scores)))
    selected=min(candidates,key=lambda c:(c['total'],c['parameters']['meter_change_cost']))
    checked=[]
    for name,kwargs in validation:
        obs,clock,gold=fixture(**kwargs);actual=decode(clock,obs,selected['parameters'])['bars']
        checked.append(dict(id=name,wrong_events=error(gold,actual)))
    value=dict(implementation_sha256=implementation,role='constructed-observation grammar calibration, not actual-recording model validation',
        candidates=candidates,selected=selected['parameters'],validation=checked,
        validation_pass=all(x['wrong_events']==0 for x in checked),real_evaluation_maps_read=False)
    a.output.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value,indent=2))


if __name__=='__main__':main()
