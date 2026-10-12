"""Diagnostic true-clock dictionary, explicitly withholding interval labels."""
import argparse
from pathlib import Path
import time

import numpy as np

from .common import read,write,guard
from .proposals import load_events,unique_clocks
from .evidence import table
from .compose import predict

ORACLE_METHODS={'O_LOCAL':{'mode':'local'},'O_REGION_HOLD':{},
                'O_LOW_CHANGE_COST':{'change_penalty':.625},'O_HIGH_CHANGE_COST':{'change_penalty':2.5}}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1);a=p.parse_args();guard(a.run)
    for row in read(a.run/'evaluation-index.json')['rows'][a.shard::a.shards]:
        ident=row['id'];ref=read(a.run/'references'/f'{ident}.json');quarters=np.array(ref['quarters']);clocks=[]
        for s in ref['segments']:
            q=quarters[(quarters>=s['start_seconds'])&(quarters<s['end_seconds'])];period=60/s['quarter_bpm']
            if not len(q):continue
            phase=float((np.angle(np.exp(2j*np.pi*q/period).mean())*period/(2*np.pi))%period)
            clocks.append({'bpm':s['quarter_bpm'],'phase':phase,'provenance':'ORACLE_REFERENCE_CLOCK_DICTIONARY'})
        clocks=unique_clocks(clocks,4096)
        write(a.run/'oracle-banks'/f'{ident}.json',{'clocks':clocks,'true_interval_labels_supplied':False,
            'true_quarter_bpm_and_phase_supplied':True,'automatic_performance':False})
        tab=table(load_events(a.run/'events'/f'{ident}.npz'),clocks)
        for method,options in ORACLE_METHODS.items():
            pred=predict(tab,method,options)
            pred['oracle_dictionary']=True;pred['true_interval_labels_supplied']=False
            write(a.run/'oracle-predictions'/method/'none'/f'{ident}.json',pred)
        print('ORACLE_DIAGNOSTIC',ident,flush=True)


if __name__=='__main__':main()
