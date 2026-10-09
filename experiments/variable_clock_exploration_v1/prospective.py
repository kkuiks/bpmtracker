"""Declare fresh constructed parent groups before calibration and real scoring."""
import argparse
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from beat_this.inference import Audio2Frames

from experiments.variable_tempo_step0 import generated
from tools.project_storage import ROOT
from .prepare import write, attack_evidence


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    corpus=ROOT/'data/samples/generated/variable-clock-exploration-v1-20261008'
    corpus.mkdir(parents=True,exist_ok=False)
    plan=[]
    for seed,base in ((6301,Fraction(175,2)),(6359,Fraction(469,4)),
                      (6407,Fraction(575,4)),(6481,Fraction(363,2))):
        for variant in ('fixed','return','short_bar'):
            segments=([(base,96)] if variant=='fixed' else
                      [(base,48),(base+Fraction(15,2),12),(base,48)] if variant=='return' else
                      [(base,64),(base+27,4),(base,64)])
            plan.append({'seed':seed,'variant':variant,'segments':[(str(b),n) for b,n in segments]})
    write(corpus/'predeclared-plan.json',{'parents':4,'inputs':12,'plan':plan,
                                        'before_real_results':True,'same_renderer_family_not_independent_real_music':True})
    rows=[];refs=[]
    for row in plan:
        seed,variant=row['seed'],row['variant'];ident=f'future_{seed}_{variant}'
        generated.CASES[variant]=[(Fraction(b),n) for b,n in row['segments']]
        source,ref=generated.render(corpus,ident,seed,variant)
        source['audio_path']=str(corpus/'inputs'/ident/'music.wav')
        ref['reference_path']=str(corpus/'references'/f'{ident}.json')
        rows.append(source);refs.append(ref)
    write(corpus/'source-inputs.json',{'samples':rows});write(corpus/'admission.json',{'rows':refs})
    output=a.run/'prospective-neural-evidence';output.mkdir(exist_ok=False)
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    tracker=Audio2Frames(str(ROOT/'data/models/final0.ckpt'),device='cpu',float16=False)
    sources=json.loads((a.run/'source-inputs.json').read_text())
    evaluation=json.loads((a.run/'evaluation-index.json').read_text())
    for row,ref in zip(rows,refs):
        signal,rate=sf.read(row['audio_path'],dtype='float32',always_2d=True)
        beat,down=tracker(signal,rate)
        values={'beat_logits':beat.cpu().numpy(),'downbeat_logits':down.cpu().numpy(),
                'fps':np.array(50),'duration_seconds':np.array(len(signal)/rate)}
        path=output/f"{row['id']}.npz";np.savez_compressed(path,**values)
        values.update(attack_evidence(row['audio_path'],len(beat),50))
        np.savez_compressed(a.run/'source-features'/f"{row['id']}.npz",**values)
        sources['samples'].append({'id':row['id'],'evidence_path':str(path.resolve()),
                                   'duration_seconds':row['duration_seconds'],'fps':50,'audio_path':row['audio_path']})
        evaluation['rows'].append({'id':row['id'],'reference_path':ref['reference_path'],
                                   'role':'prospective_constructed','kind':'authored','support_seconds':ref['support_seconds']})
        print('FUTURE SOURCE',row['id'],flush=True)
    write(a.run/'source-inputs.json',sources);write(a.run/'evaluation-index.json',evaluation)
    write(a.run/'prospective-receipt.json',{'completed':True,'inputs':12,'parent_groups':4,
                                          'official_sensor_weights_unchanged':True,'reference_read_by_sensor':False,
                                          'marker_channels_not_model_inputs':True})


if __name__=='__main__':main()
