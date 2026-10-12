"""Reference-informed sensor diagnosis; never an input to the predictor."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from experiments.metronome_benchmark_v1.metrics import event_f1
from experiments.variable_clock_composition_v1.evaluate import nearest,inside
from .common import read,write

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    sources={r['id']:r for r in read(run/'source-inputs.json')['samples']};result=[]
    for row in read(run/'evaluation-index.json')['rows']:
        if row['role']=='constructed_control':continue
        ident=row['id'];ref=read(run/'references'/f'{ident}.json')
        original=read(run/'references'/f'{ident}.original.json')
        with np.load(sources[ident]['events_path']) as z:
            bt=z['times'];dt=z['downbeat_times'];dw=z['downbeat_weights']
        bt=bt[inside(bt,ref['support'])];keep=inside(dt,ref['support']);dt,dw=dt[keep],dw[keep]
        q=np.array(ref['quarters']);bars=np.array(original.get('downbeats_seconds',original.get('downbeat_times_seconds',[])))
        bars=bars[inside(bars,ref['support'])]
        quarter_fraction=float(np.mean(nearest(dt,q)<=.07)) if len(dt) else None
        result.append({'id':ident,'title':row['title'],'role':row['role'],
                       'beat_quarter_f1_70':event_f1(bt,q,.07),
                       'downbeat_bar_f1_70':event_f1(dt,bars,.07),
                       'downbeat_events':len(dt),'reference_bars':len(bars),
                       'downbeat_on_quarter_fraction':quarter_fraction,
                       'reference_informed_not_automatic_prediction':True})
    write(run/'sensor-observability.json',{'rows':result,'predictor_must_not_read_this':True})
    for r in result:
        if r['id'] in ['r002','r008','r010']:
            print(r['id'],'bar F1',round(r['downbeat_bar_f1_70']['f1'],4),
                  'quarter aligned downbeats',r['downbeat_on_quarter_fraction'],flush=True)

if __name__=='__main__':main()
