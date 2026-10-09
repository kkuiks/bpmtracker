"""Additional declared source controls: constant BPM with changed meter."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import soundfile as sf

from tools.project_storage import ROOT, SAMPLES
from .prepare import write


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    out=a.run/'supplementary-meter-negative-controls';out.mkdir(exist_ok=False)
    catalog=json.loads((SAMPLES/'catalog.json').read_text())['tracks']
    selected={'daybreak_nocturne','daybreak_naysayer','ntm_sleeping-with-sirens_an-ending-in-itself',
              'joe-rickard-in-flames-meet-your-maker'}
    sources=[];refs=[]
    for row in catalog:
        if row['id'] not in selected:continue
        path=SAMPLES/row['audio']['path'];info=sf.info(path)
        sources.append({'id':row['id'],'audio_path':str(path),'sample_rate':info.samplerate,
                        'sample_frames':info.frames,'channels':info.channels,'duration_seconds':info.duration})
        refs.append({'id':row['id'],'reference_path':str(SAMPLES/row['reference']['path']),
                     'role':'supplementary_constant_bpm','kind':'accepted','support_seconds':row['reference_support_seconds']})
    write(out/'source-inputs.json',{'samples':sources});write(out/'evaluation-index.json',{'rows':refs})
    write(out/'protocol.json',{'declared_at_utc':datetime.now(timezone.utc).isoformat(),
                              'purpose':'BPM false-change stress: three meter-changing constant-rate recordings and the newly enrolled fixed Meet Your Maker',
                              'supplementary_known_development_only':True,'model_tuning':False})
    subprocess.run([sys.executable,'-m','experiments.variable_clock_exploration_v1.observations',
                    '--source',str(out/'source-inputs.json'),'--output',str(out/'evidence')],cwd=ROOT,check=True)
    subprocess.run([sys.executable,'-m','experiments.variable_clock_exploration_v1.stress_predict',
                    '--root',str(out)],cwd=ROOT,check=True)


if __name__=='__main__':main()
