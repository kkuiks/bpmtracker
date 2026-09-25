"""Frozen-config baseline comparison on audited public development catalogs.

References are used only for scoring after all prediction paths are produced.
No reference-informed octave choice, time offset, tempo prior or tuning occurs.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import torch
from beat_this.inference import Audio2Frames
from beat_this.model.postprocessor import Postprocessor

from fit_clock import fit_clock, propose_splits, clock_time
from inspect_inputs import sha256
from legacy_dbn import decode_dbn_from_logits
from run_beat_this import installed_versions, validate_events
from synthetic_groove import event_metrics


def score_events(reference, prediction, skip_seconds):
    lower, upper = reference['evaluation_support_seconds']
    lower = max(lower, skip_seconds)
    scores = {}
    for key in ('beats_seconds','downbeats_seconds'):
        if reference[key] is None:
            scores[key] = None
            continue
        truth = validate_events(reference[key])
        estimated = validate_events(prediction[key])
        truth = truth[(truth >= lower)&(truth <= upper)]
        estimated = estimated[(estimated >= lower)&(estimated <= upper)]
        scores[key] = {str(tolerance):event_metrics(truth,estimated,tolerance)
                       for tolerance in (.01,.02,.03,.07)}
    return scores


def score_clock(reference, proposal):
    if not reference.get('tempo_events') or proposal is None:
        return None
    times = np.array(reference['beats_seconds'])
    segments = proposal['segments']
    keep = (times >= segments[0]['start_seconds']) & (times <= segments[-1]['end_seconds'])
    eligible = times[keep]
    reference_changes = np.array([e['time_seconds'] for e in reference['tempo_events']])
    reference_rates = np.array([e['bpm_quarter'] for e in reference['tempo_events']])
    predicted_starts = np.array([s['start_seconds'] for s in segments])
    predicted_rates = np.array([s['pulse_rate_per_minute'] for s in segments])
    truth = reference_rates[np.searchsorted(reference_changes,eligible,side='right')-1]
    estimated = predicted_rates[np.searchsorted(predicted_starts,eligible,side='right')-1]
    lo,hi = reference['evaluation_support_seconds']
    changes = reference_changes[1:]
    changes = changes[(changes > lo)&(changes < hi)]
    predicted = predicted_starts[1:]
    predicted = predicted[(predicted > lo)&(predicted < hi)]
    return {'covered_reference_pulse_fraction':float(np.mean(keep)) if len(times) else None,
            'quarter_rate_mae':float(np.mean(abs(estimated-truth))) if len(eligible) else None,
            'median_predicted_to_reference_rate_ratio':float(np.median(estimated/truth)) if len(eligible) else None,
            'reference_change_count':len(changes),'predicted_change_count':len(predicted),
            'changes_0_5s':event_metrics(changes,predicted,.5) if len(changes) else None,
            'false_changes_on_constant_reference':len(predicted) if len(changes)==0 else None}


def summarize(results):
    summary = {}
    for dataset in sorted({r['dataset'] for r in results}):
        subset = [r for r in results if r['dataset']==dataset]
        variants = {}
        for variant in ('official_minimal','legacy_dbn','clock_pipeline'):
            entry = {}
            for scope in ('annotated_span','after_5_seconds'):
                entry[scope] = {}
                for key in ('beats_seconds','downbeats_seconds'):
                    scores=[r['scores'][variant][scope][key] for r in subset if r['scores'][variant][scope][key] is not None]
                    entry[scope][key]={'track_count':len(scores), 'macro_f1':{
                        str(t):float(np.mean([s[str(t)]['f1'] for s in scores])) if scores else None
                        for t in (.01,.02,.03,.07)}}
            variants[variant]=entry
        summary[dataset]={'track_count':len(subset),'variants':variants,
                          'clock_fallback_count':sum(r['clock_status'].startswith('fallback') for r in subset)}
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,nargs='+',required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists() or not args.checkpoint.is_file():
        parser.error('output must be new and checkpoint must exist locally')
    if args.device=='cuda' and not torch.cuda.is_available():
        parser.error('CUDA unavailable; verify device access or explicitly choose CPU')
    tracks=[]
    for catalog in args.catalog:
        tracks.extend(json.loads(catalog.read_text())['tracks'])
    if len({t['id'] for t in tracks}) != len(tracks):
        parser.error('duplicate track IDs')
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision('highest')
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    args.output_dir.mkdir(parents=True)
    configuration={'checkpoint_sha256':sha256(args.checkpoint),'device':args.device,'precision':'float32',
                   'catalogs':[{'path':str(p),'sha256':sha256(p)} for p in args.catalog],
                   'versions':installed_versions(),'runner_sha256':sha256(__file__),
                   'decoder_sha256':sha256(Path(__file__).with_name('legacy_dbn.py')),
                   'fitter_sha256':sha256(Path(__file__).with_name('fit_clock.py')),
                   'clock_config':{'min_events':8,'split_penalty':.01,'continuous_selection':False,
                                   'max_input_events':2000,'max_initial_segments':12,'fallback':'raw DBN'},
                   'reference_offset_seconds':0,'octave_selection':'none','initial_seconds_skipped_for_inference':0}
    (args.output_dir/'configuration.json').write_text(json.dumps(configuration,indent=2)+'\n')
    model=Audio2Frames(checkpoint_path=str(args.checkpoint.resolve()),device=args.device,float16=False)
    minimal=Postprocessor(type='minimal',fps=50)
    results=[]
    for index,track in enumerate(tracks):
        started=time.perf_counter()
        input_path=Path(track['input']['path'])
        reference_path=Path(track['reference']['path'])
        if sha256(input_path)!=track['input']['sha256'] or sha256(reference_path)!=track['reference']['sha256']:
            raise ValueError('catalog asset changed')
        target=args.output_dir/track['id']
        target.mkdir()
        if track['input']['kind']=='audio':
            audio,sr=sf.read(input_path,dtype='float32',always_2d=True)
            beat_logits,downbeat_logits=model(audio,sr)
        else:
            spect=np.load(input_path,allow_pickle=False)
            beat_logits,downbeat_logits=model.spect2frames(torch.as_tensor(spect,device=args.device,dtype=torch.float32))
        if args.device=='cuda':torch.cuda.synchronize()
        inferred=time.perf_counter()
        beat=beat_logits.detach().cpu().numpy()
        downbeat=downbeat_logits.detach().cpu().numpy()
        np.savez_compressed(target/'logits.npz',beat=beat,downbeat=downbeat,fps=np.array(50))
        beats,downbeats=minimal(beat_logits,downbeat_logits)
        dbn_beats,dbn_downbeats,numbers=decode_dbn_from_logits(beat,downbeat)
        variants={'official_minimal':{'beats_seconds':beats.tolist(),'downbeats_seconds':downbeats.tolist()},
                  'legacy_dbn':{'beats_seconds':dbn_beats.tolist(),'downbeats_seconds':dbn_downbeats.tolist()}}
        proposal=None
        clock_status='fallback_insufficient_events'
        if len(dbn_beats)>=8:
            boundaries=propose_splits(dbn_beats)
            if len(dbn_beats)<=2000 and len(boundaries)-1<=12:
                try:
                    proposal=fit_clock(dbn_beats)
                    grid=clock_time(np.arange(len(dbn_beats)),proposal['knot_pulse_indices'],proposal['coefficients'])
                    variants['clock_pipeline']={'beats_seconds':grid[grid>=0].tolist(),
                        'downbeats_seconds':grid[(numbers==1)&(grid>=0)].tolist()}
                    clock_status=proposal['status']
                except ValueError as error:
                    clock_status='fallback_invalid_fit: '+str(error)
            else:
                clock_status='fallback_fixed_complexity_budget'
        if proposal is None:
            variants['clock_pipeline']=dict(variants['legacy_dbn'])
        # Only now consume labels for evaluation. They never enter inference,
        # decoder, model selection, octave choice or clock fitting.
        reference=json.loads(reference_path.read_text())
        scores={name:{'annotated_span':score_events(reference,prediction,0),
                      'after_5_seconds':score_events(reference,prediction,5)} for name,prediction in variants.items()}
        row={'id':track['id'],'dataset':track['dataset'],'genre':track['genre'],'group_id':track['group_id'],
             'input_sha256':track['input']['sha256'],'reference_sha256':track['reference']['sha256'],
             'duration_seconds':track['duration_seconds'],'variants':variants,'clock':proposal,'clock_status':clock_status,
             'scores':scores,'clock_metrics':score_clock(reference,proposal),
             'timing_seconds':{'inference_and_input_load':inferred-started,'total':time.perf_counter()-started}}
        (target/'result.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
        results.append(row)
        report={'configuration':configuration,'summary':summarize(results),'tracks':results,
                'completed_tracks':len(results),'planned_tracks':len(tracks),'complete':len(results)==len(tracks)}
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        f1=scores['official_minimal']['annotated_span']['beats_seconds']['0.07']['f1']
        print(f"{index+1}/{len(tracks)} {track['id']}: beat F1@70ms={f1:.3f}, {clock_status}, {row['timing_seconds']['total']:.1f}s",flush=True)


if __name__=='__main__':
    main()
