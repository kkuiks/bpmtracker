from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
import copy
import numpy as np
from .common import POLICIES,read,write,guard
from .core import prepare_source,fit

def load(row):
    with np.load(row['events_path'],allow_pickle=False) as data:events={k:data[k].copy() for k in data.files}
    with np.load(row['table_path'],allow_pickle=False) as data:table={k:data[k].copy() for k in data.files}
    bank=read(row['bank_path'])['expanded']
    family=read(row['family_path']) if row.get('family_path') else None
    if abs(float(events['duration'])-row['duration_seconds'])>1e-6:raise RuntimeError('Source geometry mismatch')
    return events,table,bank,family

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--stage',choices=['prepare','predict'],required=True)
    parser.add_argument('--shard',type=int,default=0);parser.add_argument('--shards',type=int,default=1)
    args=parser.parse_args();guard(args.run)
    rows=read(args.run/'source-inputs.json')['samples'][args.shard::args.shards]
    opened=[];forbidden=[];active=[False]
    def hook(event,arguments):
        if event!='open' or not active[0] or not isinstance(arguments[0],(str,bytes)):return
        value=arguments[0].decode() if isinstance(arguments[0],bytes) else arguments[0]
        mode=arguments[1] if isinstance(arguments[1],str) else ''
        if any(c in mode for c in 'wax+'):return
        if Path(value).suffix in ['.json','.npz']:
            opened.append(value)
            if any(s in value for s in ['/references/','evaluation-index','catalog.json','raw-proxies','acceptance.json']):
                forbidden.append(value);raise RuntimeError('Reference read in source map worker')
    sys.addaudithook(hook);active[0]=True
    for row in rows:
        start=time.perf_counter();ident=row['id'];events,table,bank,family=load(row)
        if args.stage=='prepare':
            target=args.run/'prepared-source'/(ident+'.json')
            if not target.exists():write(target,prepare_source(events,table,bank,family))
        else:
            prepared=read(args.run/'prepared-source'/(ident+'.json'));cache={}
            for policy in POLICIES:
                packet=read(args.run/'encoded-units'/policy/(ident+'.json'))
                key=packet.get('unit_id')
                if key not in cache:
                    cache[key]={}
                    for method,changes in [('C0_CONSTANT_MAP',False),('C1_CONTINUOUS_MAP',True)]:
                        cache[key][method]=fit(events,table,bank,prepared,packet,changes)
                for method,result in cache[key].items():
                    output=copy.deepcopy(result);output.update(policy=policy,method=method)
                    write(args.run/'predictions'/method/policy/(ident+'.json'),output)
        print(args.stage.upper(),ident,round(time.perf_counter()-start,2),flush=True)
    active[0]=False
    write(args.run/'worker-audit'/f'{args.stage}-{args.shard}.json',{'ids':[r['id'] for r in rows],
          'actual_read_hook':True,'opened_data_paths':sorted(set(opened)),'forbidden_reads':forbidden})
    guard(args.run)

if __name__=='__main__':main()
