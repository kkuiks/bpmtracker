"""Freeze current approved references; workers receive only opaque source rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import importlib.metadata
from pathlib import Path
import shutil
import subprocess

import numpy as np
import soundfile as sf

from .common import ROOT, OLD, CONTINUITY, CONFIG, METHODS, GATES, read, write, digest, stamp

VARIABLE = [
 'jens-bogren-opeth', 'andrew-wade-a-day-to-remember',
 'david-bendeth-underoath-desperate-times-desperate-measures',
 'legacy_circle', 'ntm_archspire_liminal-cypher', 'acle-kahney-tesseract-juno',
 'forrester-savell-karnivool', 'wage_war',
 'carl-bown-bullet-for-my-valentine', 'dave-otero-allageon-allageon', 'jens-bogren-btbam-2019',
]
CONFIRMATION = set(VARIABLE[-3:])
METER_ONLY = ['daybreak_nocturne', 'daybreak_naysayer', 'max-morton-jinjer-on-the-top',
              'jamie-king-the-contortionist']
FIXED = ['ntm_kami-kehoe_die-4-u', 'ntm_nickelback_san-quentin',
         'ntm_periphery_prayer-position', 'ntm_state-champs_common-sense',
         'joe-rickard-in-flames-meet-your-maker', 'jeff-braun-bilmuri-hard2tell']


def nominal(b):
    f = Fraction(float(b)).limit_denominator(4)
    return float(f) if abs(float(f)-float(b)) < .001 else float(b)


def intervals(v):
    if not v: return []
    if isinstance(v[0], (int,float)): v = [v]
    return [[float(a),float(b)] for a,b in v if b>a]


def normalize(track, r):
    scope = r.get('evaluation_scope', {})
    support = intervals(r.get('support_seconds')) or intervals(scope.get('grid_support_seconds'))
    support = support or intervals(r.get('owner_approved_audio_span_seconds'))
    support = support or intervals(r.get('accepted_audio_span_seconds'))
    support = support or intervals(track.get('reference_support_seconds'))
    if not support: raise ValueError('No approved reference scope')
    def seconds(e): return float(e.get('master_seconds', e.get('time_seconds')))
    states=[]
    for e in sorted(r['tempo_events'], key=seconds):
        b=nominal(e.get('bpm_quarter',e.get('bpm')))
        if not states or states[-1]['bpm'] != b: states.append({'time':seconds(e),'bpm':b})
    seg=[]
    for a,b in support:
        for i,s in enumerate(states):
            left=max(a,s['time']);right=min(b,states[i+1]['time'] if i+1<len(states) else b)
            if right>left:seg.append({'start_seconds':left,'end_seconds':right,'quarter_bpm':s['bpm']})
    q=None;field=None
    for k in ['quarter_times_seconds','quarter_beats_seconds','quarter_beats_audio_seconds',
              'beats_seconds','beat_times_seconds']:
        if k in r:q=r[k];field=k;break
    if q is None:q=[seconds(e) for e in r['quarter_events']];field='quarter_events'
    q=sorted(set(float(x) for x in q if any(a<=float(x)<b for a,b in support)))
    if not q or not seg: raise ValueError('Empty approved grid')
    transitions=[]
    for left,right in zip(seg,seg[1:]):
        if abs(left['end_seconds']-right['start_seconds'])<1e-7:
            transitions.append({'time':right['start_seconds'],'left_bpm':left['quarter_bpm'],
                                'right_bpm':right['quarter_bpm'],'left_start':left['start_seconds'],
                                'right_end':right['end_seconds']})
    return {'support':support,'segments':seg,'quarters':q,'quarter_field':field,
            'transitions':transitions,'initial_bpm':seg[0]['quarter_bpm'],
            'no_grid':intervals(scope.get('no_grid_tail_seconds')),
            'excluded':intervals(r.get('excluded_evaluation_seconds')),
            'additional_offset_applied_seconds':0}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path);a=p.parse_args()
    run=(a.run or ROOT/'data/research/runs/variable_clock_composition_v1'/
         (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')).resolve()
    run.mkdir(parents=True,exist_ok=False)
    catalog=read(ROOT/'data/samples/catalog.json');tracks={t['id']:t for t in catalog['tracks']}
    excluded=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    old_sources={r['id']:r for r in read(OLD/'source-inputs.json')['samples']}
    old_identity=read(OLD/'identity-index.json')['rows']
    old_by_original={r['original_id']:old_sources[r['id']] for r in old_identity}
    old_eval={r['id']:r for r in read(OLD/'evaluation-index.json')['rows']}
    prior_sources={r['id']:r for r in read(CONTINUITY/'source-worker-inputs.json')['samples']}
    prior_by_original={r['original_id']:prior_sources[r['id']] for r in read(CONTINUITY/'source-manifest.json')['samples']}
    source=[];evaluation=[];provenance=[]
    selected=[(ident,'variable') for ident in VARIABLE]+[(ident,'meter_control') for ident in METER_ONLY]
    selected += [(ident,'fixed_control') for ident in FIXED]
    for n,(original,role) in enumerate(selected):
        ident=f'r{n:03d}';t=tracks[original];audio=ROOT/'data/samples'/t['audio']['path']
        if any(e.get('permanent_exclusion') and (original==e.get('id') or
              e.get('slug','!') in t['audio']['path'] or t['title'].casefold()==e.get('title','!').casefold()) for e in excluded):
            raise ValueError('Permanently excluded input')
        info=sf.info(audio);sha=digest(audio)
        if t['audio'].get('sha256') and sha!=t['audio']['sha256']:raise ValueError('Audio identity changed')
        old=prior_by_original.get(original) or old_by_original.get(original)
        row={'id':ident,'audio_path':str(audio),'duration_seconds':info.frames/info.samplerate,
             'sample_rate':info.samplerate,'sample_frames':info.frames,'channels':info.channels}
        if old:
            row['cache_path']=old['evidence_path'];row['cache_sha256']=digest(old['evidence_path'])
            bank=CONTINUITY/'candidate-banks'/f"{old['id']}.json" if original in prior_by_original else OLD/'candidate-banks'/f"{old['id']}.json"
            row['final_bank_path']=str(bank)
        source.append(row)
        ref=ROOT/'data/samples'/t['reference']['path'];target=run/'references'/f'{ident}.original.json'
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ref,target)
        nr=normalize(t,read(ref));write(run/'references'/f'{ident}.json',nr)
        evaluation.append({'id':ident,'original_id':original,'title':t['title'],'role':role,
                           'partition':'confirmation' if original in CONFIRMATION else 'development',
                           'duration_seconds':row['duration_seconds'],'reference_path':str(run/'references'/f'{ident}.json'),
                           'reference_sha256':digest(ref),'qualification':t.get('qualification',{}),
                           'reference_is_known_development_material':True})
        provenance.append({'id':ident,'original_id':original,'audio_path':str(audio),'audio_sha256':sha,
                           'reference_path':str(ref),'reference_sha256':digest(ref),
                           'sensor_inherited':bool(old),'sensor_provenance':
                           'retained Beat This final0 observations; checkpoint-at-original-run not independently recertified' if old else 'fresh official final0 CPU observations'})
    # The previously authored four musical parents x six arrangements are controls,
    # never counted as additional real recordings or unseen musical truth.
    controls=[r for r in old_identity if r.get('original_id','').startswith('mcc_')]
    if not controls:
        controls=[r for r in old_identity if int(r['id'][3:])>=503]
    for n,identity in enumerate(controls):
        old=old_sources[identity['id']];e=old_eval[identity['id']];ident=f'c{n:03d}'
        audio=Path(old['audio_path']);info=sf.info(audio)
        source.append({'id':ident,'audio_path':str(audio),'duration_seconds':info.frames/info.samplerate,
                       'sample_rate':info.samplerate,'sample_frames':info.frames,'channels':info.channels,
                       'cache_path':old['evidence_path'],'cache_sha256':digest(old['evidence_path']),
                       'final_bank_path':str(OLD/'candidate-banks'/f"{old['id']}.json")})
        write(run/'inherited-control-evaluation'/f'{ident}.json',e)
        evaluation.append({'id':ident,'original_id':identity['original_id'],'title':identity['original_id'],
                           'role':'constructed_control','partition':'constructed',
                           'duration_seconds':source[-1]['duration_seconds'],
                           'legacy_evaluation_path':str(run/'inherited-control-evaluation'/f'{ident}.json'),
                           'reference_is_known_development_material':True})
        provenance.append({'id':ident,'original_id':identity['original_id'],'audio_sha256':digest(audio),
                           'sensor_inherited':True,'sensor_provenance':'retained authored-music official final0 observations'})
    write(run/'source-inputs.json',{'samples':source})
    write(run/'evaluation-index.json',{'rows':evaluation})
    write(run/'provenance.json',{'rows':provenance,'catalog_sha256':digest(ROOT/'data/samples/catalog.json'),
                                 'model_sha256':digest(ROOT/'data/models/final0.ckpt')})
    write(run/'protocol.json',{'created_at_utc':stamp(),'config':CONFIG,'methods':METHODS,'gates':GATES,
        'primary':'source-only region-first joint clock/interval composition on complete variable songs',
        'input_policies':['none','proxy100','proxy95','proxy105'],
        'proxy_numeric_values_only_in_separate_encoder':True,'actual_human_taps_collected':False,
        'oracle':'union of true nominal BPM/physical quarter phases; interval boundaries withheld from predictor',
        'cohort':{'real_variable':len(VARIABLE),'meter_controls':len(METER_ONLY),'fixed_controls':len(FIXED),
                  'constructed_music_controls':len(controls)},
        'confirmation_is_known_material_not_unseen_test':True,
        'confirmation_ids':[r['id'] for r in evaluation if r['partition']=='confirmation'],
        'all_songs_and_all_transitions_retained':True,'all_configs_frozen_before_real_prediction_scoring':True,
        'no_target_parameter_tuning':True,'gradual_tempo_and_automatic_meter_not_in_scope':True,
        'offline_future_audio_used':True,'app_integration':False,'source_git_mutations':False,
        'packages':{m:importlib.metadata.version(m) for m in ['numpy','scipy','soundfile','torch','beat_this','matplotlib']}})
    write(run/'entry-state.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)})
    print('RUN',run,'SOURCES',len(source),flush=True)


if __name__=='__main__':main()
