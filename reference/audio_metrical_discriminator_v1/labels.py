"""Only development-song reference labels may be opened before fitting."""
import argparse
from pathlib import Path
import numpy as np
from .common import CONFIG,FACTORS,DEVELOPMENT,read,write,guard
from .worker import arrays

def label(feat,ref):
    time=feat['time'];n=len(time);support=np.zeros(n,bool);truth=np.full(n,np.nan)
    for a,b in ref['support']:support|=(time>=a)&(time<b)
    for s in ref['segments']:
        use=(time>=s['start_seconds'])&(time<s['end_seconds']);truth[use]=s['quarter_bpm']
    support &= np.isfinite(truth)
    relative=abs(feat['base_bpm'][:,None]*np.array(FACTORS)[None,:]/truth[:,None]-1)
    relative[~feat['valid_candidates']]=np.inf
    index=np.argmin(relative,axis=1);representable=relative[np.arange(n),index]<=CONFIG['unit_family_relative_tolerance']
    index[~(support&representable)]=-1;purity=np.zeros(n)
    for i,t in enumerate(time):
        if not support[i]:continue
        left=t-CONFIG['window_seconds']/2;right=t+CONFIG['window_seconds']/2
        same=sum(max(0,min(right,s['end_seconds'])-max(left,s['start_seconds'])) for s in ref['segments'] if s['quarter_bpm']==truth[i])
        purity[i]=same/CONFIG['window_seconds']
    train=support&representable&feat['source_available']&(purity>=CONFIG['train_window_purity_min'])
    return {'in_support':support,'truth_bpm':truth,'unit_index':index,
            'family_representable':representable&support,'window_purity':purity,'train_mask':train}

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();guard(a.run);receipt=[]
    for ident in DEVELOPMENT:
        feat=arrays(a.run/'features'/f'{ident}.npz');ref=read(a.run/'references'/f'{ident}.json');labels=label(feat,ref)
        target=a.run/'development-labels'/f'{ident}.npz';target.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(target,**labels)
        receipt.append({'id':ident,'windows':len(feat['time']),'training_windows':int(labels['train_mask'].sum()),
                        'all_support_windows':int(labels['in_support'].sum()),'unrepresentable_windows':int((labels['in_support']&~labels['family_representable']).sum())})
    write(a.run/'development-label-receipt.json',{'rows':receipt,'validation_references_not_read':True})
    print('LABELED DEVELOPMENT',len(receipt),flush=True)

if __name__=='__main__':main()
