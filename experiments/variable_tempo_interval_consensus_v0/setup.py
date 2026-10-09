"""Admission manager exports source-only worker records and separate evaluator records."""
import argparse
from pathlib import Path
import numpy as np
import soundfile as sf
from tools.project_storage import ROOT, RUNS, SAMPLES, resolve_path
from experiments.variable_clock_exploration_v1.evaluate import reference
from .io import read,write,source_array,digest

PRIOR = RUNS/'variable_clock_exploration_v1/20261008-clock-witness-v1'
STEP = RUNS/'variable_tempo_step0/20261007-step0-v1/original'
BENCH = RUNS/'metronome_benchmark_v1'


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True);a=p.parse_args()
    if (a.run/'source-inputs.json').exists(): raise ValueError('Use a fresh run/admission')
    exclusions=read(SAMPLES/'excluded-candidates.json')['candidates']
    catalog=read(SAMPLES/'catalog.json')
    forbidden={r.get('id') for r in exclusions if r.get('permanent_exclusion')}
    old_sources=read(PRIOR/'source-inputs.json')['samples']; old_eval=read(PRIOR/'evaluation-index.json')['rows']
    stress=PRIOR/'supplementary-meter-negative-controls'
    stress_sources=read(stress/'source-inputs.json')['samples']; stress_eval=read(stress/'evaluation-index.json')['rows']
    for row in stress_sources:
        row.update(evidence_path=str(stress/'evidence'/f"{row['id']}.npz"),fps=50)
    fresh_sources=read(a.corpus/'source-inputs.json')['samples']; fresh_eval=read(a.corpus/'evaluation-index.json')['rows']
    for row in fresh_sources: row.update(evidence_path=str(a.run/'neural-evidence'/f"{row['id']}.npz"),fps=50)
    known_hints={r['id']:r for r in read(a.corpus/'initial-information.json')['rows']}
    old_cal=set(read(PRIOR/'protocol.json')['calibration_ids'])
    sources=[]; evaluation=[]; hints=[]; calibration=[]; mapping=[]; receipt=[]
    for k,(old,ev) in enumerate(zip(old_sources+stress_sources+fresh_sources,old_eval+stress_eval+fresh_eval)):
        original_id=old['id']; ident=f'src{k:04d}'
        if original_id in forbidden: raise ValueError('Permanently excluded source')
        cached=PRIOR/'source-features'/f'{original_id}.npz'
        path=cached if cached.exists() else resolve_path(old['evidence_path'])
        data=source_array(path)
        if 'silent_frame_mask' not in data and old.get('audio_path'):
            signal,rate=sf.read(resolve_path(old['audio_path']),dtype='float32',always_2d=True)
            zero=np.all(signal==0,axis=1); prefix=np.r_[0,np.cumsum(zero)]
            positions=np.arange(len(data['beat_logits'])); lo=np.minimum(len(zero),np.rint(positions*rate/50).astype(int))
            hi=np.minimum(len(zero),np.rint((positions+1)*rate/50).astype(int))
            data['silent_frame_mask']=(hi>lo)&(prefix[hi]-prefix[lo]==hi-lo)
            out=a.run/'source-evidence'/f'{ident}.npz';out.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(out,**data);path=out
        row=dict(id=ident,evidence_path=str(path.resolve()),duration_seconds=old['duration_seconds'],fps=50)
        if old.get('audio_path'): row['audio_path']=str(resolve_path(old['audio_path']))
        roots=[STEP,BENCH/'20261007-generated58-frozen-v1',BENCH/'20261007-gtzan-development280-frozen-v1',BENCH/'20261007-gtzan-validation87-frozen-v1']
        for root in roots:
            family=root/'families'/f'{original_id}.json'
            if family.exists():
                row['original_family_path']=str(family.resolve())
                for field,suffix in [('original_trace_path','scores'),('original_events_path','events')]:
                    candidate=root/'traces'/f'{original_id}.{suffix}.jsonl.gz'
                    if candidate.exists(): row[field]=str(candidate.resolve())
                break
        phasor=PRIOR/'frozen-predictions/phasor_transport-p32-neural'/f'{original_id}.json'
        if not phasor.exists(): phasor=stress/'predictions/phasor_transport-neural'/f'{original_id}.json'
        if phasor.exists(): row['phasor_cache_path']=str(phasor.resolve())
        sources.append(row)
        ev=dict(ev,id=ident,original_id=original_id)
        ref=reference(ev,old['duration_seconds'])
        raw=read(ev['reference_path']); bars=raw.get('stored_downbeat_events',raw.get('downbeat_times_seconds',raw.get('downbeats_seconds',[])))
        if ev['role']=='supplementary_constant_bpm':
            signatures={(e['numerator'],e['denominator']) for e in raw.get('meter_events',[])}
            ev['role']='additional_fixed' if signatures=={(4,4)} else 'meter_change_stress'
        if not bars and 'meter_events' in raw:
            from experiments.variable_tempo_step0.common import stored_reference
            bars=stored_reference(raw,ref.get('support',[])).get('downbeat_times_seconds',[])
        meter=raw.get('bar_pulse_count') or raw.get('time_signature',{}).get('numerator')
        if meter is None and raw.get('meter_events'): meter=raw['meter_events'][0]['numerator']
        if meter is None and bars and ref.get('quarters'):
            qs=np.array(ref['quarters']); bs=np.array(bars)
            counts=[int(np.sum((qs>=x-1e-6)&(qs<y-1e-6))) for x,y in zip(bs,bs[1:])]
            meter=int(round(np.median(counts))) if counts else 4
        four_two=any(e['numerator']==4 and e['denominator']==2 for e in raw.get('meter_events',[]))
        ev['scope']='rate_only' if ref['rate_only'] or four_two else 'out_of_scope_meter' if meter and meter!=4 else 'quarter4'
        ev['bar_events']=bars; ev['reference_meter']=meter
        evaluation.append(ev)
        if (original_id in old_cal or ev['role']=='new_development') and ev['scope']=='quarter4': calibration.append(ident)
        if original_id in known_hints:
            hint={key:value for key,value in known_hints[original_id].items() if key!='id'}
        elif ref.get('segments'):
            hint=dict(initial_bpm=ref['segments'][0]['quarter_bpm'],bpm_unit_quarters=1.,scope='initial_audio_section',origin='approved_initial_clock_assumption_proxy')
        else: hint=None
        if hint: hints.append(dict(id=ident,**hint))
        mapping.append(dict(id=ident,original_id=original_id,role=ev['role'],scope=ev['scope']))
        receipt.append(dict(id=ident,source_exists=path.exists(),frames=len(data['beat_logits']),cached_observation=True))
    write(a.run/'source-inputs.json',{'samples':sources})
    write(a.run/'evaluation-index.json',{'rows':evaluation})
    write(a.run/'assumed-initial-inputs.json',{'rows':hints,'actual_human_inputs_collected':False,'only_initial_BPM_and_unit_forwarded':True})
    write(a.run/'identity-index.json',{'rows':mapping})
    write(a.run/'admission.json',{'rows':receipt,'unique_input_ids':len(sources),'reserved98_consumed':0,'formal_catalog_changed':False,
                               'original_denominators_changed':False,'phase_or_boundaries_in_initial_information':False})
    protocol=dict(experiment='interval-consensus-A-v1',owner_execution_approved=True,first_unit_only=True,
                  new_constructed_inputs=24,new_parent_groups=4,calibration_ids=calibration,
                  parent_split_before_selection=True,primary_real_used_for_tuning=False,
                  conditions=['A_GLOBAL_MATCHED','A_INTERVAL_FIXED','A_RETAINED','A_BROAD_PHASE','A_PHASOR','A_PHASE_REFIT','A_RATE_PHASE_REFIT'],
                  initial_policies=['none','initial_unit','initial_exact'],initial_information_assumed_not_measured=True,
                  primary_direction_gate_policy='initial_exact',initial_scope_rule='initial source pulse anchor extended only through the first source-supported clock episode; no reference boundary',
                  initial_exact_semantics='select existing source-supported nominal BPM only in initial scope; no phase/hypothesis creation',
                  quarter_bpm_domain=[30,400],maximum_denominator=4,primary_meter=4,
                  candidate_budgets=[128,512],primary_candidate_budget=512,maximum_configurations=24,
                  primary_tolerance_ms=70,secondary_tolerances_ms=[20,30],fixed_calibration_wrong_time_target=.01,
                  direction_gate=dict(improvement_percentage_points=5,positive_real_songs=2,fixed_wrong_time_must_not_increase=True),
                  source_reference_workers_separate=True,application_integration=False,
                  original_config_sha256=digest(ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json'))
    write(a.run/'protocol.json',protocol)
    print('ADMITTED',len(sources),'CALIBRATION',len(calibration),flush=True)


if __name__=='__main__':main()
