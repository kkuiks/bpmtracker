"""Prediction-only worker. Evaluation files cannot be passed in its schema."""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from .clock import predict


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['calibration','frozen'],required=True)
    p.add_argument('--limit',type=int,default=0);p.add_argument('--only-method');a=p.parse_args()
    protocol=json.loads((a.run/'protocol.json').read_text())
    rows=json.loads((a.run/'source-inputs.json').read_text())['samples']
    allowed={'id','evidence_path','duration_seconds','fps','audio_path'}
    if any(set(row)-allowed for row in rows):raise ValueError('Non-source input field')
    if a.stage=='calibration':
        ids=set(protocol['calibration_ids']);rows=[r for r in rows if r['id'] in ids]
        configs=[(m,float(p),False) for m in protocol['methods'] for p in protocol['penalty_scales']]
    else:
        if not (a.run/'predictor-freeze.json').exists():raise ValueError('Predictor must be frozen')
        selected=json.loads((a.run/'selected-config.json').read_text())
        configs=[(m,float(p),snap) for m,p in selected.items() for snap in (False,True)]
    if a.limit:rows=rows[:a.limit]
    if a.only_method:configs=[r for r in configs if r[0]==a.only_method]
    output=a.run/f'{a.stage}-predictions';output.mkdir(exist_ok=bool(a.only_method))
    receipt=[]
    receipt_path=output/'receipt.json'
    if a.only_method and receipt_path.exists():
        old=receipt_path.read_bytes();(output/f'receipt-before-{a.only_method}.json').write_bytes(old)
        receipt=json.loads(old)['rows']
    receipt_path.write_text(json.dumps({'completed':False,'reference_files_read':False,'rows':receipt},indent=2)+'\n')
    for i,row in enumerate(rows):
        with np.load(a.run/'source-features'/f"{row['id']}.npz",allow_pickle=False) as stored:
            data={k:stored[k].copy() for k in stored.files}
        for method,penalty,snap in configs:
            if snap and 'attack_times' not in data:continue
            key=f"{method}-p{penalty:g}-{'attack' if snap else 'neural'}"
            folder=output/key;folder.mkdir(exist_ok=True)
            if (folder/f"{row['id']}.json").exists():raise ValueError('Prediction output already exists')
            started=time.perf_counter()
            try:result=predict(data,method,penalty,snap)
            except Exception as exc:result={'status':'failed','error':f'{type(exc).__name__}: {exc}','regions':[],'boundaries':[]}
            result.update(id=row['id'],fitting_seconds=time.perf_counter()-started)
            (folder/f"{row['id']}.json").write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            receipt.append({'id':row['id'],'configuration':key,'seconds':result['fitting_seconds'],'status':result['status']})
        if (i+1)%10==0 or i+1==len(rows):print(f'{a.stage.upper()} {i+1}/{len(rows)} {row["id"]}',flush=True)
    (output/'receipt.json').write_text(json.dumps({'completed':True,'reference_files_read':False,
                                                 'rows':receipt},indent=2)+'\n')


if __name__=='__main__':main()
