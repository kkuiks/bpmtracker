"""Prepare the specified ten inputs, current references and shared final banks."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
import soundfile as sf

from experiments.variable_tempo_interval_consensus_v0.core import quantize, observation
from experiments.variable_tempo_interval_consensus_v0.io import source_array
from .common import ROOT, LEGACY, CONFIG, ARMS, POLICIES, read, write, digest

TARGETS = [
    ('src0096','ntm_kami-kehoe_die-4-u','fixed'),
    ('src0098','ntm_nickelback_san-quentin','fixed'),
    ('src0097','ntm_periphery_prayer-position','fixed'),
    ('src0095','ntm_state-champs_common-sense','fixed'),
    ('src0502','joe-rickard-in-flames-meet-your-maker','fixed'),
    ('src0106','jeff-braun-bilmuri-hard2tell','fixed'),
    ('src0499','daybreak_nocturne','fixed'),
    ('src0500','daybreak_naysayer','fixed'),
    ('src0032','jens-bogren-opeth','variable'),
    ('new001','david-bendeth-underoath-desperate-times-desperate-measures','variable'),
]


def pairs(value):
    if value is None or len(value)==0: return []
    if isinstance(value[0],(int,float)): value=[value]
    result=sorted([[float(a),float(b)] for a,b in value if b>a])
    merged=[]
    for a,b in result:
        if merged and a<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],b)
        else: merged.append([a,b])
    return merged


def accepted_reference(track, ref):
    options=[('support_seconds',ref.get('support_seconds')),
             ('evaluation_scope.grid_support_seconds',ref.get('evaluation_scope',{}).get('grid_support_seconds')),
             ('owner_approved_audio_span_seconds',ref.get('owner_approved_audio_span_seconds')),
             ('accepted_audio_span_seconds',ref.get('accepted_audio_span_seconds')),
             ('evaluation_support_seconds',ref.get('evaluation_support_seconds')),
             ('catalog.reference_support_seconds',track.get('reference_support_seconds'))]
    available=[(key,pairs(value)) for key,value in options if pairs(value)]
    if not available: raise ValueError('No approved support')
    basis,support=available[0]
    def audio_time(e):
        return float(e['master_seconds'] if 'master_seconds' in e else e['time_seconds'])
    states=[]
    for e in sorted(ref['tempo_events'],key=audio_time):
        value=float(e.get('bpm_quarter',e.get('bpm')))
        if not states or quantize(states[-1]['bpm'])!=quantize(value):
            states.append({'time':audio_time(e),'bpm':value})
    segments=[]
    for a,b in support:
        for i,s in enumerate(states):
            left=max(a,s['time']);right=min(b,states[i+1]['time'] if i+1<len(states) else b)
            if right>left:
                segments.append({'start_seconds':left,'end_seconds':right,'quarter_bpm':quantize(s['bpm']),
                                 'original_reference_bpm':s['bpm']})
    if not segments: raise ValueError('No tempo state in approved support')
    quarters=None; quarter_field=None
    for field in ['quarter_times_seconds','quarter_beats_seconds','beats_seconds','beat_times_seconds']:
        if field in ref: quarters=ref[field];quarter_field=field;break
    if quarters is None:
        quarters=[audio_time(e) for e in ref['quarter_events']];quarter_field='quarter_events.master_seconds'
    def inside(t): return any(a<=t<b for a,b in support)
    quarters=sorted(set(float(t) for t in quarters if inside(float(t))))
    if not quarters: raise ValueError('No stored quarter events in support')
    no_grid=pairs(ref.get('evaluation_scope',{}).get('no_grid_tail_seconds'))
    transitions=[]
    for left,right in zip(segments,segments[1:]):
        ratio=right['quarter_bpm']/left['quarter_bpm']
        power=round(np.log2(ratio))
        harmonic=power!=0 and abs(ratio/2.**power-1)<=CONFIG['harmonic_tolerance']
        if abs(left['end_seconds']-right['start_seconds'])<1e-8 and abs(ratio-1)>=.01 and not harmonic:
            transitions.append({'time':right['start_seconds'],'left_bpm':left['quarter_bpm'],
                                'right_bpm':right['quarter_bpm'],'end':right['end_seconds'],
                                'eligible':right['end_seconds']-right['start_seconds']>=12.})
    return {'support':support,'scope_basis':basis,'scope_candidates':dict(available),
            'segments':segments,'quarters':quarters,'quarter_field':quarter_field,'no_grid':no_grid,
            'transitions':transitions,'initial_bpm':segments[0]['quarter_bpm'],
            'additional_offset_applied_seconds':0,'rate_only':False}


def silence_mask(signal,rate,frames):
    zero=np.all(signal==0,axis=1)
    prefix=np.r_[0,np.cumsum(zero)]
    lo=np.minimum(len(zero),np.rint(np.arange(frames)*rate/50).astype(int))
    hi=np.minimum(len(zero),np.rint((np.arange(frames)+1)*rate/50).astype(int))
    return (hi>lo)&(prefix[hi]-prefix[lo]==hi-lo)


def fresh_source(audio, destination, bank_destination, run):
    import torch
    from beat_this.inference import Audio2Frames
    from experiments.metronome_reconstruction_v1.infer import make_evidence
    from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
    from experiments.metronome_benchmark_v1.trace import CandidateTrace
    from experiments.variable_tempo_interval_consensus_v0.candidates import original_h,pool
    started=time.perf_counter()
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    signal,rate=sf.read(audio,dtype='float32',always_2d=True)
    tracker=Audio2Frames(str(ROOT/'data/models/final0.ckpt'),device='cpu',float16=False)
    print('FRESH_SENSOR_START new001',flush=True)
    beat,down=tracker(signal,rate)
    data={'beat_logits':beat.cpu().numpy(),'downbeat_logits':down.cpu().numpy(),'fps':np.array(50),
          'duration_seconds':np.array(len(signal)/rate),
          'silent_frame_mask':silence_mask(signal,rate,len(beat))}
    np.savez_compressed(destination,**data)
    del signal,tracker,beat,down
    observation(data)
    print('FRESH_SENSOR_DONE new001; ORIGINAL_FINAL_BANK_START',flush=True)
    cfg=read(ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json')
    evidence=make_evidence(data['beat_logits'],data['downbeat_logits'],float(data['duration_seconds']),cfg)
    with CandidateTrace(run/'new-original-traces','new001') as trace:
        family=prepare_audio_family(evidence,cfg)
        trace.finish(family,select_from_family(family))
    write(run/'new-original-families/new001.json',family)
    values=[];scored=0
    with gzip.open(run/'new-original-traces/new001.scores.jsonl.gz','rt') as stream:
        for line in stream:
            record=json.loads(line);scored+=1
            candidate=record['candidate']
            if record['block']!='base_search' and candidate['time_signature']['numerator']==4:
                values.append(original_h(candidate,'original_scored_'+str(record['block'])))
    clocks,stats=pool(values,512)
    if not clocks: raise ValueError('Original final candidate bank empty')
    write(bank_destination,{'pools':{'final':clocks},'statistics':{'final':stats},
                           'source_only':True,'reference_fields_read':False,'status':'prepared',
                           'original_score_trials':scored,'original':select_from_family(family)})
    return {'fresh_model_run':True,'seconds':time.perf_counter()-started,
            'model':'Beat This 1.1.0/final0','model_sha256':digest(ROOT/'data/models/final0.ckpt'),
            'same_original_final_bank_generator':True,'other_candidate_pools_generated':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path)
    args=parser.parse_args()
    run=(args.run or ROOT/'data/research/runs/bpm_continuity_v1'/
         (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')).resolve()
    run.mkdir(parents=True,exist_ok=False)
    for sub in ['source-evidence','candidate-banks','current-references','legacy-predictions','initial-inputs','receipts']:
        (run/sub).mkdir()
    print('RUN',run,flush=True)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
    status=subprocess.run(['git','status','--short'],cwd=ROOT,text=True,capture_output=True,check=True).stdout
    write(run/'receipts/entry-state.json',{'head':head,'status':status,'source_git_mutations_performed':False})
    catalog=read(ROOT/'data/samples/catalog.json');tracks={t['id']:t for t in catalog['tracks']}
    excluded=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    old={s['id']:s for s in read(LEGACY/'source-inputs.json')['samples']}
    sources=[];evaluation=[];provenance=[];receipts=[]
    for ident,original_id,role in TARGETS:
        track=tracks[original_id]
        if any(e.get('permanent_exclusion') and (original_id==e.get('id') or
              e.get('slug','') in str(track.get('audio',{}).get('path','')) or
              str(track['title']).casefold()==str(e.get('title','')).casefold()) for e in excluded):
            raise ValueError('Excluded source')
        audio=ROOT/'data/samples'/track['audio']['path'];reference=ROOT/'data/samples'/track['reference']['path']
        # Source byte identity and current reference snapshots are explicitly part
        # of this authorized experiment; no historical files are rewritten.
        ahash=digest(audio);rhash=digest(reference)
        if track['audio'].get('sha256') and ahash!=track['audio']['sha256']:
            raise ValueError(f'Audio differs from accepted catalog: {ident}')
        shutil.copy2(reference,run/'current-references'/f'{ident}.json')
        normalized=accepted_reference(track,read(reference))
        write(run/'current-references'/f'{ident}.normalized.json',normalized)
        evidence_path=run/'source-evidence'/f'{ident}.npz';bank_path=run/'candidate-banks'/f'{ident}.json'
        if ident in old:
            data=source_array(old[ident]['evidence_path'])
            if 'silent_frame_mask' not in data:
                signal,rate=sf.read(audio,dtype='float32',always_2d=True)
                data['silent_frame_mask']=silence_mask(signal,rate,len(data['beat_logits']))
                del signal
            np.savez_compressed(evidence_path,**data)
            shutil.copy2(LEGACY/'candidate-banks'/f'{ident}.json',bank_path)
            sensor={'fresh_model_run':False,'inherited_evidence_path':old[ident]['evidence_path'],
                    'inherited_evidence_sha256':digest(old[ident]['evidence_path']),
                    'model_claim':'Beat This 1.1.0/final0 from retained run documentation',
                    'original_checkpoint_hash_receipt_verified':False,
                    'limitation':'Current cache identity verified; original checkpoint bytes not independently recertified.'}
        else:
            sensor=fresh_source(audio,evidence_path,bank_path,run)
            data=source_array(evidence_path)
        obs=observation(data)
        if abs(obs['duration']-track['duration_seconds'])>.08:
            raise ValueError(f'Accepted source / cache duration mismatch: {ident}')
        bank=read(bank_path)['pools']['final']
        sources.append({'id':ident,'evidence_path':str(evidence_path),'bank_path':str(bank_path),
                        'duration_seconds':obs['duration'],'fps':50})
        evaluation.append({'id':ident,'original_id':original_id,'title':track['title'],'role':role,
                           'reference_path':str(run/'current-references'/f'{ident}.normalized.json'),
                           'source_reference_path':str(reference),'reference_sha256':rhash,
                           'qualification':track.get('qualification',{}),'duration_seconds':obs['duration'],
                           'eligible_transition_count':sum(t['eligible'] for t in normalized['transitions'])})
        provenance.append({'id':ident,'original_id':original_id,'audio_path':str(audio),'audio_sha256':ahash,
                           'evidence_sha256':digest(evidence_path),'bank_sha256':digest(bank_path),
                           'final_clock_count':len(bank),'source_metadata':sensor,
                           'nominal_rate_availability':{str(s['quarter_bpm']):any(abs(h['bpm']-s['quarter_bpm'])<1e-8 for h in bank)
                                                       for s in normalized['segments']}})
        for policy in ['none','initial_unit','initial_exact']:
            previous=LEGACY/'frozen-predictions/A_INTERVAL_FIXED'/policy/f'{ident}.json'
            if previous.exists():
                target=run/'legacy-predictions'/policy/f'{ident}.json';target.parent.mkdir(exist_ok=True)
                shutil.copy2(previous,target)
        receipts.append({'id':ident,'prepared':True,'sensor':sensor,'final_clocks':len(bank)})
        print('PREPARED',ident,'final_clocks',len(bank),flush=True)
    write(run/'source-worker-inputs.json',{'samples':sources})
    write(run/'source-manifest.json',{'samples':provenance,'catalog_sha256':digest(ROOT/'data/samples/catalog.json')})
    write(run/'evaluation-manifest.json',{'samples':evaluation,'catalog_sha256':digest(ROOT/'data/samples/catalog.json')})
    write(run/'config.json',CONFIG)
    protocol={'version':'1.2','based_on_plan_revision':'1.1','config':CONFIG,'arms':ARMS,'policies':POLICIES,
              'fixed_ids':[i for i,o,r in TARGETS if r=='fixed'],'variable_ids':[i for i,o,r in TARGETS if r=='variable'],
              'primary_comparison':'C2_CONTINUITY versus C1_STATELESS, oracle_start',
              'additional_control':'C_HOLD shares seed, support and phase reanchor; BPM changes forbidden',
              'candidate_pool':'final, maximum 512, identical across conditions',
              'actual_human_taps_collected':False,'human_tap_evaluation':'NOT_IN_SCOPE',
              'drift_revision':'Use source candidate quarter indices to unwrap residuals; retain principal-unwrap slope as diagnostic.',
              'drift_limitation':'Conditional on proposed quarter identity, not an independent proof of musical unit; 6-second window cannot certify all >=1% changes.',
              'low_tempo_limitation':'Eight primary matches require seven periods within six seconds; <=70 BPM may not seed.',
              'gates':'Original section 13 numerical gates retained; event-F1 nonregression additionally required for clock-output improvement.',
              'ceiling_rule':'If the stateless macro correct clock is >90%, the +10pp gate ceiling is reported as FIXED_INCONCLUSIVE, not relaxed post-score.',
              'comparison_tolerance':'One 0.02-second evaluation cell per recording; exact event counts use zero tolerance.',
              'offline_inference':True,'full_tempo_map_returned':False,'meter_inference':False,
              'targets_used_for_parameter_tuning':False,'git_head':head,
              'packages':{m:importlib.metadata.version(m) for m in ['numpy','scipy','soundfile','torch','beat_this','matplotlib']}}
    write(run/'protocol.json',protocol)
    shutil.copy2(ROOT/'BPMTracker_BPM_Continuity_Experiment_Plan_2026-10-10.md',run/'plan-v1.1.md')
    write(run/'legacy-config.json',read(LEGACY/'selected-config.json'))
    write(run/'receipts/prepare.json',{'completed':True,'rows':receipts,'run':str(run)})
    print('PREPARE_COMPLETE',run,flush=True)


if __name__=='__main__': main()
