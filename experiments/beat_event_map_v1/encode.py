from __future__ import annotations
import argparse
from pathlib import Path
from .common import POLICIES,read,write,guard,digest,stamp
from .source import encode

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);args=parser.parse_args();run=args.run;guard(run)
    frozen={}
    for p in (run/'source-before-tap-freeze').glob('*.json'):frozen.update(read(p)['files'])
    if any(digest(p)!=sha for p,sha in frozen.items()):raise RuntimeError('Source preparation changed before tap')
    rows=read(run/'evaluation-index.json')['rows'];audit=[]
    for row in rows:
        ident=row['id'];prepared=read(run/'prepared-source'/(ident+'.json'));ref=read(row['reference_path']);packets=[]
        for policy in POLICIES:
            ratio=int(policy.removeprefix('proxy'))/100
            packet=encode(prepared,ref['initial_bpm']*ratio);packets.append(packet)
            write(run/'encoded-units'/policy/(ident+'.json'),packet)
        audit.append({'id':ident,'same_unit_across_three_proxies':packets[0]==packets[1]==packets[2],
                      'unit_ids':[p.get('unit_id') for p in packets],'tap_values_not_retained':True})
    write(run/'tap-encoder-audit.json',{'at_utc':stamp(),'rows':audit,'source_files_frozen_before_tap':len(frozen),
                                     'initial_unit_only_not_fine_bpm_or_meter_or_phase':True,'measured_human_taps':False})
    print('ENCODED',len(rows),'same units',sum(r['same_unit_across_three_proxies'] for r in audit),flush=True)

if __name__=='__main__':main()
