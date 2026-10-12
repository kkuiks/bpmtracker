"""Evaluation-derived tap proxies are encoded after every source bank is ready."""
import argparse
import math
from pathlib import Path

from .common import read,write,guard


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();guard(a.run)
    rows=read(a.run/'evaluation-index.json')['rows'];receipt=[]
    for row in rows:
        ident=row['id'];ref=read(a.run/'references'/f'{ident}.json')
        source=read(a.run/'source-unit'/f'{ident}.json')
        for policy,factor in [('proxy95',.95),('proxy100',1.),('proxy105',1.05)]:
            raw=ref['initial_bpm']*factor
            encoded={**source,'power':int(math.floor(math.log2(raw/source['base_bpm'])+.5)) if source['available'] else None}
            write(a.run/'encoded-units'/policy/f'{ident}.json',encoded)
            write(a.run/'raw-proxies'/policy/f'{ident}.json',{'bpm':raw,'reference_derived_diagnostic':True})
        enc=[read(a.run/'encoded-units'/p/f'{ident}.json') for p in ['proxy95','proxy100','proxy105']]
        receipt.append({'id':ident,'all_three_same_discrete_input':enc[0]==enc[1]==enc[2],
                        'available':source['available'],'scope_end':source['scope_end']})
    write(a.run/'encoder-receipt.json',{'rows':receipt,'all_banks_complete_before_numeric_proxies':True,
                                      'fine_rate_or_phase_provided':False,'actual_human_taps':False})
    print('ENCODED',len(rows),flush=True)


if __name__=='__main__':main()
