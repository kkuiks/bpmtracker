"""Paired musical controls with explicitly scheduled sample-clock coordinates.

The synthesizer is deterministic and uses analytic drum/bass/chord voices.
A separate transport-marker WAV establishes the clock/audio coordinate relation;
it is never included in the music supplied to the observation model.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from .inference import write_json


RATE=32000
VARIANTS=['straight','weak_downbeat','syncopated','half_time','double_time','dropout','leading_shift']
PARENTS=[(60,3),(Fraction(250,3),3),(120,3),(179,3),(80,4),(103,4),(Fraction(257,2),4),(197,4)]


def frame_at(quarter,bpm,lead):
    value=(lead+quarter*Fraction(60,1)/bpm)*RATE
    # Renderer uses integer quotient/remainder rounding, independently of the
    # reference evaluator's ceil arithmetic on the ideal periodic clock.
    whole,remainder=divmod(value.numerator,value.denominator)
    return whole+(2*remainder>=value.denominator)


def voice(kind,pitch,velocity,rng):
    duration={'kick':.38,'snare':.2,'hat':.085,'bass':.32,'chord':.7}[kind]
    t=np.arange(round(duration*RATE))/RATE
    if kind=='kick':
        phase=2*np.pi*(48*t+85*.018*(1-np.exp(-t/.018)))
        signal=np.sin(phase)*np.exp(-t/.095)+.08*rng.normal(size=len(t))*np.exp(-t/.004)
    elif kind=='snare':
        noise=rng.normal(size=len(t));noise=np.r_[noise[0],np.diff(noise)]
        signal=(.5*noise+.25*np.sin(2*np.pi*185*t))*np.exp(-t/.06)
    elif kind=='hat':
        noise=rng.normal(size=len(t));noise=np.r_[noise[0],np.diff(noise)]
        signal=.22*noise*np.exp(-t/.018)
    else:
        frequency=440*2**((pitch-69)/12)
        harmonics=range(1,5) if kind=='bass' else range(1,4)
        signal=sum(np.sin(2*np.pi*frequency*harmonic*t)/harmonic for harmonic in harmonics)
        signal*=np.minimum(t/.004,1)*np.exp(-t/(.15 if kind=='bass' else .35))*.18
    signal*=np.minimum(t/.0006,1)*velocity
    return signal.astype(np.float64)


def render_case(directory,ident,bpm,meter,seed,variant,bars=None):
    bpm=Fraction(bpm);lead=Fraction(137,1000)+(Fraction(317,1000) if variant=='leading_shift' else 0)
    period=Fraction(60,1)/bpm
    bars=bars or max(12,math.ceil(Fraction(40,1)/(period*meter)))
    quarters=bars*meter
    musical_end=lead+quarters*period
    frames=math.ceil((musical_end+Fraction(1,1))*RATE)
    music=np.zeros(frames,dtype=np.float64)
    marker=np.zeros(frames,dtype=np.float64)
    rng=np.random.default_rng(seed)
    ledger=[]
    def add(q,kind,pitch=36,gain=1):
        if variant=='dropout' and quarters*Fraction(2,5)<=q<quarters*Fraction(3,5):return
        start=frame_at(q,bpm,lead)
        signal=voice(kind,pitch,gain,rng)
        end=min(len(music),start+len(signal))
        if 0<=start<end:
            music[start:end]+=signal[:end-start]
            ledger.append({'quarter':{'numerator':q.numerator,'denominator':q.denominator},
                           'frame':start,'voice':kind,'pitch':pitch,'gain':gain})
    roots=[40+(seed%5),43+(seed%5),38+(seed%5),45+(seed%5)]
    for bar in range(bars):
        root=roots[(bar//2)%len(roots)]
        for beat in range(meter):
            q=Fraction(bar*meter+beat)
            strong=beat==0
            gain=.26 if variant=='weak_downbeat' and strong else (1 if strong else .7)
            if variant=='half_time':
                if strong and bar%2==0:add(q,'kick',gain=gain)
                if beat==meter-1 and bar%2==0:add(q,'snare',gain=.8)
            elif variant=='syncopated':
                if beat%2==0:add(q+Fraction(1,4),'kick',gain=.8)
                if beat%2==1:add(q+Fraction(3,4),'snare',gain=.7)
            else:
                add(q,'kick' if strong or beat%2==0 else 'snare',gain=gain)
            add(q,'bass',root+(7 if beat%2 else 0),.55 if strong else .3)
            subdivision=4 if variant=='double_time' else 2
            for sub in range(subdivision):
                add(q+Fraction(sub,subdivision),'hat',gain=.5 if sub==0 else .25)
            if strong:
                for pitch in [root+24,root+27,root+31]:add(q,'chord',pitch,.38)
        for i in range(0,meter*2,2):
            add(Fraction(bar*meter)+Fraction(i,2),'chord',root+36+[0,3,7][(i//2+bar)%3],.15)
    for quarter in range(quarters):
        marker[frame_at(Fraction(quarter),bpm,lead)]=.8
    peak=float(np.max(abs(music)))
    if peak<=0:raise ValueError('Empty generated music')
    music=music/peak*.85
    directory.mkdir(parents=True)
    sf.write(directory/'music.wav',music,RATE,subtype='PCM_24')
    sf.write(directory/'transport-marker.wav',marker,RATE,subtype='PCM_24')
    clock={'schema_version':1,'id':ident,'parent_group':f'composition:{seed}:{meter}',
           'role':'controlled_diagnostic','variant':variant,'sample_rate':RATE,'sample_frames':frames,
           'bpm_fraction':{'numerator':bpm.numerator,'denominator':bpm.denominator},
           'meter':{'numerator':meter,'denominator':4},'lead_fraction':{'numerator':lead.numerator,'denominator':lead.denominator},
           'musical_quarters':quarters,'marker_supplied_to_model':False,
           'renderer':'analytic sample-clock drum/bass/chord synthesis',
           'quarter_definition':'explicit compositional transport; perceptual uniqueness is not guaranteed',
           'real_recording_generalization_evidence':False,'source_support_seconds':[0,frames/RATE],
           'paired_family':{'seed':seed,'bpm':str(bpm),'meter':meter}}
    write_json(directory/'clock.json',clock);write_json(directory/'event-ledger.json',{'events':ledger})
    return clock


def verify_clock(directory,clock):
    """Read the independent marker channel against declared rational transport."""
    bpm=Fraction(clock['bpm_fraction']['numerator'],clock['bpm_fraction']['denominator'])
    lead=Fraction(clock['lead_fraction']['numerator'],clock['lead_fraction']['denominator'])
    marker,rate=sf.read(directory/'transport-marker.wav',dtype='float64')
    actual=np.flatnonzero(abs(marker)>.4)
    expected=np.array([int(round((lead+Fraction(index)*60/bpm)*rate)) for index in range(clock['musical_quarters'])])
    if len(actual)!=len(expected) or np.max(abs(actual-expected))>1:
        raise ValueError('Rendered transport marker differs from declared sample clock')
    ledger=json.loads((directory/'event-ledger.json').read_text())['events']
    maximum_event_error=0
    for event in ledger:
        quarter=Fraction(event['quarter']['numerator'],event['quarter']['denominator'])
        intended=int(round((lead+quarter*60/bpm)*rate))
        maximum_event_error=max(maximum_event_error,abs(event['frame']-intended))
    if maximum_event_error>1:
        raise ValueError('Music event placement differs from declared transport')
    audio=sf.info(directory/'music.wav')
    if audio.frames!=len(marker) or audio.samplerate!=rate or rate!=clock['sample_rate']:
        raise ValueError('Music and verified marker use different sample coordinates')
    return {'independent_transport_marker_read':True,'marker_not_model_input':True,
            'maximum_marker_frame_difference':int(np.max(abs(actual-expected))),
            'maximum_music_event_frame_difference':maximum_event_error,
            'music_temporal_postprocessing':False,
            'origin_coordinate_bound_ms':1000/rate,'does_not_certify_real_producer_clock':True}


def references(clock):
    """Construct ideal clock events independently of estimator grid helpers."""
    bpm=Fraction(clock['bpm_fraction']['numerator'],clock['bpm_fraction']['denominator'])
    lead=Fraction(clock['lead_fraction']['numerator'],clock['lead_fraction']['denominator'])
    period=Fraction(60,1)/bpm;duration=Fraction(clock['sample_frames'],clock['sample_rate'])
    def events(p):
        first=math.ceil(-lead/p);stop=math.ceil((duration-lead)/p)
        return [float(lead+index*p) for index in range(first,stop) if 0<=lead+index*p<duration]
    return {'id':clock['id'],'kind':'defined_generated_transport_clock','quarter_bpm':float(bpm),
            'period_seconds':float(period),'time_signature':clock['meter'],
            'offset_seconds':float(lead%(period*clock['meter']['numerator'])),
            'quarter_times_seconds':events(period),'downbeat_times_seconds':events(period*clock['meter']['numerator']),
            'support_seconds':[0,float(duration)],'absolute_audio_origin_verified':True,
            'origin_coordinate_bound_ms':1000/clock['sample_rate'],
            'independent_real_producer_clock':False,'reference_creation_uses_model_predictions':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new corpus output')
    rows=[]
    for index,(bpm,meter) in enumerate(PARENTS):
        for variant in VARIANTS:
            ident=f'control{index:02d}_{variant}'
            directory=args.output/'inputs'/ident
            clock=render_case(directory,ident,bpm,meter,4100+index,variant)
            verification=verify_clock(directory,clock)
            write_json(directory/'origin-verification.json',verification)
            reference=references(clock);write_json(args.output/'references'/f'{ident}.json',reference)
            rows.append({'id':ident,'audio_path':str((directory/'music.wav').resolve()),'sample_rate':RATE,
                         'sample_frames':clock['sample_frames'],'channels':1,'duration_seconds':clock['sample_frames']/RATE})
            print(f'RENDER {ident}',flush=True)
    for index,bpm in enumerate([Fraction(257,2),Fraction(1201,10)]):
        ident=f'control_long{index}'
        directory=args.output/'inputs'/ident
        clock=render_case(directory,ident,bpm,4,4200+index,'straight',bars=128)
        write_json(directory/'origin-verification.json',verify_clock(directory,clock))
        write_json(args.output/'references'/f'{ident}.json',references(clock))
        rows.append({'id':ident,'audio_path':str((directory/'music.wav').resolve()),'sample_rate':RATE,
                     'sample_frames':clock['sample_frames'],'channels':1,'duration_seconds':clock['sample_frames']/RATE})
    write_json(args.output/'source-inputs.json',{'schema_version':1,'samples':rows})
    write_json(args.output/'unit-hints.json',{'schema_version':1,'samples':[
        {'id':row['id'],'initial_quarter_bpm_tap':json.loads((args.output/'references'/f'{row["id"]}.json').read_text())['quarter_bpm'],
         'scope':'initial_section','origin':'defined-generated-clock-unit-diagnostic'} for row in rows]})
    write_json(args.output/'corpus.json',{'sample_count':len(rows),'parents':len(PARENTS)+2,
        'variants':VARIANTS,'synthetic_control_not_real_music_test':True,
        'origin_checks':len(rows),'model_inputs_exclude_transport_markers':True,
        'vocabulary_probe_ids':['control_long1'],'music_minutes':sum(row['duration_seconds'] for row in rows)/60})
    print(json.dumps({'samples':len(rows),'minutes':sum(row['duration_seconds'] for row in rows)/60}),flush=True)


if __name__=='__main__':main()
