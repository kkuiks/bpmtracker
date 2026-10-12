from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
import copy
import numpy as np
from .common import POLICIES,METHODS,read,write,guard,digest,stamp
from .source import prepare
from .core import fit

def load(row):
    with np.load(row['events_path'],allow_pickle=False) as data:events={k:data[k].copy() for k in data.files}
    family=read(row['family_path']) if row.get('family_path') else None
    if abs(float(events['duration'])-row['duration_seconds'])>1e-6:raise RuntimeError('Source geometry changed')
    return events,family

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--stage',choices=['prepare','predict'],required=True)
    parser.add_argument('--shard',type=int,default=0);parser.add_argument('--shards',type=int,default=1)
    parser.add_argument('--ids',nargs='*');parser.add_argument('--methods',nargs='*')
    args=parser.parse_args();run=args.run;guard(run)
    rows=read(run/'source-inputs.json')['samples'][args.shard::args.shards]
    if args.ids:rows=[r for r in rows if r['id'] in args.ids]
    opened=[];forbidden=[];active=[True]
    def hook(event,arguments):
        if event!='open' or not active[0] or not isinstance(arguments[0],(str,bytes)):return
        path=arguments[0].decode() if isinstance(arguments[0],bytes) else arguments[0]
        mode=arguments[1] if isinstance(arguments[1],str) else ''
        if any(c in mode for c in 'wax+'):return
        if Path(path).suffix in ['.json','.npz']:
            opened.append(path)
            if any(k in path for k in ['/references/','evaluation-index','catalog.json','metrics.json','raw-proxies','acceptance.json','/tables/','/banks/']):
                forbidden.append(path);raise RuntimeError('Forbidden source worker input')
    sys.addaudithook(hook)
    for row in rows:
        start=time.perf_counter();events,family=load(row);ident=row['id']
        if args.stage=='prepare':
            target=run/'prepared-source'/(ident+'.json')
            if target.exists():raise RuntimeError('Prepared source already exists')
            prepared=prepare(events,family);write(target,prepared)
            print('SOURCE',ident,'pulses',len(prepared['pulses']),'bars',len(prepared['bars']),
                  'root',prepared.get('audio_initial_pulse_bpm'),'initial_end',prepared.get('adaptive_initial_evidence_end'),flush=True)
        else:
            prepared=read(run/'prepared-source'/(ident+'.json'));cache={}
            for policy in POLICIES:
                packet=read(run/'encoded-units'/policy/(ident+'.json'));key=packet.get('unit_id')
                if key not in cache:
                    cache[key]={}
                    for method in (args.methods or read(run/'protocol.json').get('selected_methods',list(METHODS))):
                        beginning=time.perf_counter()
                        def progress(depth,children,best_events):
                            print('SEARCH',ident,method,'depth',depth,'children',children,'best_events',best_events,
                                  'seconds',round(time.perf_counter()-beginning,2),flush=True)
                        cache[key][method]=fit(events,prepared,packet,method,progress)
                        print('MAP',ident,method,'unit',key,'events',len(cache[key][method].get('events',[])),
                              'seconds',round(time.perf_counter()-beginning,2),flush=True)
                for method,result in cache[key].items():
                    target=run/'predictions'/method/policy/(ident+'.json')
                    if target.exists():raise RuntimeError('Prediction overwrite forbidden')
                    output=copy.deepcopy(result);output['policy']=policy;write(target,output)
        print(args.stage.upper(),ident,round(time.perf_counter()-start,2),flush=True)
    active[0]=False
    tag='-'.join(args.ids or [str(args.shard)])+'-'+('-'.join(args.methods) if args.methods else 'all')
    write(run/'worker-audit'/(args.stage+'-'+tag+'.json'),{'at_utc':stamp(),'ids':[r['id'] for r in rows],
            'actual_read_hook':True,'opened_data_paths':sorted(set(opened)),'forbidden_reads':forbidden,
            'old_window_tables_and_banks_not_used':True})
    if args.stage=='prepare':
        write(run/'source-before-tap-freeze'/f'{tag}.json',{'files':{str(run/'prepared-source'/(r['id']+'.json')):digest(run/'prepared-source'/(r['id']+'.json')) for r in rows}})
    guard(run)

if __name__=='__main__':main()
