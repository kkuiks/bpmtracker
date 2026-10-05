"""Choose shared decoder settings on held-out learning compositions only.

This isolates meter reconstruction using label-derived clocks for calibration.
It is not an end-to-end audio validation score or a primary21 performance claim.
"""
import argparse
import itertools
import json
from pathlib import Path
import sys
import numpy as np
from .meter_calibrated import decode_meter,interpolate
from .structure_compare import predict
from .probe_resources import digest


def nearest(a,b,tolerance=.07):
    a=sorted(a);b=sorted(b);i=j=matched=0
    while i<len(a) and j<len(b):
        if abs(a[i]-b[j])<=tolerance:matched+=1;i+=1;j+=1
        elif a[i]<b[j]:i+=1
        else:j+=1
    return 2*matched/(len(a)+len(b)) if a or b else 1.


def assess(clock,bars,label):
    lo,hi=label['support'];starts=interpolate(clock,np.array([b['q'] for b in bars]))
    candidates=[(float(t),b) for t,b in zip(starts,bars) if lo<=t<hi]
    truth=[t for t in label['bars'] if lo<=t<hi]
    bar_score=nearest(truth,[t for t,b in candidates])
    correct=0
    for t in truth:
        if not candidates:continue
        predicted=min(candidates,key=lambda x:abs(x[0]-t))
        m=next((m for m in reversed(label['meter']) if m['time_seconds']<=t+1e-8),label['meter'][0])
        if abs(predicted[0]-t)<=.07 and (predicted[1]['n'],predicted[1]['d'])==(m['numerator'],m['denominator']):correct+=1
    predicted_changes=[]
    for (ta,a),(tb,b) in zip(zip(starts,bars),list(zip(starts,bars))[1:]):
        if (a['n'],a['d'])!=(b['n'],b['d']) and lo<tb<hi:predicted_changes.append(float(tb))
    actual=[m['time_seconds'] for a,m in zip(label['meter'],label['meter'][1:]) if (a['numerator'],a['denominator'])!=(m['numerator'],m['denominator']) and lo<m['time_seconds']<hi]
    change_score=nearest(actual,predicted_changes,.5)
    return dict(bar_f1=bar_score,meter_bar_fraction=correct/max(1,len(truth)),change_f1=change_score,
                objective=.3*bar_score+.5*correct/max(1,len(truth))+.2*change_score)


def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',required=True);p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--learning',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mert-cache',type=Path,default=Path('data/cache/tempo-meter-v3/mert-v2'));a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    import torch
    torch.set_num_threads(4)
    rows=[r for r in json.loads(a.learning.read_text())['rows'] if r['split']=='validation' and r['labels']['meter_known']]
    prepared=[]
    for row in rows:
        with np.load(row['cache']) as z:features=z['features'];logits=z['logits']
        extra=None
        if a.arm=='B':
            with np.load(a.mert_cache/(row['audio_sha256']+'.npz')) as z:extra=z['features']
        structural=predict(features,logits,a.checkpoint,extra)
        beats=np.array(sorted(set(row['labels']['beats'])),float)
        if len(beats)<4:continue
        clock=np.column_stack([np.arange(len(beats),dtype=float),beats])
        prepared.append((row,clock,logits,structural))
    configs=[dict(style='log_odds',category_strength=1.,change_cost=4.)]
    configs += [dict(style='softplus',category_strength=s,change_cost=c) for s,c in itertools.product((1.,3.,10.),(4.,8.,12.))]
    results=[]
    for config in configs:
        scores=[]
        for row,clock,logits,structural in prepared:
            prediction=decode_meter(clock,logits,structural,**config)
            scores.append(dict(id=row['id'],**assess(clock,prediction['bars'],row['labels'])))
        score=float(np.mean([s['objective'] for s in scores]));results.append(dict(config=config,objective=score,rows=scores))
        print(a.arm,config,round(score,4),flush=True)
    chosen=max(results,key=lambda r:r['objective'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(arm=a.arm,calibration_scope='held-out learning labels; reference-clock meter diagnostic only',
        primary21_used=False,checkpoint_sha256=digest(a.checkpoint),selected=chosen['config'],results=results),indent=2)+'\n')


if __name__=='__main__':main()
