"""Source-only proposal/table/prediction workers; no evaluation imports."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import numpy as np

from .common import CONFIG,METHODS,read,write,digest,guard
from .proposals import load_events,generate
from .evidence import table,refine_episodes,seed_episodes
from .compose import predict,source_initial_unit


def save_table(path,tab):
    np.savez_compressed(path,**{k:v for k,v in tab.items() if k not in ['clocks']})


def load_table(run,ident,bank):
    with np.load(run/'tables'/bank/f'{ident}.npz',allow_pickle=False) as d:
        tab={k:d[k].copy() for k in d.files}
    tab['duration']=float(tab['duration'])
    tab['clocks']=read(run/'banks'/f'{ident}.json')[bank]
    return tab


def prepare_bank(run,ident):
    started=time.perf_counter();events=load_events(run/'events'/f'{ident}.npz')
    final=read(run/'final-banks'/f'{ident}.json')['clocks']
    banks=generate(events,final)
    base=table(events,banks['expanded'])
    refined,extra=refine_episodes(events,base)
    banks['expanded']=refined;banks['statistics']['episode_refit_proposals']=len(extra)
    banks['small']=refined[:CONFIG['small_budget']]
    write(run/'banks'/f'{ident}.json',banks)
    for name in ['expanded','unrefined','final','small']:
        tab=table(events,banks[name])
        path=run/'tables'/name/f'{ident}.npz';path.parent.mkdir(parents=True,exist_ok=True)
        save_table(path,tab)
        if name=='expanded':
            write(run/'seed-episodes'/f'{ident}.json',{'episodes':seed_episodes(tab)})
            write(run/'source-unit'/f'{ident}.json',source_initial_unit(tab))
    write(run/'bank-receipts'/f'{ident}.json',{'id':ident,'elapsed_seconds':time.perf_counter()-started,
          'counts':{name:len(banks[name]) for name in ['expanded','unrefined','final','small']},
          'bank_sha256':digest(run/'banks'/f'{ident}.json')})
    print('BANK',ident,round(time.perf_counter()-started,2),flush=True)


def predict_one(run,ident,policies=None,methods=None,out=None):
    started=time.perf_counter();policies=policies or ['none','proxy100'];methods=methods or list(METHODS)
    out=out or run/'predictions';tabs={}
    for method in methods:
        options=METHODS[method];bank=options.get('bank','expanded')
        if bank not in tabs:tabs[bank]=load_table(run,ident,bank)
        for policy in policies:
            # The extremes only verify the exact same-unit contract of M3.
            if policy in ['proxy95','proxy105'] and method!='M3_REGION_HOLD':continue
            packet=None if policy=='none' else read(run/'encoded-units'/policy/f'{ident}.json')
            prediction=predict(tabs[bank],method,options,packet)
            prediction['policy']=policy
            write(out/method/policy/f'{ident}.json',prediction)
    print('PREDICT',ident,round(time.perf_counter()-started,2),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['banks','predict'],required=True)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1)
    p.add_argument('--ids',nargs='*');a=p.parse_args();guard(a.run)
    rows=read(a.run/'source-inputs.json')['samples']
    ids=[r['id'] for r in rows if not a.ids or r['id'] in a.ids][a.shard::a.shards]
    opened=[];forbidden=[];active=[False]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        s=args[0].decode() if isinstance(args[0],bytes) else args[0]
        mode=args[1] if isinstance(args[1],str) else ''
        if any(v in mode for v in 'wax+'):return
        if Path(s).suffix not in ['.json','.npz','.gz','.wav']:return
        opened.append(s)
        if any(v in s.lower() for v in ['/references/','evaluation','catalog.json','raw-proxies','oracle-banks','acceptance.json']):
            forbidden.append(s);raise RuntimeError('Forbidden reference read in source-only worker')
    sys.addaudithook(audit);active[0]=True
    try:
        for ident in ids:
            if a.stage=='banks':
                if not (a.run/'bank-receipts'/f'{ident}.json').exists():prepare_bank(a.run,ident)
            else:predict_one(a.run,ident,['none','proxy100','proxy95','proxy105'])
    finally:active[0]=False
    write(a.run/'worker-audit'/f'{a.stage}-{a.shard}.json',{'actual_read_hook':True,'forbidden_reads':forbidden,
         'opened_data_paths':sorted(set(opened)),'ids':ids,'not_an_OS_sandbox_claim':True})
    guard(a.run)


if __name__=='__main__':main()
