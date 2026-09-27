"""Freeze a disjoint follow-up probe and candidate code before seeing its results.

Track IDs and exact features are disjoint from the development sample. Artist,
composition and near-duplicate independence are not certified by this utility.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from inspect_inputs import sha256
from prepare_public_corpus import write_json, read_published_beats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development-catalog',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--per-genre',type=int,default=5)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    if not 1<=args.per_genre<=100:parser.error('per-genre must be between 1 and 100')
    dev=json.loads(args.development_catalog.read_text())
    excluded={t['id'] for t in dev['tracks']}
    existing_hashes={t['input']['sha256'] for t in dev['tracks']}
    source=args.development_catalog.parent
    groups={}
    for annotation in sorted((source/'published-annotations').glob('*/gtzan/annotations/beats/*.beats')):
        if annotation.stem not in excluded:
            groups.setdefault(annotation.stem.split('_')[1],[]).append(annotation)
    args.output_dir.mkdir(parents=True)
    entries=[]
    with zipfile.ZipFile(source/'published-features/gtzan.npz') as features:
        for genre,paths in sorted(groups.items()):
            paths.sort(key=lambda p:hashlib.sha256(('joljak-followup-probe-v1:'+p.stem).encode()).hexdigest())
            chosen=0
            for annotation in paths:
                raw=features.read(f'{annotation.stem}/track.npy')
                digest=hashlib.sha256(raw).hexdigest()
                if digest in existing_hashes:continue
                feature_path=args.output_dir/'features'/f'{annotation.stem}.npy'
                feature_path.parent.mkdir(exist_ok=True)
                feature_path.write_bytes(raw)
                array=np.load(feature_path,allow_pickle=False)
                beats,downbeats = read_published_beats(annotation)
                reference={'kind':'published_human_beat_annotation','source_annotation':str(annotation),
                           'source_annotation_sha256':sha256(annotation),'annotation_version':'beat_this_annotations v1.1',
                           'beats_seconds':beats,'downbeats_seconds':downbeats,
                           'tempo_events':None,'meter_events':None,'evaluation_support_seconds':[0,len(array)/50],
                           'source_origin_shift_seconds':0,'annotation_caveat':'Human labels; no waveform acquired.'}
                label_path=args.output_dir/'labels'/f'{annotation.stem}.json'
                write_json(label_path,reference)
                entries.append({'id':annotation.stem,'dataset':'gtzan','genre':genre,
                                'input':{'kind':'spectrogram','path':str(feature_path),'sha256':digest,'fps':50},
                                'reference':{'path':str(label_path),'sha256':sha256(label_path)},
                                'duration_seconds':len(array)/50,'group_id':annotation.stem,
                                'model_overlap':'publisher excludes GTZAN from final0 training','target_scope':'metronome status unqualified'})
                existing_hashes.add(digest);chosen+=1
                if chosen==args.per_genre:break
            if chosen!=args.per_genre:raise ValueError('insufficient distinct examples')
    files=('fit_clock.py','decode_pulses.py','decode_bar_structure.py','pulse_gaps.py','run_corpus_benchmark.py','evaluate_saved_clocks.py')
    hashes={}
    snapshot=args.output_dir/'frozen-source';snapshot.mkdir()
    for name in files:
        p=Path(__file__).with_name(name);hashes[name]=sha256(p);(snapshot/name).write_bytes(p.read_bytes())
    write_json(args.output_dir/'catalog.json',{'schema_version':1,'dataset':'gtzan','role':'disjoint_followup_probe_not_artist_heldout_final_test',
        'selection':f'{args.per_genre} per genre by SHA256(joljak-followup-probe-v1:ID), excluding development IDs/exact feature duplicates',
        'development_catalog_sha256':sha256(args.development_catalog),'frozen_candidate_code':hashes,
        'tracks':entries,'excluded':[]})
    print(args.output_dir/'catalog.json',len(entries))


if __name__=='__main__':main()
