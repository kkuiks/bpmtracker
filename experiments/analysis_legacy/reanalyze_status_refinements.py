"""Replay existing prior, phase and bar experiments on frozen core predictions.

No strength or phase is chosen with labels. The original meter-free grid feeds
bar decoding. Priors use the original raw pulses, never an already fitted grid.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import resource
import time

import numpy as np
import soundfile as sf
import torch

from bar_metrics import score_bar_changes
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from decode_bar_structure import bar_path
from decode_pulses import decode_pulses
from evaluate_tempo_prior import prediction
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from replay_integrity import source_fingerprint, prediction_index, require_file_hash, merge_prediction_rows
from phase_alignment import AttackConfig, PhaseConfig, extract_attacks, propose_phase, shifted_clock
from reanalyze_status_paths import read, save
from status_reanalysis_metrics import tempo_rate_diagnostics
from tempo_prior import PriorConfig, refine_tempo_clock

PREDICTION_SOURCES=('reanalyze_status_refinements.py','tempo_prior.py','phase_alignment.py','decode_bar_structure.py',
    'decode_pulses.py','fit_clock.py','legacy_dbn.py','evaluate_tempo_prior.py','run_beat_this.py','replay_integrity.py')
STRENGTHS=(0.,.5,1.,2.)
TOLERANCES={'10ms':.01,'20ms':.02,'30ms':.03,'70ms':.07}


def get_attacks(track_id, source, output, calibration):
    config=AttackConfig(**calibration['configuration']);feature_hash=sha256(Path(__file__).with_name('phase_alignment.py'))
    local=output/'attacks'/(track_id+'.json')
    paths=[local,Path('data/runs/phase-alignment/attacks-v1')/(track_id+'.json')]
    paths.extend(Path('data/runs/corpus-expansion').glob('*/'+track_id+'/attacks.json'))
    for path in paths:
        if not path.exists():continue
        attacks=read(path)
        if (attacks.get('audio_sha256')==source['sha256'] and attacks.get('feature_sha256')==feature_hash
                and attacks.get('configuration')==asdict(config)):
            return attacks,{'path':str(path),'sha256':sha256(path),'execution':'cache_reuse'}
    started=time.perf_counter()
    if sha256(source['path'])!=source['sha256']:raise ValueError('audio changed')
    audio,sr=sf.read(source['path'],dtype='float32',always_2d=True)
    if (sr,len(audio))!=(source['sample_rate'],source['sample_frames']):raise ValueError('audio geometry mismatch')
    attacks=extract_attacks(audio,sr,config)
    attacks.update(audio_sha256=source['sha256'],feature_sha256=feature_hash)
    save(local,attacks)
    return attacks,{'path':str(local),'sha256':sha256(local),'execution':'computed','elapsed_seconds':time.perf_counter()-started}


def build(core, output, calibration):
    source=core['source'];duration=source['duration_seconds'];fps=source['native_frame_rate']
    if sha256(source['logits_path'])!=source['logits_sha256']:raise ValueError('logits changed')
    values=np.load(source['logits_path']);raw=decode_pulses(values['beat'],fps=fps)
    raw=raw[(raw>=0)&(raw<duration)]
    base=core['methods']['meter_free_clock'];clock=base['clock'];methods={};started=time.perf_counter()
    if clock and len(raw)!=clock['input_event_count']:raise ValueError('raw pulse count differs from clock')
    for strength in STRENGTHS:
        name='continuous_refit' if strength==0 else 'soft_prior_'+str(strength)
        if clock is None:
            value={'clock':None,'prediction':base['prediction']['beats_seconds'],'status':'unchanged_no_clock_fallback'}
        else:
            try:
                fitted=refine_tempo_clock(raw,clock['input_pulse_indices'],clock,
                    PriorConfig(strength=strength,quantization_seconds=1/fps))
                value={'clock':fitted,'prediction':prediction(fitted,duration,clock['pulse_index_span']),
                       'status':'refitted_unaccepted_proposal'}
            except ValueError as error:
                value={'clock':clock,'prediction':base['prediction']['beats_seconds'],
                       'status':'unchanged_rejected_refit','reason':str(error)}
        value['prior_strength']=strength;methods[name]=value
    strongest=methods['soft_prior_2.0'];attack_provenance=None
    if strongest['clock'] is not None:
        attacks,attack_provenance=get_attacks(core['id'],source,output,calibration)
        phase=propose_phase(strongest['prediction'],attacks,calibration,PhaseConfig())
    else:phase={'status':'no_clock_fallback','applied_shift_seconds':0.}
    shift=phase['applied_shift_seconds']
    moved=shifted_clock(strongest['clock'],shift,duration) if strongest['clock'] and shift else strongest['clock']
    methods['phase_after_prior_2']={'clock':moved,
        'prediction':[v+shift for v in strongest['prediction'] if 0<=v+shift<duration],
        'status':phase['status'],'phase':phase}
    bars={name:bar_path(base['prediction']['beats_seconds'],values['downbeat'],fps=fps,variable=variable)
          for name,variable in [('fixed',False),('variable',True)]}
    return {'id':core['id'],'cohort':core['cohort'],'model':core['model'],'source':source,
        'references_used_for_prediction':False,'methods':methods,'bars':bars,
        'bar_input_grid':'unchanged_meter_free_clock_prediction','attack_provenance':attack_provenance,
        'elapsed_seconds':time.perf_counter()-started,
        'memory_process_high_water_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}


def score(reference, predictions):
    methods={};lo,hi=reference['evaluation_support_seconds']
    for name,method in predictions['methods'].items():
        clock=method['clock']
        methods[name]=evaluate_times(reference,method['prediction'],tempo_events(clock) if clock else None,
                                    tempo_map_supported=True)
        methods[name]['rate_diagnostics']=tempo_rate_diagnostics(reference,clock)
        methods[name]['downbeat_capability']='unsupported_in_this_path'
    bars={}
    for name,bar in predictions['bars'].items():
        downbeats=reference.get('downbeats_seconds')
        scores={label:nearest_event_diagnostics([v for v in downbeats if lo<=v<=hi],
            [v for v in bar['downbeats_seconds'] if lo<=v<=hi],tol) if downbeats is not None else None
            for label,tol in TOLERANCES.items()}
        signatures=sorted({(e['numerator'],e['denominator']) for e in reference.get('meter_events') or []})
        bars[name]={'downbeat_scores':scores,'meter_change_500ms_quarter_hypothesis':score_bar_changes(reference,bar,.5),
            'meter_change_100ms_quarter_hypothesis':score_bar_changes(reference,bar,.1),
            'unsupported_reference_signatures':[list(s) for s in signatures if s[1]!=4 or s[0] not in (2,3,4)],
            'full_meter_map_status':'unresolved_pulse_unit_and_denominator',
            'musical_origin_status':'unverified_not_a_first_bar_accuracy_measure'}
    return {'methods':methods,'bars':bars}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core-dir',type=Path,required=True);p.add_argument('--old-root',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--rescore',action='store_true')
    p.add_argument('--calibration',type=Path,default=Path('data/runs/phase-alignment/calibration-v2/calibration.json'))
    args=p.parse_args();torch.set_num_threads(2)
    calibration_path=args.calibration;calibration=read(calibration_path)
    if calibration['source_hashes']['phase_alignment.py']!=sha256(Path(__file__).with_name('phase_alignment.py')):
        raise ValueError('calibration version mismatch')
    manifest=read(args.core_dir/'manifest.json')
    if not manifest['complete']:p.error('core manifest must be complete')
    prediction_index(manifest)
    previous_path=args.output_dir/'manifest.json'
    previous=prediction_index(read(previous_path)) if previous_path.exists() else {}
    records={t['id']:t for t in read(args.old_root/'catalog-scored-audio.json')['tracks']}
    config={'core_manifest_path':str(args.core_dir/'manifest.json'),'core_manifest_sha256':sha256(args.core_dir/'manifest.json'),'strengths':list(STRENGTHS),
        'phase':asdict(PhaseConfig()),'calibration':{'path':str(calibration_path),'sha256':sha256(calibration_path)},
        'frozen_sources':source_fingerprint(PREDICTION_SOURCES),
        'evaluation_sources':source_fingerprint(('compare_clock_candidates.py','grid_metrics.py','bar_metrics.py','status_reanalysis_metrics.py')),
        'reference_used_for_prediction':False,'default_promoted':False,'new_algorithm_or_settings':False,
        'bar_scope':'separate unchanged-grid experiment; does not attach denominator to pulse groups'}
    target=args.output_dir/'configuration.json'
    if target.exists():
        prior=read(target)
        if {k:v for k,v in prior.items() if k!='evaluation_sources'}!={k:v for k,v in config.items() if k!='evaluation_sources'}:
            raise ValueError('refinement prediction configuration changed; use a new output directory')
        if prior['evaluation_sources']!=config['evaluation_sources'] and not args.rescore:
            raise ValueError('evaluation changed; explicit --rescore required')
    save(target,config);rows=[]
    # Every prediction is saved first. Reference event files are read only below.
    for item in manifest['rows']:
        if item['status']!='predictions_saved':continue
        path=Path(item['prediction_path']);core=read(path)
        target=args.output_dir/'predictions'/core['id']/(core['model']+'.json')
        if target.exists():
            if (core['id'],core['model']) not in previous:raise ValueError('unbound refinement prediction')
            value=read(target)
            if value['core_prediction_sha256']!=sha256(path):raise ValueError('core prediction changed')
            reuse=True
        else:
            value=build(core,args.output_dir,calibration)
            value.update(core_prediction_path=str(path),core_prediction_sha256=sha256(path))
            save(target,value);reuse=False
        rows.append({'id':core['id'],'cohort':core['cohort'],'model':core['model'],
            'evaluation_admission':item['evaluation_admission'],'prediction_path':str(target),
            'prediction_sha256':sha256(target),'prediction_reused':reuse})
        save(args.output_dir/'manifest.json',{'configuration':config,'rows':merge_prediction_rows(rows,list(previous.values())),'complete':False,
            'core_manifest_sha256':sha256(args.core_dir/'manifest.json'),'evaluation_only':True})
        print('PREDICT',core['id'],core['model'],'reuse' if reuse else round(value['elapsed_seconds'],2),flush=True)
    for row in rows:
        target=args.output_dir/'scores'/row['id']/(row['model']+'.json')
        if row['evaluation_admission']=='admitted_reference':
            ref=records[row['id']]['reference']
            if sha256(ref['path'])!=ref['sha256']:raise ValueError('reference changed')
            scores=score(read(ref['path']),read(row['prediction_path']))
            save(target,{'reference':ref,**scores});row['score_path']=str(target)
        if sha256(row['prediction_path'])!=row['prediction_sha256']:raise ValueError('prediction changed during scoring')
    save(args.output_dir/'manifest.json',{'configuration':config,'rows':rows,'complete':manifest['complete'],
         'core_manifest_sha256':sha256(args.core_dir/'manifest.json'),'evaluation_only':True})
    print('COMPLETE',len(rows),flush=True)

if __name__=='__main__':main()
