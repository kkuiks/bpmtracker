"""Source-only original PCM feature extraction, with reference-read rejection."""
import argparse
from pathlib import Path
import sys,time
import numpy as np
from .common import read,write,digest,guard
from .features import source_table

def arrays(path):
    with np.load(path,allow_pickle=False) as d:return {k:d[k].copy() for k in d.files}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--shard',type=int,default=0)
    p.add_argument('--shards',type=int,default=1);p.add_argument('--ids',nargs='*');a=p.parse_args();guard(a.run)
    rows=[r for r in read(a.run/'source-inputs.json')['samples'] if not a.ids or r['id'] in a.ids][a.shard::a.shards]
    opened=[];active=[False];forbidden=[]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        path=args[0].decode() if isinstance(args[0],bytes) else args[0]
        mode=args[1] if isinstance(args[1],str) else ''
        if any(c in mode for c in 'wax+'):return
        if Path(path).suffix not in ['.json','.npz','.wav','.flac','.mp3']:return
        opened.append(path)
        if any(s in path.lower() for s in ['/references/','evaluation-index','catalog.json','labels','raw-proxies','acceptance.json']):
            forbidden.append(path);raise RuntimeError('Reference read in source feature worker')
    sys.addaudithook(audit);active[0]=True
    try:
        for row in rows:
            ident=row['id'];started=time.perf_counter();bank=read(row['bank_path'])['expanded']
            result,meta=source_table(row,bank,arrays(row['table_path']),arrays(row['sensor_path']),arrays(row['events_path']))
            target=a.run/'features'/f'{ident}.npz';target.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(target,**result)
            write(a.run/'feature-receipts'/f'{ident}.json',{'id':ident,**meta,'sha256':digest(target),
                    'elapsed_seconds':time.perf_counter()-started,'anchor_available':int(result['anchor_index'])>=0,
                    'anchor_base_bpm':float(result['anchor_base_bpm']),'anchor_time':float(result['anchor_time'])})
            print('FEATURES',ident,meta['windows'],round(time.perf_counter()-started,2),flush=True)
    finally:active[0]=False
    write(a.run/'worker-audit'/f'features-{a.shard}.json',{'actual_read_hook':True,'forbidden_reads':forbidden,
              'opened_data_paths':sorted(set(opened)),'not_OS_sandbox':True})
    guard(a.run)

if __name__=='__main__':main()
