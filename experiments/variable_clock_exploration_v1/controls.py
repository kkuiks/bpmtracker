"""Necessary constructed observation controls for the requested exploration."""
import argparse
import json
from pathlib import Path

import numpy as np

from .clock import predict


def sensor(segments,noise=0.,missing=False,phase_jump=False,clutter=False):
    rng=np.random.default_rng(8801);times=[];t=.137
    for i,(bpm,beats) in enumerate(segments):
        if phase_jump and i:t+=.2
        for _ in range(beats):times.append(t);t+=60/bpm
    times=np.asarray(times)
    if missing:times=times[np.arange(len(times))%7!=3]
    times=times+rng.normal(0,noise,len(times))
    duration=t+.6;axis=np.arange(int(np.ceil(duration*50)))/50
    probability=np.full(len(axis),.003)
    for point in times:
        probability=np.maximum(probability,.97*np.exp(-.5*((axis-point)/.009)**2))
    if clutter:
        for point in times[::9]+.17:
            probability=np.maximum(probability,.30*np.exp(-.5*((axis-point)/.009)**2))
    probability=np.clip(probability,1e-5,1-1e-5)
    return {'beat_logits':np.log(probability/(1-probability)),'fps':np.array(50),
            'duration_seconds':np.array(duration)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--only-method');a=p.parse_args()
    cases={
        'fixed_clean':([(120,128)],{}),
        'fixed_fractional':([(131.25,128)],{}),
        'fixed_frame_noise':([(120,128)],{'noise':.009}),
        'fixed_missing_pulses':([(120,128)],{'missing':True}),
        'fixed_clutter':([(120,128)],{'clutter':True}),
        'fixed_unrepresentable_120_1':([(120.1,512)],{}),
        'same_rate_phase_reset':([(120,64),(120,64)],{'phase_jump':True}),
        'step_return':([(120,64),(144,32),(120,32)],{}),
        'short_four_quarters':([(130,64),(140,4),(130,64)],{}),
        'octave_step':([(160,64),(80,64)],{}),
        'small_quarter_bpm_step':([(120,128),(120.25,128)],{}),
    }
    results=[]
    for name,(segments,options) in cases.items():
        data=sensor(segments,**options)
        for method in ((a.only_method,) if a.only_method else ('affine_mdl','multiscale','transport')):
            value=predict(data,method,16)
            changes=sum(b['kind']=='rate_change' for b in value['boundaries'])
            truth=sum(a[0]!=b[0] for a,b in zip(segments,segments[1:]))
            results.append({'case':name,'method':method,'expected_rate_changes':truth,
                            'proposed_rate_changes':changes,'rates':[r['bpm'] for r in value['regions']],
                            'rate_change_count_matches':changes==truth})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({'constructed_observation_controls_only':True,
                                   'not_audio_or_real_music_accuracy':True,'rows':results},indent=2)+'\n')
    for row in results:
        if not row['rate_change_count_matches']:print('LIMIT',json.dumps(row),flush=True)
    print('CONTROL OUTCOMES',len(results),sum(r['rate_change_count_matches'] for r in results),flush=True)


if __name__=='__main__':main()
