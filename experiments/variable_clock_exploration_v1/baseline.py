"""Source-only unchanged Original on the twelve new constructed inputs."""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from experiments.metronome_reconstruction_v1.infer import make_evidence
from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
from tools.project_storage import ROOT


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    rows=json.loads((a.run/'source-inputs.json').read_text())['samples']
    cfg=json.loads((ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    output=a.run/'original-prospective';output.mkdir(exist_ok=False);receipt=[]
    for row in rows:
        # Cohort selection, never a song-specific inference parameter.
        if not row['id'].startswith('future_'):continue
        started=time.perf_counter()
        with np.load(row['evidence_path'],allow_pickle=False) as d:
            evidence=make_evidence(d['beat_logits'],d['downbeat_logits'],float(d['duration_seconds']),cfg)
        prediction=select_from_family(prepare_audio_family(evidence,cfg),None)
        (output/f"{row['id']}.json").write_text(json.dumps(prediction,indent=2,allow_nan=False)+'\n')
        receipt.append({'id':row['id'],'seconds':time.perf_counter()-started})
        print('ORIGINAL NEW SOURCE',row['id'],flush=True)
    (output/'receipt.json').write_text(json.dumps({'completed':True,'reference_files_read':False,
                                                 'original_sources_and_config_unchanged':True,'rows':receipt},indent=2)+'\n')


if __name__=='__main__':main()
