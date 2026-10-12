"""Reference-derived +/-3% tap proxies: numeric values never reach learners."""
import argparse
from pathlib import Path
from .common import read,write,guard,unit_index
from .worker import arrays

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();guard(a.run);rows=[]
    for row in read(a.run/'evaluation-index.json')['rows']:
        ident=row['id'];feat=arrays(a.run/'features'/f'{ident}.npz');ref=read(a.run/'references'/f'{ident}.json')
        available=int(feat['anchor_index'])>=0;base=float(feat['anchor_base_bpm']);packets=[]
        for policy,factor in [('proxy97',.97),('proxy100',1.),('proxy103',1.03)]:
            value=ref['initial_bpm']*factor
            packet={'available':available,'unit_index':unit_index(value,base) if available else None,
                    'source_anchor_index':int(feat['anchor_index'])}
            packets.append(packet);write(a.run/'encoded-units'/policy/f'{ident}.json',packet)
            write(a.run/'raw-proxies'/policy/f'{ident}.json',{'bpm':value,'reference_derived_not_human_tap':True})
        rows.append({'id':ident,'same_discrete_input':packets[0]==packets[1]==packets[2],
                     'available':available,'indices':[p['unit_index'] for p in packets]})
    write(a.run/'encoder-receipt.json',{'rows':rows,'source_features_complete_before_proxies':True})
    print('ENCODED',len(rows),flush=True)

if __name__=='__main__':main()
