"""Controlled downbeat-evidence fusion using already aligned original drum stems.

All variants share the same mix-derived pulse clock. No independent stem clock,
audio shift, source separation, or reference-informed weighting is applied.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from bar_metrics import score_bar_changes
from decode_bar_structure import bar_path
from inspect_inputs import sha256
from run_corpus_benchmark import score_events


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clock-report',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--mix-run',type=Path,required=True)
    parser.add_argument('--stem-runs',type=Path,nargs='+',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    args.output_dir.mkdir(parents=True)
    clocks={t['id']:t for t in json.loads(args.clock_report.read_text())['tracks']}
    catalog={t['id']:t for t in json.loads(args.catalog.read_text())['tracks']}
    report={'clock_report_sha256':sha256(args.clock_report),'runner_sha256':sha256(__file__),
            'fusion':'equal mean sigmoid downbeat activations; same frozen mix pulse clock','tracks':[]}
    for path in args.stem_runs:
        number=path.name.split('-')[1]
        name='babyslakh_'+number
        entry=catalog[name]
        stem_info=json.loads((path/'result.json').read_text())
        stem_audio=Path(entry['input']['path']).parent/'stems/S00.wav'
        if sha256(stem_audio)!=stem_info['audio']['sha256']:raise ValueError('stem provenance mismatch')
        if (stem_info['audio']['analyzed_frames'],stem_info['audio']['sample_rate'])!=(entry['sample_frames'],entry['sample_rate']):
            raise ValueError('stem and mix clocks differ')
        mix=np.load(args.mix_run/name/'logits.npz')
        drum=np.load(path/'logits.npz')
        if mix['downbeat'].shape!=drum['downbeat'].shape or float(mix['fps'])!=float(drum['fps']):
            raise ValueError('logit time axes differ')
        probability=(1/(1+np.exp(-np.clip(mix['downbeat'].astype(float),-60,60)))+1/(1+np.exp(-np.clip(drum['downbeat'].astype(float),-60,60))))/2
        probability=np.clip(probability,1e-7,1-1e-7)
        fusion=np.log(probability/(1-probability))
        grid=clocks[name]['methods']['meter_free_clock']['prediction']['beats_seconds']
        methods={}
        for label,evidence in [('mix_only',mix['downbeat']),('drums_only',drum['downbeat']),('equal_fusion',fusion)]:
            bars=bar_path(grid,evidence,fps=float(mix['fps']))
            methods[label]={'bars':bars,'prediction':{'beats_seconds':list(grid),'downbeats_seconds':bars['downbeats_seconds']}}
        reference=json.loads(Path(entry['reference']['path']).read_text())
        for method in methods.values():
            method['scores']=score_events(reference,method['prediction'],0)
            method['meter_change_scores']=score_bar_changes(reference,method['bars'])
        report['tracks'].append({'id':name,'stem_audio_sha256':sha256(stem_audio),'methods':methods})
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    for t in report['tracks']:
        print(t['id'],{k:{'downbeat_f1':v['scores']['downbeats_seconds']['0.07']['f1'],'meter_changes':v['meter_change_scores']} for k,v in t['methods'].items()})


if __name__=='__main__':main()
