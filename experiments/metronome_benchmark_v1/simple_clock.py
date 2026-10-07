"""A same-output baseline: event intervals, robust linear clocks and bar phases.

No spectrum, original clock objective, or reference clock enters preparation.
Every candidate and its unit group is fixed before numeric hints are read.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from experiments.metronome_reconstruction_v1.grid import timestamps
from experiments.metronome_reconstruction_v1.hinted import encode_tap_level, validate_hint_row
from experiments.metronome_reconstruction_v1.infer import make_evidence
from .inference import decorate, validate_source, write_json
from .metrics import event_f1


def weighted_median(values, weights):
    order=np.argsort(values)
    cumulative=np.cumsum(weights[order])
    return float(values[order[np.searchsorted(cumulative,cumulative[-1]/2)]])


def period_seeds(evidence, model, config):
    times=evidence['channels']['beat']['events']
    weights=evidence['channels']['beat']['weights']
    low, high=60/model['bpm_max'],60/model['bpm_min']
    seeds=[]
    for lag in range(1,min(5,len(times))):
        gaps=(times[lag:]-times[:-lag])/lag
        w=np.minimum(weights[lag:],weights[:-lag])
        valid=(gaps>=low)&(gaps<=high)
        if valid.any():
            seeds.append(weighted_median(gaps[valid],w[valid]))
    if len(times)>1:
        gaps=np.diff(times)
        step=config['histogram_step_seconds']
        bins=np.arange(low,high+2*step,step)
        counts,_=np.histogram(gaps,bins=bins,weights=np.minimum(weights[1:],weights[:-1]))
        peaks,_=find_peaks(counts)
        for index in sorted(peaks,key=lambda index:counts[index],reverse=True)[:3]:
            center=(bins[index]+bins[index+1])/2
            nearby=abs(gaps-center)<=2*step
            if nearby.any():
                seeds.append(float(np.median(gaps[nearby])))
    down=evidence['channels']['downbeat']['events']
    if len(down)>2:
        bar=float(np.median(np.diff(down)))
        seeds.extend(bar/meter for meter in model['meters'] if low<=bar/meter<=high)
    unique=[]
    for seed in seeds:
        if not any(abs(seed-old)<=.002 for old in unique):
            unique.append(seed)
    return unique[:config['seed_limit']]


def phase_seed(times, weights, period, limit):
    if not len(times):
        return None
    anchors=np.remainder(times[np.argsort(weights)[-limit:]],period)
    differences=(times[None,:]-anchors[:,None]+period/2)%period-period/2
    losses=(np.minimum(abs(differences),.08)*weights).sum(axis=1)
    phase=float(anchors[np.argmin(losses)])
    residual=(times-phase+period/2)%period-period/2
    keep=abs(residual)<=min(.08,period*.4)
    if keep.any():
        phase+=weighted_median(residual[keep],weights[keep])
    return phase%period


def fit_clock(times, weights, initial_period, phase, model, config):
    if phase is None:
        return None
    period, origin=initial_period,phase
    for _ in range(config['robust_iterations']):
        indices=np.rint((times-origin)/period)
        residual=times-(origin+indices*period)
        keep=abs(residual)<=min(.16,period*.4)
        if keep.sum()<4 or np.ptp(indices[keep])<=0:
            return None
        x=indices[keep]
        w=weights[keep]*np.minimum(1,config['huber_seconds']/np.maximum(abs(residual[keep]),1e-8))
        design=np.column_stack((np.ones(len(x)),x))
        coefficients=np.linalg.lstsq(design*np.sqrt(w[:,None]),times[keep]*np.sqrt(w),rcond=None)[0]
        origin,period=map(float,coefficients)
        if period<=0 or abs(period/initial_period-1)>config['period_relative_refinement_limit']:
            return None
    bpm=Fraction(60/period).limit_denominator(model['denominator_max'])
    if not model['bpm_min']<=float(bpm)<=model['bpm_max']:
        return None
    rational_period=60/float(bpm)
    indices=np.rint((times-origin)/period)
    residual=times-(origin+indices*period)
    keep=abs(residual)<=min(.16,period*.4)
    if keep.sum()<4:
        return None
    phase=weighted_median(times[keep]-indices[keep]*rational_period,weights[keep])%rational_period
    return bpm,float(phase)


def score_clock(evidence,bpm,phase,meter,model,config):
    period=60/float(bpm)
    offset=phase%(meter*period)
    values={}
    for name,p in [('beat',period),('downbeat',period*meter)]:
        predicted=timestamps(p,offset,evidence['duration']).tolist()
        observed=evidence['channels'][name]['events'].tolist()
        tolerance=min(model['matching_window_seconds'],p*model['matching_period_fraction'])
        values[name]=event_f1(predicted,observed,tolerance)
    score=config['beat_weight']*values['beat']['f1']+config['downbeat_weight']*values['downbeat']['f1']
    return {'quarter_bpm':float(bpm),'bpm_fraction':{'numerator':bpm.numerator,'denominator':bpm.denominator},
        'period_seconds':period,'time_signature':{'numerator':meter,'denominator':4},
        'offset_seconds':offset,'score':score,'beat_source_f1':values['beat']['f1'],
        'downbeat_source_f1':values['downbeat']['f1']}


def prepare_family(evidence,model,config):
    channels=evidence['channels']
    times,weights=channels['beat']['events'],channels['beat']['weights']
    if len(times)<model['minimum_audio_peak_events']:
        return {'status':'insufficient_acoustic_evidence','candidates':[],'config':config}
    seeds=period_seeds(evidence,model,config)
    candidates={}
    for seed in seeds:
        for power in config['hypothesis_powers']:
            period=seed*2**power
            if not 60/model['bpm_max']<=period<=60/model['bpm_min']:
                continue
            phases=[phase_seed(channel['events'],channel['weights'],period,config['phase_anchor_limit'])
                    for channel in [channels['beat'],channels['downbeat']]]
            for phase in phases:
                fitted=fit_clock(times,weights,period,phase,model,config)
                if fitted is None:
                    continue
                bpm,phase=fitted
                for meter in model['meters']:
                    for index in range(meter):
                        row=score_clock(evidence,bpm,phase+index*60/float(bpm),meter,model,config)
                        key=(bpm,meter,round(row['offset_seconds'],8))
                        candidates[key]=row
    ranked=sorted(candidates.values(),key=lambda row:row['score'],reverse=True)
    if not ranked:
        return {'status':'insufficient_acoustic_evidence','candidates':[],'config':config}
    base=ranked[0]['quarter_bpm']
    for row in ranked:
        row['layer_power']=math.floor(math.log2(row['quarter_bpm']/base)+.5)
    return {'status':'audio_family_prepared','audio_base_bpm':base,'candidates':ranked,
            'period_seeds_seconds':seeds,'config':config,'all_candidates_prepared_before_hint':True}


def select(family,hint=None):
    if family['status']!='audio_family_prepared':
        return {'status':'insufficient_acoustic_evidence','quarter_bpm':None,'period_seconds':None,
                'time_signature':None,'offset_seconds':None}
    decision=encode_tap_level(family['audio_base_bpm'],hint) if hint is not None else {'status':'not_provided','power':None}
    candidates=family['candidates']
    if hint is not None:
        candidates=[row for row in candidates if row['layer_power']==decision['power']] if decision['power'] is not None else []
    if not candidates:
        return {'status':'tap_unit_not_supported_by_audio_family','quarter_bpm':None,'period_seconds':None,
                'time_signature':None,'offset_seconds':None,'tap_unit_decision':decision}
    best=candidates[0]
    rivals=[row for row in candidates[1:] if row['quarter_bpm']!=best['quarter_bpm']
            or row['time_signature']!=best['time_signature']
            or abs((row['offset_seconds']-best['offset_seconds']+best['period_seconds']*best['time_signature']['numerator']/2)
                   %(best['period_seconds']*best['time_signature']['numerator'])
                   -best['period_seconds']*best['time_signature']['numerator']/2)>best['period_seconds']/2]
    flags=[]
    if rivals and best['score']-rivals[0]['score']<family['config']['ambiguity_margin']:
        flags.append('close_competing_clock')
    for channel in ['beat','downbeat']:
        if best[channel+'_source_f1']<family['config']['minimum_agreement']:
            flags.append('weak_'+channel+'_agreement')
    return {**best,'status':'uncertain_fixed_map_proposal' if flags else 'fixed_map_proposal',
            'confidence_flags':flags,'confidence_flags_uncalibrated':True,
            'initial_tap_provided':hint is not None,'tap_unit_decision':decision,
            'audio_base_bpm':family['audio_base_bpm'],'raw_tap_number_used_after_unit_selection':False,
            'time_signature_supplied':False,'all_candidates_and_scores_prepared_before_hint':True,
            'method':'robust event-index constant-clock fit v1'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','select'])
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--model-config',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('simple-clock-v1.json'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--hints',type=Path)
    args=parser.parse_args()
    rows=json.loads(args.source.read_text())['samples'];validate_source(rows)
    config=json.loads(args.config.read_text());model=json.loads(args.model_config.read_text())
    if args.stage=='prepare':
        if args.output.exists():
            raise ValueError('Use a new baseline output')
        args.output.mkdir(parents=True)
        receipt={'started_at_utc':datetime.now(timezone.utc).isoformat(),'reference_files_read':False,
                 'hint_files_read':False,'configuration':config,'samples':[]}
        for index,row in enumerate(rows,1):
            print(f'BASELINE {index}/{len(rows)} {row["id"]}',flush=True)
            try:
                with np.load(args.evidence/f'{row["id"]}.npz',allow_pickle=False) as data:
                    if int(data['fps'])!=model['fps'] or abs(float(data['duration_seconds'])-row['duration_seconds'])>1e-8:
                        raise ValueError('Cached observation coordinates differ from source contract')
                    evidence=make_evidence(data['beat_logits'],data['downbeat_logits'],row['duration_seconds'],model)
                family=prepare_family(evidence,model,config)
                write_json(args.output/'families'/f'{row["id"]}.json',family)
                prediction=decorate(select(family),row['duration_seconds'])
            except Exception as exc:
                prediction={'status':'inference_failed','error':f'{type(exc).__name__}: {exc}'}
            write_json(args.output/'predictions/audio_only'/f'{row["id"]}.json',prediction)
            receipt['samples'].append({'id':row['id'],'status':prediction['status']})
        receipt['all_families_prepared_at_utc']=datetime.now(timezone.utc).isoformat()
        write_json(args.output/'receipt.json',receipt)
    else:
        receipt=json.loads((args.output/'receipt.json').read_text())
        if 'all_families_prepared_at_utc' not in receipt or args.hints is None:
            raise ValueError('Prepared audio families and a separate hint file are required')
        hints=json.loads(args.hints.read_text())['samples']
        if len(hints)!=len(rows) or {row['id'] for row in hints}!={row['id'] for row in rows}:
            raise ValueError('Source and hint identities differ')
        durations={row['id']:row['duration_seconds'] for row in rows}
        for hint in hints:
            validate_hint_row(hint)
            try:
                family=json.loads((args.output/'families'/f'{hint["id"]}.json').read_text())
                prediction=decorate(select(family,hint['initial_quarter_bpm_tap']),durations[hint['id']])
            except Exception as exc:
                prediction={'status':'inference_failed','error':f'{type(exc).__name__}: {exc}'}
            write_json(args.output/'predictions/correct_unit_diagnostic'/f'{hint["id"]}.json',prediction)
        receipt['unit_selection_completed_at_utc']=datetime.now(timezone.utc).isoformat()
        receipt['reference_unit_hints_are_diagnostic']=True
        write_json(args.output/'receipt.json',receipt)


if __name__=='__main__':
    main()
