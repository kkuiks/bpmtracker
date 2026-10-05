"""Measure attack timing on declared synthetic events, never creator labels."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from analyze_onsets import spectral_flux
from inspect_inputs import sha256
from phase_alignment import AttackConfig, BANDS, extract_attacks


def fixture(kind,sample_rate,seed):
    rng=np.random.default_rng(seed);duration=1.2
    audio=np.zeros(round(duration*sample_rate),dtype=np.float32)
    when=.25+rng.uniform(0,.01);start=round(when*sample_rate)
    t=np.arange(round(.12*sample_rate))/sample_rate
    if kind=='impulse':sound=np.r_[1.,np.zeros(len(t)-1)]
    elif kind=='noise':sound=rng.normal(0,1,len(t))*np.exp(-t*60)
    elif kind=='clap':sound=np.r_[0,np.diff(rng.normal(0,1,len(t))) ]*np.exp(-t*90)*np.minimum(1,t/.001)
    elif kind=='kick':sound=np.sin(2*np.pi*(45*t+80*.025*(1-np.exp(-t/.025))))*np.exp(-t*30)
    elif kind=='wood':sound=np.sin(2*np.pi*900*t)*np.exp(-t*150)
    elif kind=='slow':sound=rng.normal(0,1,len(t))*np.minimum(1,t/.030)*np.exp(-t*20)
    else:raise ValueError('unknown synthetic attack')
    gain=rng.uniform(.05,.8);sound=sound/max(abs(sound))*gain
    audio[start:start+len(sound)]=sound
    return audio,start/sample_rate


def measure(group,seeds,config):
    rows=[]
    for rate in (16000,44100,48000):
        for kind in ('impulse','noise','clap','kick','wood','slow'):
            for seed in seeds:
                audio,target=fixture(kind,rate,seed)
                attacks=extract_attacks(audio,rate,config)
                row={'group':group,'sample_rate':rate,'kind':kind,'seed':seed,'target_seconds':target,'bands':{}}
                for band in BANDS:
                    values=attacks['bands'][band];t=np.asarray(values['seconds']);strength=np.asarray(values['strength'])
                    near=np.flatnonzero(abs(t-target)<=.060)
                    # Strongest local evidence, not the candidate closest to the
                    # known annotation: this prevents optimistic calibration.
                    index=near[np.argmax(strength[near])] if len(near) else None
                    row['bands'][band]=None if index is None else {'seconds':float(t[index]),
                        'error_seconds':float(t[index]-target),'rise_seconds':values['rise_seconds'][index]}
                rows.append(row)
    return rows


def calibrate():
    config=AttackConfig();training=measure('calibration',range(4),config);validation=measure('validation',range(100,104),config)
    result={'schema_version':'synthetic-attack-calibration-v1','synthetic_only':True,'reference_music_used':False,
            'configuration':asdict(config),'bands':{},'calibration_rows':training,'validation_rows':validation,
            'scope':'fast synthetic attack timing; no real-music precision guarantee','slow_attacks_excluded_from_bias_estimation':True}
    for band in BANDS:
        fit=[r['bands'][band]['error_seconds'] for r in training if r['kind']!='slow' and r['bands'][band] is not None]
        bias=float(np.median(fit))
        eligible=[r for r in validation if r['kind']!='slow'];errors=[r['bands'][band]['error_seconds']-bias for r in eligible if r['bands'][band] is not None]
        recall=len(errors)/len(eligible);p95=float(np.percentile(abs(np.asarray(errors)),95))
        slow=[r['bands'][band]['error_seconds']-bias for r in validation if r['kind']=='slow' and r['bands'][band] is not None]
        result['bands'][band]={'bias_seconds':bias,'fast_validation_detection_fraction':recall,
            'fast_validation_p95_absolute_seconds':p95,'fast_validation_max_absolute_seconds':float(max(abs(np.asarray(errors)))),
            'slow_validation_p95_absolute_seconds':float(np.percentile(abs(np.asarray(slow)),95)) if slow else None,
            'eligible':recall>=.9 and p95<=.005}
    # Preserve the earlier diagnostic, including its normalization/clipping
    # dependence; it does not establish a universal 21 ms latency.
    examples=[]
    for seed in range(4):
        audio,target=fixture('impulse',22050,seed)
        t,flux=spectral_flux(audio,22050)
        examples.append({'target_seconds':target,'maximum_seconds':float(t[np.argmax(flux.mean(axis=1))])})
    result['legacy_clipped_flux_impulse_examples']=examples
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if args.output.exists():parser.error('output must be new')
    result=calibrate();result['source_hashes']={n:sha256(Path(__file__).with_name(n)) for n in ('phase_alignment.py','calibrate_phase_attacks.py','analyze_onsets.py')}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as handle:json.dump(result,handle,indent=2,allow_nan=False);handle.write('\n')
    print(json.dumps(result['bands'],indent=2))


if __name__=='__main__':main()
