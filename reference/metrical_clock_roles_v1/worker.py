"""Source-only preparation/prediction with an actual read audit hook."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
import numpy as np
from .common import CONFIG,METHODS,read,write,guard,digest
from .evidence import build
from .decode import predict

def load_array(path):
    with np.load(path,allow_pickle=False) as d:return {k:d[k].copy() for k in d.files}

def load_table(run,ident):
    tab=load_array(run/'tables'/f'{ident}.npz');meta=read(run/'states'/f'{ident}.json')
    return {**tab,**meta,'duration':float(tab['duration'])}

def prepare_one(run,row):
    started=time.perf_counter();ident=row['id'];clocks=read(row['bank_path'])['expanded']
    tab=build(load_array(row['events_path']),load_array(row['sensor_path']),clocks)
    write(run/'states'/f'{ident}.json',{k:tab[k] for k in ['pulse_states','joint_states','source_unit','statistics']})
    out=run/'tables'/f'{ident}.npz';out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out,**{k:tab[k] for k in ['time','duration','beat_score','quality','bar_score','bar_phase','information']})
    write(run/'source-unit'/f'{ident}.json',tab['source_unit'])
    write(run/'source-receipts'/f'{ident}.json',{'id':ident,'elapsed_seconds':time.perf_counter()-started,
          'statistics':tab['statistics'],'source_unit':tab['source_unit'],
          'table_sha256':digest(out),'states_sha256':digest(run/'states'/f'{ident}.json')})
    print('PREPARED',ident,round(time.perf_counter()-started,2),tab['statistics'],flush=True)

def predict_one(run,ident,methods=None,policies=None):
    started=time.perf_counter();tab=load_table(run,ident)
    for method in methods or METHODS:
        for policy in policies or ['none','proxy100','proxy97','proxy103']:
            if policy in ['proxy97','proxy103'] and method!='R2_ROLES_BARS':continue
            packet=None if policy=='none' else read(run/'encoded-units'/policy/f'{ident}.json')
            pred=predict(tab,method,METHODS[method],packet)
            pred['policy']=policy;write(run/'predictions'/method/policy/f'{ident}.json',pred)
    print('PREDICTED',ident,round(time.perf_counter()-started,2),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['prepare','predict'],required=True);p.add_argument('--ids',nargs='*')
    p.add_argument('--methods',nargs='*');p.add_argument('--policies',nargs='*')
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1);a=p.parse_args();guard(a.run)
    rows=[r for r in read(a.run/'source-inputs.json')['samples'] if not a.ids or r['id'] in a.ids][a.shard::a.shards]
    opened=[];forbidden=[];active=[False]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        s=args[0].decode() if isinstance(args[0],bytes) else args[0]
        mode=args[1] if isinstance(args[1],str) else ''
        if any(v in mode for v in 'wax+'):return
        if Path(s).suffix not in ['.json','.npz','.wav']:return
        opened.append(s)
        if any(v in s.lower() for v in ['/references/','evaluation-index','catalog.json','raw-proxies',
                                     'sensor-observability','oracle-','acceptance.json']):
            forbidden.append(s);raise RuntimeError('Forbidden reference read in source worker')
    sys.addaudithook(audit);active[0]=True
    try:
        for row in rows:
            if a.stage=='prepare':prepare_one(a.run,row)
            else:predict_one(a.run,row['id'],a.methods,a.policies)
    finally:active[0]=False
    write(a.run/'worker-audit'/f'{a.stage}-{a.shard}-{rows[0]["id"] if rows else "empty"}.json',
          {'actual_read_hook':True,'opened_data_paths':sorted(set(opened)),'forbidden_reads':forbidden,
           'ids':[r['id'] for r in rows],'not_an_OS_sandbox_claim':True})
    guard(a.run)

if __name__=='__main__':main()
