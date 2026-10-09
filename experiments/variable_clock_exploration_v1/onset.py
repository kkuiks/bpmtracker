"""A separately frozen source-onset challenger, independent of neural peak recall."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .clock import boundaries, event_axis, events_from_evidence, noise_scale, quantize
from .phasor import regions as phase_regions


def predict(data,initial_neural_unit=False):
    t=np.asarray(data['attack_times'],dtype=float)
    w=np.asarray(data['attack_weights'],dtype=float)
    w=np.clip(w/max(float(np.quantile(w,.8)),1e-8),.05,1) if len(w) else w
    duration=float(data['duration_seconds'])
    if len(t)<4:return {'status':'UNKNOWN_insufficient_attacks','regions':[],'boundaries':[]}
    x=event_axis(t);sigma=noise_scale(x,t)
    regions,diagnostic,alternatives=phase_regions(t,w,duration,sigma,32)
    power=0;unit_available=False
    if initial_neural_unit and regions:
        nt,nw,_=events_from_evidence(data,False);nt=nt[nt<20]
        if len(nt)>=4:
            neural_bpm=60/float(np.median(np.diff(nt)))
            raw_bpm=regions[0]['bpm_continuous']
            power=int(np.clip(round(math.log2(neural_bpm/raw_bpm)),-2,2));unit_available=True
    scale=2.**power
    for r in regions:
        r['bpm_continuous']*=scale;r['period']/=scale
        r['bpm']=quantize(r['bpm_continuous']);r['nominal_period']=60/r['bpm']
        r['nominal_phase']=r['origin']%r['nominal_period']
        r['source_supported_span']=[r['first_event'],r['last_event']]
        r['confidence_state']='SUPPORTED' if 30<=r['bpm_continuous']<=400 else 'UNKNOWN_unsupported_audio_unit'
    switches=boundaries(regions,x,t,sigma,True)
    unknown=[[r['start'],r['end']] for r in regions if r['confidence_state']!='SUPPORTED']
    uncertain=[];accepted=[]
    for switch,left,right in zip(switches,regions,regions[1:]):
        if left['confidence_state']=='SUPPORTED' and right['confidence_state']=='SUPPORTED':accepted.append(switch)
        else:uncertain.append(switch)
    switches=accepted
    if 'silent_frame_mask' in data:
        mask=np.asarray(data['silent_frame_mask'],dtype=bool)
        first=np.flatnonzero(mask & ~np.r_[False,mask[:-1]])
        last=np.flatnonzero(mask & ~np.r_[mask[1:],False])+1
        for a,b in zip(first,last):
            lo,hi=a/float(data['fps']),min(duration,b/float(data['fps']))
            periods=[r['period'] for r in regions if r['start']<hi and r['end']>lo]
            if periods and hi-lo>=min(periods):unknown.append([lo,hi])
    return {'status':'exploratory_source_onset_clock','regions':regions,'boundaries':switches,
            'unknown_intervals_seconds':unknown,'source_clock_alternatives':alternatives,
            'uncertain_boundary_hypotheses':uncertain,
            'diagnostic':diagnostic,'initial_neural_unit_requested':initial_neural_unit,
            'initial_neural_unit_available':unit_available,'discrete_initial_audio_unit_power':power,
            'initial_audio_number_not_used_as_fine_bpm_target':True,
            'whole_input_pulse_level_relation_stability_is_an_experimental_assumption':True,
            'reference_fields_read':False,'initial_tap_used':False,
            'native_pulse_unit_is_not_certified_quarter_notation':True}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output-name',default='onset-domain-guard-predictions');a=p.parse_args()
    rows=json.loads((a.run/'source-inputs.json').read_text())['samples']
    output=a.run/a.output_name;output.mkdir(exist_ok=False)
    hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in ('onset.py','clock.py','phasor.py')}
    freeze={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':hashes,
            'reference_data_used_to_choose_parameters':False,'penalty':32,
            'variants':['raw_onset_transport','raw_onset_initial_neural_unit'],
            'parameter_selection_not_repeated_on_real_or_prospective_scores':True,
            'not_an_additional_independent_test_set':True}
    (a.run/(a.output_name+'-freeze.json')).write_text(json.dumps(freeze,indent=2)+'\n')
    (output/'onset-source-snapshot.py').write_bytes(Path(__file__).read_bytes())
    used=0
    for row in rows:
        if not row.get('audio_path'):continue
        with np.load(a.run/'source-features'/f"{row['id']}.npz",allow_pickle=False) as stored:
            data={k:stored[k].copy() for k in stored.files}
        for name,gauge in (('raw_onset_transport',False),('raw_onset_initial_neural_unit',True)):
            folder=output/name;folder.mkdir(exist_ok=True)
            try:value=predict(data,gauge)
            except Exception as exc:value={'status':'failed','error':f'{type(exc).__name__}: {exc}','regions':[],'boundaries':[]}
            value['id']=row['id']
            (folder/f"{row['id']}.json").write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
        used+=1
        if used%10==0:print('RAW ONSET',used,flush=True)
    (output/'receipt.json').write_text(json.dumps({'completed':True,'reference_files_read':False,
                                                 'waveform_input_ids':used,'predictions':used*2},indent=2)+'\n')


if __name__=='__main__':main()
