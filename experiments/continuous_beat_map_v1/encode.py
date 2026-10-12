"""Evaluation-side tap simulation; only an opaque source-created unit reaches fit."""
from __future__ import annotations
import argparse
from pathlib import Path
from .common import POLICIES,read,write,guard,digest,stamp
from .core import encode_unit

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);args=parser.parse_args();guard(args.run)
    hashes={str(p):digest(p) for p in sorted((args.run/'prepared-source').glob('*.json'))}
    write(args.run/'source-before-tap-freeze.json',{'at_utc':stamp(),'files':hashes})
    records=[]
    for item in read(args.run/'evaluation-index.json')['rows']:
        ident=item['id'];prepared=read(args.run/'prepared-source'/(ident+'.json'));ref=read(item['reference_path'])
        for policy in POLICIES:
            tap=None if policy=='none' else ref['initial_bpm']*int(policy.removeprefix('proxy'))/100
            packet=encode_unit(prepared,tap)
            write(args.run/'encoded-units'/policy/(ident+'.json'),packet)
            records.append({'id':ident,'policy':policy,'unit_id':packet.get('unit_id'),'proxy':True,'measured_human_tap':False})
    write(args.run/'encoding-diagnostic.json',{'records':records,'candidates_prepared_before_any_tap':True})
    print('ENCODED',len(records),flush=True)

if __name__=='__main__':main()
