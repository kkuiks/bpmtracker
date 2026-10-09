"""Strict source-only official sensor replay for fresh constructed inputs."""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from beat_this.inference import Audio2Frames

from tools.project_storage import ROOT


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    rows=json.loads(a.source.read_text())['samples']
    allowed={'id','audio_path','sample_rate','sample_frames','channels','duration_seconds'}
    if any(set(r)!=allowed for r in rows):raise ValueError('Source-only schema violated')
    a.output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    tracker=Audio2Frames(str(ROOT/'data/models/final0.ckpt'),device='cpu',float16=False)
    receipt=[]
    for row in rows:
        signal,rate=sf.read(row['audio_path'],dtype='float32',always_2d=True)
        if rate!=row['sample_rate'] or signal.shape!=(row['sample_frames'],row['channels']):raise ValueError('Geometry mismatch')
        beat,down=tracker(signal,rate)
        np.savez_compressed(a.output/f"{row['id']}.npz",beat_logits=beat.cpu().numpy(),
                            downbeat_logits=down.cpu().numpy(),fps=np.array(50),duration_seconds=np.array(len(signal)/rate))
        receipt.append({'id':row['id'],'frames':len(beat)})
        print('ISOLATED SOURCE',row['id'],flush=True)
    (a.output/'receipt.json').write_text(json.dumps({'completed':True,'reference_files_read':False,
                                                   'source_schema_only':True,'rows':receipt},indent=2)+'\n')


if __name__=='__main__':main()
