"""One reference-free full-song analysis route with an optional scalar BPM hint."""
import argparse
import json
import math
from pathlib import Path
import resource
import time
import numpy as np
import soundfile as sf
from .features import Extractor
from .structure_model import predict
from .clock_search import clock_bank,sigmoid,select_pulse_level
from .meter_search import decode_meter,interpolate
from .probe_resources import digest


def extend_clock(clock,qmin,qmax):
    points=clock.tolist()
    if qmin<clock[0,0]:points.insert(0,[float(qmin),float(interpolate(clock,np.array([qmin]))[0])])
    if qmax>clock[-1,0]:points.append([float(qmax),float(interpolate(clock,np.array([qmax]))[0])])
    return np.asarray(points)


def declared_map(candidate,source,duration,structural,logits,energy):
    clock=candidate['clock'];bars=candidate['meter']['bars'];events=[]
    first_rate=(clock[1,0]-clock[0,0])/(clock[1,1]-clock[0,1])
    last_rate=(clock[-1,0]-clock[-2,0])/(clock[-1,1]-clock[-2,1])
    qstart=clock[0,0]-clock[0,1]*first_rate
    qend=clock[-1,0]+(duration-clock[-1,1])*last_rate
    first_length=4*bars[0]['n']/bars[0]['d']
    context_start=bars[0]['q']+math.floor((qstart-bars[0]['q'])/first_length)*first_length
    clock=extend_clock(clock,min(bars[0]['q'],context_start),max(qend,bars[-1]['q']+4*bars[-1]['n']/bars[-1]['d']))
    for bar in bars:
        signature=(bar['n'],bar['d'])
        if not events or signature!=(events[-1]['numerator'],events[-1]['denominator']):
            n,d=signature
            grouping=([3]*(n//3) if d==8 and n in (6,9,12) else None)
            events.append(dict(pulse=bar['q'],numerator=n,denominator=d,grouping=grouping,bar_action='continue'))
    events[0]['pulse']=float(clock[0,0])
    support_end=duration;tail_decision='retained_grid_no_sufficient_free_tail_evidence'
    grid=sigmoid(structural['events'][:,3]);grid_times=np.arange(len(grid))/12.5
    # Compare against THIS selected variable clock, never an old constant clock.
    quarters=np.arange(math.ceil(qstart),math.floor(qend)+1)
    pulse_times=interpolate(clock,quarters)
    probabilities=sigmoid(logits[:,0]);pt=np.arange(len(probabilities))/50
    for start in np.arange(max(0,duration*.6),max(0,duration-8),.5):
        mask=grid_times>=start
        if not mask.any() or np.quantile(grid[mask],.9)>=.25:continue
        tail_pulses=pulse_times[(pulse_times>=start)&(pulse_times<duration)]
        if len(tail_pulses)<4:continue
        aligned=np.max([np.interp(tail_pulses+shift,pt,probabilities) for shift in (-.04,0,.04)],axis=0)
        if np.mean(aligned>.35)<.25:
            support_end=float(start);tail_decision='low_grid_support_and_low_selected_clock_support';break
    raw=dict(schema_version=1,source=source,
        clock_knots=[dict(pulse=float(q),source_seconds=float(t)) for q,t in clock],
        quarters_per_pulse=dict(numerator=1,denominator=1),bar_anchor_pulse=bars[0]['q'],
        meter_events=events,support_seconds=[[0.,support_end]],analysis_condition='unhinted',shared_origin_id=None)
    return raw,dict(reason=tail_decision,no_grid_tail=[support_end,duration] if support_end<duration else None,
        grid_confidence_calibrated=False)


def analyze(audio_path,initial_bpm=None,*,acoustic_checkpoint,structure_checkpoint,cache_root,output):
    import torch
    if initial_bpm is not None and (not math.isfinite(initial_bpm) or initial_bpm<=0):raise ValueError('positive finite BPM hint required')
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    started=time.perf_counter();torch.set_num_threads(4);torch.cuda.reset_peak_memory_stats()
    audio_path=Path(audio_path);info=sf.info(audio_path);audio_hash=digest(audio_path)
    source=dict(sha256=audio_hash,sample_rate=info.samplerate,sample_frames=info.frames)
    cache=Path(cache_root)/(audio_hash+'.npz');cache_hit=cache.exists()
    extractor=Extractor(acoustic_checkpoint);meta=extractor.extract(audio_path,cache)
    del extractor;torch.cuda.empty_cache()
    with np.load(cache) as z:features=z['features'];logits=z['logits'];energy=z['energy']
    structural=predict(features,logits,structure_checkpoint);del features
    np.savez_compressed(output/'structural-observations.npz',**structural)
    bank=clock_bank(logits,structural,energy)
    from .timing_controls import proposals
    bank.extend(proposals(logits,source,structural))
    for proposal in bank:
        proposal['meter']=decode_meter(proposal['clock'],logits,structural)
        clock=proposal['clock'];rates=60*np.diff(clock[:,0])/np.diff(clock[:,1])
        mid=(clock[:-1,1]+clock[1:,1])/2
        learned=np.interp(mid,np.arange(len(structural['tempo']))/12.5,structural['tempo'])
        tempo_penalty=.20*float(np.mean(np.minimum(2,abs(np.log2(rates/120)-learned))))
        proposal['joint_score']=proposal['score']+.35*proposal['meter']['score']-tempo_penalty
    bank,pulse_choice=select_pulse_level(bank,initial_bpm)
    outputs=[];all_candidates=[]
    for rank,candidate in enumerate(bank):
        raw,tail=declared_map(candidate,source,info.duration,structural,logits,energy)
        raw['analysis_condition']='user_bpm_guided' if initial_bpm is not None else 'unhinted'
        value=dict(schema_version=1,map=raw,source_only=True,reference_read=False,
            diagnostics=dict(clock_family=candidate['name'],clock_fit=candidate['fit'],
                joint_score=candidate['joint_score'],meter_search=candidate['meter']['diagnostics'],
                tail=tail,initial_bpm=initial_bpm,initial_bpm_note_unit_supplied=False,pulse_level_selection=pulse_choice,
                alternative_rank=rank,confidence_calibrated=False))
        all_candidates.append(dict(name=candidate['name'],score=candidate['joint_score'],prediction=value))
        if rank<3:
            filename='selected.json' if rank==0 else f'alternative-{rank}.json'
            (output/filename).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
            outputs.append(dict(path=str((output/filename).resolve()),sha256=digest(output/filename)))
    (output/'candidate-bank.json').write_text(json.dumps(all_candidates,indent=2,allow_nan=False)+'\n')
    ended=time.perf_counter()
    record=dict(complete=True,references_available_to_runner=False,audio=str(audio_path.resolve()),source=source,
        selected=outputs[0],alternatives=outputs[1:],initial_bpm=initial_bpm,
        model_sha256=digest(structure_checkpoint),acoustic_checkpoint_sha256=digest(acoustic_checkpoint),
        feature_binding=meta['binding'],cache_hit=cache_hit,
        runtime_seconds=ended-started,real_time_factor=(ended-started)/info.duration,
        peak_reserved_bytes=torch.cuda.max_memory_reserved(),max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        proposal_scores=[dict(name=c['name'],score=c['joint_score'],clock_segments=c['fit']['segments']) for c in bank],
        search_limits=dict(quarter_bpm=[25,400],numerator=[1,32],denominators=[2,4,8,16,32],
                           note='Explicit initial experimental coverage, not a claim to every possible notation.'),
        implementation_sha256={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')})
    (output/'run.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(complete=True,seconds=record['runtime_seconds'],clock=bank[0]['name'],output=str(output))))
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True);p.add_argument('--initial-bpm',type=float)
    p.add_argument('--acoustic-checkpoint',type=Path,required=True);p.add_argument('--structure-checkpoint',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    analyze(a.audio,a.initial_bpm,acoustic_checkpoint=a.acoustic_checkpoint,structure_checkpoint=a.structure_checkpoint,cache_root=a.cache_root,output=a.output)

if __name__=='__main__':main()
