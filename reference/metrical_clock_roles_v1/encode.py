"""Discard numeric +/-3% proxy values after discrete initial-role encoding."""
import argparse
from pathlib import Path
from .common import CONFIG,read,write,guard
from .decode import layer

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--ids',nargs='*');a=p.parse_args();guard(a.run)
    receipt=[]
    for row in read(a.run/'evaluation-index.json')['rows']:
        ident=row['id']
        if a.ids and ident not in a.ids:continue
        source=read(a.run/'source-unit'/f'{ident}.json');ref=read(a.run/'references'/f'{ident}.json')
        enc=[]
        for policy,factor in [('proxy97',.97),('proxy100',1.),('proxy103',1.03)]:
            raw=ref['initial_bpm']*factor
            packet={**source,'unit_index':int(layer(raw,source['base_bpm'],CONFIG)) if source['available'] else None}
            enc.append(packet);write(a.run/'encoded-units'/policy/f'{ident}.json',packet)
            write(a.run/'raw-proxies'/policy/f'{ident}.json',{'bpm':raw,'reference_derived_not_human':True})
        receipt.append({'id':ident,'same_discrete_input':enc[0]==enc[1]==enc[2],'available':source['available'],
                        'source_unit':source,'encoded_unit_index':enc[1]['unit_index']})
    write(a.run/'encoder-receipts'/f'{receipt[0]["id"] if receipt else "empty"}.json',
          {'rows':receipt,'numeric_proxy_not_read_by_predictor':True,'no_meter_or_phase_input':True})
    print('ENCODED',len(receipt),flush=True)

if __name__=='__main__':main()
