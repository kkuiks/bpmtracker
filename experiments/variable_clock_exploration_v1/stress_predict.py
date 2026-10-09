"""Source-only predictor for the supplementary controls; no reference access."""
import argparse
import json
from pathlib import Path

import numpy as np

from .clock import predict
from .onset import predict as onset_predict
from .prepare import attack_evidence


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    rows=json.loads((a.root/'source-inputs.json').read_text())['samples']
    expected={'id','audio_path','sample_rate','sample_frames','channels','duration_seconds'}
    if any(set(r)!=expected for r in rows):raise ValueError('Non-source field')
    for row in rows:
        with np.load(a.root/'evidence'/f"{row['id']}.npz",allow_pickle=False) as s:data={k:s[k].copy() for k in s.files}
        data.update(attack_evidence(row['audio_path'],len(data['beat_logits']),50))
        for method in ('affine_mdl','multiscale','transport','phasor_transport','phasor_abstain'):
            for snap in (False,True):
                key=method+('-attack' if snap else '-neural');out=a.root/'predictions'/key;out.mkdir(parents=True,exist_ok=True)
                value=predict(data,method,32,snap)
                (out/f"{row['id']}.json").write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
        for name,gauge in (('raw_onset_transport',False),('raw_onset_initial_neural_unit',True)):
            out=a.root/'predictions'/name;out.mkdir(parents=True,exist_ok=True)
            value=onset_predict(data,gauge)
            (out/f"{row['id']}.json").write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
        print('SUPPLEMENTARY SOURCE',row['id'],flush=True)
    (a.root/'prediction-receipt.json').write_text(json.dumps({'completed':True,'source_count':len(rows),
                                                           'reference_files_read':False,'parameters_retuned':False},indent=2)+'\n')


if __name__=='__main__':main()
