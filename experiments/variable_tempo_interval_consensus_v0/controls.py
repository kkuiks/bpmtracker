"""Requested logical controls; noise rates are measurements, not perfect-accuracy assertions."""
import argparse
import copy
import json
from pathlib import Path
import numpy as np
from .core import DEFAULT, predict, observation, clock_features, extract,refit
from .io import write,validate_source


def fixture(segments=((130,80),), lead=.137, silence=None, gap=None):
    events=[]; bars=[]; hypotheses=[]; t=lead; count=0
    for bpm,length in segments:
        p=60/bpm; phase=t % p
        hypotheses.append(dict(bpm=float(bpm),phase=phase,bars=[phase+j*p for j in range(4)],provenance='artificial_source_hypothesis'))
        for j in range(length):
            q=t+j*p
            if not gap or not gap[0]<=q<gap[1]:
                events.append(q)
                if (count+j)%4==0: bars.append(q)
        t+=length*p;count+=length
    duration=t+.4; n=int(round(duration*50)); beat=np.full(n,-12.);down=np.full(n,-12.)
    for ts,output in ((events,beat),(bars,down)):
        for v in ts:
            k=round(v*50)
            if k<n: output[k]=6.
    mask=np.zeros(n,dtype=bool)
    if silence: mask[(np.arange(n)/50>=silence[0])&(np.arange(n)/50<silence[1])]=True
    return dict(beat_logits=beat,downbeat_logits=down,fps=np.array(50),duration_seconds=np.array(duration),silent_frame_mask=mask),hypotheses


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    results=[]
    def check(name,condition,detail=None): results.append(dict(name=name,passed=bool(condition),detail=detail))
    data,h=fixture(); h+= [dict(bpm=65.,phase=.137,bars=[.137]),dict(bpm=260.,phase=.137,bars=[.137])]
    r=predict(data,h)
    check('fixed_clock_long_support',any(e['bpm']==130 and e['end']-e['start']>30 for e in r['accepted']))
    check('fixed_clock_no_wrong_nominal_support',all(e['bpm']==130 for e in r['accepted']))
    check('bar_phase_separately_supported',any(e['bar_status']=='SUPPORTED' for e in r['accepted']))
    wrong=copy.deepcopy(h[:1]);wrong[0]['bars']=[.137+60/130]
    w=predict(data,wrong)
    check('wrong_bar_does_not_erase_quarter',bool(w['accepted']) and all(e['bar_status']!='SUPPORTED' for e in w['accepted']))
    for middle,name in [(14,'same_phase'),(16,'different_phase')]:
        d,hs=fixture(((130,32),(140,middle),(130,32)))
        x=predict(d,hs)
        boundary1=.137+32*60/130;boundary2=boundary1+middle*60/140
        es=[e for e in x['episodes'] if e['bpm']==130]
        check('tempo_return_'+name+'_separate_episodes',len(es)>=2,dict(episodes=len(es)))
        check('tempo_return_'+name+'_no_contradiction_bridge',not any(e['start']<boundary1-1 and e['end']>boundary2+1 for e in es))
    silent=copy.deepcopy(data);silent['silent_frame_mask'][:]=True
    check('strong_neural_peaks_in_digital_silence_abstain',not predict(silent,h)['episodes'])
    g,hs=fixture(gap=(10,20));x=predict(g,hs)
    check('no_event_gap_has_no_claimed_support',not any(e['start']<=15<e['end'] for e in x['accepted']))
    # An exact array-coordinate shift is different from re-running the neural model on padded audio.
    shift=1.4; shifted={k:v.copy() if hasattr(v,'copy') else v for k,v in data.items()}
    for key in ('beat_logits','downbeat_logits'): shifted[key]=np.r_[np.full(70,-12.),data[key]]
    shifted['silent_frame_mask']=np.r_[np.ones(70,dtype=bool),data['silent_frame_mask']]
    shifted['duration_seconds']=np.array(float(data['duration_seconds'])+shift)
    hh=[dict(v,phase=(v['phase']+shift)%(60/v['bpm']),bars=[b+shift for b in v['bars']]) for v in h]
    y=predict(shifted,hh)
    orig=[(e['bpm'],e['start'],e['end']) for e in r['episodes']]
    moved=[(e['bpm'],e['start']-shift,e['end']-shift) for e in y['episodes']]
    check('source_grid_shift_invariance',len(orig)==len(moved) and all(u[0]==v[0] and abs(u[1]-v[1])<=.25 and abs(u[2]-v[2])<=.25 for u,v in zip(orig,moved)),dict(original=orig,shifted=moved))
    initial=dict(initial_bpm=130.,bpm_unit_quarters=1.,scope='initial_audio_section',origin='constructed_assumption')
    unit=[predict(data,h,initial=dict(initial,initial_bpm=value),policy='initial_unit') for value in (125,130,135)]
    check('same_layer_inputs_identical_complete_unit_predictions',json.dumps(unit[0],sort_keys=True)==json.dumps(unit[1],sort_keys=True)==json.dumps(unit[2],sort_keys=True))
    # Initial exact BPM does not create an unsupported clock.
    bad=predict(data,h,initial=dict(initial,initial_bpm=137),policy='initial_exact')
    scope=bad['initial_information_scope']
    check('initial_information_cannot_create_missing_clock',not any(e['start']<(scope or [0,0])[1] and e['end']>(scope or [0,0])[0] for e in bad['accepted']))
    def outside(result,scope):
        return [(e['bpm'],e['phase'],max(e['start'],scope[1]),e['end']) for e in result['accepted'] if e['end']>scope[1]]
    check('initial_exact_input_has_no_later_direct_effect',outside(bad,scope)==outside(r,scope))
    octave,oh=fixture(((160,32),(80,32)))
    oi=dict(initial,initial_bpm=160.)
    oo=predict(octave,oh,dict(quality_threshold=.55),initial=oi,policy='initial_exact')
    check('initial_scope_stops_observable_octave_regime_change',oo['initial_information_scope'][1]<16.,oo['initial_information_scope'])
    wrapped,wh=fixture(lead=.465)
    wh[0]['phase']=.45;wh[0]['bars']=[.45]
    wc=dict(DEFAULT,quality_threshold=.55)
    before=predict(wrapped,wh,wc)
    after=predict(wrapped,wh,wc,refinement='phase')
    check('source_phase_refit_has_evidence',bool(before['accepted']) and bool(after['accepted']))
    check('phase_refit_preserves_bar_wrap',bool(after['episodes']) and abs(after['episodes'][0]['bar_phase']-.465)<.025)
    check('determinism',r==predict(data,h))
    check('duplicate_hypotheses_no_extra_wrong_support',all(e['bpm']==130 for e in predict(data,h+h)['accepted']))
    empty=dict(beat_logits=np.array([]),downbeat_logits=np.array([]),fps=np.array(50),duration_seconds=np.array(0.))
    check('empty_input_unknown',not predict(empty,[])['accepted'])
    failed=False
    try:
        malformed=copy.deepcopy(data);malformed['beat_logits'][0]=np.nan;predict(malformed,h)
    except ValueError: failed=True
    check('nonfinite_rejected',failed)
    failed=False
    try: validate_source(dict(id='x',evidence_path='/tmp/x',duration_seconds=1,fps=50,reference_path='/does/not/exist'))
    except ValueError: failed=True
    check('reference_fields_rejected',failed)
    # Predictor accepts arrays only: inaccessible reference paths cannot be consulted by it.
    check('array_predictor_has_no_reference_argument',predict(data,h)['reference_fields_read'] is False)
    # A declared source clock outside the representable vocabulary remains outside it.
    probe,hs=fixture(((120.1,240),)); hs[0]['bpm']=120.;hs[0]['phase']=.137
    z=predict(probe,hs)
    check('vocabulary_drift_not_fabricated_new_rate',all(e['bpm']==120 for e in z['episodes']))
    noise=[]
    for seed in range(12):
        rng=np.random.default_rng(8700+seed); n=3000; beat=np.full(n,-12.); down=beat.copy()
        times=np.sort(rng.uniform(0,60,180)); pos=np.unique(np.minimum(n-1,np.rint(times*50).astype(int)));beat[pos]=rng.uniform(0,5,len(pos))
        d=dict(beat_logits=beat,downbeat_logits=down,fps=np.array(50),duration_seconds=np.array(60.))
        pool=[dict(bpm=float(rate),phase=float(phi),bars=[float(phi)]) for rate in (60,80,100,120,140,160,180,200) for phi in (.0,.07,.17,.29)]
        result=predict(d,pool)
        noise.append(dict(seed=seed,episodes=len(result['episodes']),maximum_integral=max((e['integral_score'] for e in result['episodes']),default=0.)))
    # Identical NN evidence from two different non-silent source realities cannot be distinguished by A.
    limitations={'non_silent_consistent_sensor_placebo_identifiability':'Same supplied logits and silence mask necessarily give the same A output; PCM corroboration is a later experiment, not silently available here.'}
    report=dict(checks=results,mandatory_passed=all(r['passed'] for r in results),noise_measurements=noise,
                software_controls_are_not_music_accuracy=True,identified_sensor_limit=limitations)
    write(a.run/'controls-v1.json',report)
    print(json.dumps(dict(checks=len(results),passed=sum(r['passed'] for r in results),failures=[r for r in results if not r['passed']]),ensure_ascii=False),flush=True)
    if not report['mandatory_passed']: raise SystemExit(1)


if __name__=='__main__':main()
