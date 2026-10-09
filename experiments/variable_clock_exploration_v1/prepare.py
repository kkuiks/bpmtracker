"""Prepare separate source and evaluation indexes from retained fresh-start data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from scipy.signal import find_peaks, stft

from tools.project_storage import ROOT, SAMPLES, RUNS, resolve_path

STEP = RUNS/'variable_tempo_step0/20261007-step0-v1'
BENCH = RUNS/'metronome_benchmark_v1'


def read(path):
    return json.loads(resolve_path(path).read_text())


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False,ensure_ascii=False)+'\n')


def attack_evidence(audio,frames,fps):
    signal,rate=sf.read(audio,dtype='float32',always_2d=True)
    hop=rate/fps
    silent=np.array([np.all(signal[round(i*hop):round((i+1)*hop)]==0)
                     for i in range(frames)],dtype=bool)
    mono=signal.mean(axis=1)
    if rate!=22050:mono=soxr.resample(mono,rate,22050,quality='HQ')
    frequencies,times,spectrum=stft(mono,fs=22050,nperseg=1024,noverlap=914,
                                    boundary='zeros',padded=False)
    energy=abs(spectrum)**2
    channels=[]
    for low,high in ((40,250),(250,2500),(2500,10000)):
        band=energy[(frequencies>=low)&(frequencies<high)].sum(axis=0)
        curve=np.maximum(0,np.diff(np.log1p(band*1e5),prepend=0))
        curve/=max(float(np.quantile(curve,.95)),1e-8)
        channels.append(np.minimum(curve,5))
    novelty=np.mean(channels,axis=0)
    positions,_=find_peaks(novelty,height=.3,distance=12,prominence=.1)
    return {'attack_times':times[positions],'attack_weights':novelty[positions],
            'silent_frame_mask':silent}


def build(run):
    run.mkdir(parents=True,exist_ok=False)
    sources={};evaluation=[]
    catalog={r['id']:r for r in read(SAMPLES/'catalog.json')['tracks']}
    # The durable exclusion register is checked before admitting any source.
    exclusions=read(SAMPLES/'excluded-candidates.json')['candidates']
    forbidden={r.get('id') for r in exclusions if r.get('permanent_exclusion')}
    forbidden|={r.get('slug') for r in exclusions if r.get('permanent_exclusion')}

    def admit(row,evidence,reference,role,kind,support=None):
        ident=row['id']
        if ident in forbidden:raise ValueError('Excluded source in admission')
        audio=row.get('audio_path')
        if audio:audio=str(resolve_path(audio))
        if ident not in sources:
            sources[ident]={'id':ident,'evidence_path':str(evidence.resolve()),
                           'duration_seconds':row['duration_seconds'],'fps':50}
            if audio:sources[ident]['audio_path']=audio
        evaluation.append({'id':ident,'reference_path':str(resolve_path(reference)),
                           'role':role,'kind':kind,'support_seconds':support})

    admissions={r['id']:r for r in read(STEP/'admission.json')['rows']}
    for row in read(STEP/'source-inputs.json')['samples']:
        meta=admissions[row['id']]
        role=('vocabulary_probe' if 'probe' in meta['variant']
              else 'synthetic_calibration' if meta['parent_group']=='step0_composition:5100'
              else 'synthetic_prior_evaluation' if row['id'].startswith('step0_')
              else 'real_variable' if meta['variant']=='real_variable'
              else 'secondary_variable' if meta['variant'].startswith('secondary')
              else 'vocabulary_probe')
        reference=STEP/'evaluation-references'/f"{row['id']}.json"
        kind='step0'
        if not reference.exists():
            if meta['reference_path'] is None:
                reference=BENCH/'20261007-babyslakh-baseline-v1/qualification.json'
                kind='encoded'
            else:reference=resolve_path(meta['reference_path']);kind='authored'
        admit(row,STEP/'acoustic-evidence'/f"{row['id']}.npz",reference,role,
              kind,meta['support_seconds'])
        if kind=='encoded':evaluation[-1]['record_id']=meta['inventory_id'].removeprefix('babyslakh_')

    corpus=SAMPLES/'datasets/generated-clock-contrast-v1'
    for row in read(corpus/'source-inputs.json')['samples']:
        reference=corpus/'references'/f"{row['id']}.json"
        admit(row,BENCH/'20261007-generated58-frozen-v1/evidence'/f"{row['id']}.npz",
              reference,'generated_fixed','generated')

    fixed=read(SAMPLES/'selections/fixed-metronome-v1/all-valid-inference.json')['samples']
    for row in fixed:
        sample=catalog[row['id']]
        source={**row,'audio_path':str(SAMPLES/sample['audio']['path'])}
        admit(source,ROOT/'data/research/state/experiment/metronome-v1/evidence'/f"{row['id']}.npz",
              SAMPLES/sample['reference']['path'],'formal_fixed','accepted',sample['reference_support_seconds'])

    for name,role in (('20261007-gtzan-development280-frozen-v1','gtzan_development'),
                      ('20261007-gtzan-validation87-frozen-v1','gtzan_used_validation')):
        root=BENCH/name
        for row in read(root/'source-inputs.json')['samples']:
            admit(row,root/'evidence'/f"{row['id']}.npz",root/'references'/f"{row['id']}.json",role,'gtzan')

    development=sorted(r['id'] for r in evaluation if r['role']=='gtzan_development')
    # Four deterministic sources per genre. No prior prediction score enters selection.
    calibration=[]
    for genre in sorted({x.split('_')[1] for x in development}):
        calibration.extend([x for x in development if x.split('_')[1]==genre][:4])
    calibration.extend(r['id'] for r in evaluation if r['role']=='synthetic_calibration')
    protocol={'created_at_utc':datetime.now(timezone.utc).isoformat(),
              'experiment':'variable-clock-exploration-v1','methods':['affine_mdl','multiscale','transport'],
              'penalty_scales':[8,16,32],'sensor_variants':['neural','attack_snapped'],
              'calibration_ids':calibration,'real_references_used_to_tune':False,
              'existing_validation_is_already_used':True,'reserved_groups_consumed':0,
              'quarter_bpm_output_domain':[30,400],'maximum_denominator':4,
              'metrical_octave_alternatives_are_diagnostic':True,
              'automatic_meter_inference':False,'application_integration':False,
              'known_real_sources_are_development_material':True,
              'source_and_reference_workers_separate':True,
              'research_sources':[
                  'https://arxiv.org/abs/2308.10355',
                  'https://arxiv.org/abs/2210.06817'],
              'novelty_claim':'new project experiments combining source-inferred clock compression, multiscale witnesses and phase transport; no world-first claim'}
    write(run/'protocol.json',protocol)
    write(run/'source-inputs.json',{'samples':list(sources.values())})
    write(run/'evaluation-index.json',{'rows':evaluation})
    write(run/'admission.json',{'unique_sources':len(sources),'evaluation_rows':len(evaluation),
                               'excluded_sources_admitted':0,'reference_values_unchanged':True})
    return len(sources)


def features(run):
    output=run/'source-features';output.mkdir(exist_ok=False)
    rows=read(run/'source-inputs.json')['samples'];receipt=[]
    for i,row in enumerate(rows):
        with np.load(row['evidence_path'],allow_pickle=False) as old:
            values={k:old[k].copy() for k in old.files if k in
                    ('beat_logits','downbeat_logits','fps','duration_seconds','silent_frame_mask')}
        if row.get('audio_path'):
            values.update(attack_evidence(row['audio_path'],len(values['beat_logits']),int(values['fps'])))
        np.savez_compressed(output/f"{row['id']}.npz",**values)
        receipt.append({'id':row['id'],'audio_available':bool(row.get('audio_path')),
                        'reference_read':False,'new_neural_inference':False})
        if (i+1)%25==0:print(f'SOURCE FEATURES {i+1}/{len(rows)}',flush=True)
    write(run/'feature-receipt.json',{'completed':True,'rows':receipt,'reference_files_read':False})


def freeze(run):
    paths=sorted(Path(__file__).parent.glob('*.py'))
    snapshot=run/'source-snapshot';snapshot.mkdir(exist_ok=False)
    hashes={}
    for path in paths:
        content=path.read_bytes();hashes[path.name]=hashlib.sha256(content).hexdigest()
        (snapshot/path.name).write_bytes(content)
    for name in ('protocol.json','selected-config.json','source-inputs.json','evaluation-index.json'):
        content=(run/name).read_bytes();hashes[name]=hashlib.sha256(content).hexdigest()
        (snapshot/name).write_bytes(content)
    write(run/'predictor-freeze.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
                                      'sources_sha256':hashes,'before_real_evaluation':True})


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['build','features','freeze'],required=True);a=p.parse_args()
    if a.stage=='build':print('ADMITTED',build(a.run))
    elif a.stage=='features':features(a.run)
    else:freeze(a.run)


if __name__=='__main__':main()
