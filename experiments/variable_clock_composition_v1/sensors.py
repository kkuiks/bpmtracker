"""Official cached/fresh sensor and a separate PCM onset measurement."""
from __future__ import annotations

import argparse
import gzip
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, resample_poly, stft
from scipy.special import expit
import soundfile as sf

from .common import ROOT, read, write, digest


def event_peaks(logits, refine=True):
    p=expit(np.asarray(logits,dtype=float));k,_=find_peaks(p,height=.25,distance=3)
    delta=np.zeros(len(k))
    if refine and len(k):
        a,b,c=p[k-1],p[k],p[k+1];den=a-2*b+c
        delta=np.divide(.5*(a-c),den,out=delta,where=abs(den)>1e-12)
        delta=np.clip(delta,-.5,.5)
    return (k+delta)/50.,p[k]


def pcm_flux(signal,rate,duration):
    mono=signal.mean(axis=1)
    if rate!=16000:
        g=math.gcd(rate,16000);mono=resample_poly(mono,16000//g,rate//g)
    _,times,z=stft(mono,fs=16000,nperseg=1024,noverlap=704,boundary='zeros',padded=True)
    mag=np.log1p(abs(z)*100.)
    flux=np.r_[0.,np.maximum(0.,np.diff(mag,axis=1)).mean(axis=0)]
    local=median_filter(flux,size=101,mode='nearest')
    excess=np.maximum(0.,flux-local)
    scale=np.percentile(excess,95) if len(excess) else 0.
    v=np.clip(excess/max(float(scale),1e-9),0,1)
    k,_=find_peaks(v,height=.20,distance=3)
    use=times[k]<duration
    return times[k][use],v[k][use]


def source_array(path):
    allowed={'beat_logits','downbeat_logits','fps','duration_seconds','silent_frame_mask'}
    with np.load(path,allow_pickle=False) as d:
        return {k:d[k].copy() for k in allowed if k in d}


def final_bank(data,run,ident):
    from experiments.metronome_reconstruction_v1.infer import make_evidence
    from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family,select_from_family
    from experiments.metronome_benchmark_v1.trace import CandidateTrace
    from experiments.variable_tempo_interval_consensus_v0.candidates import original_h,pool
    cfg=read(ROOT/'experiments/metronome_reconstruction_v1/config-tap-v2.json')
    ev=make_evidence(data['beat_logits'],data['downbeat_logits'],float(data['duration_seconds']),cfg)
    with CandidateTrace(run/'original-traces',ident) as trace:
        family=prepare_audio_family(ev,cfg);trace.finish(family,select_from_family(family))
    write(run/'original-families'/f'{ident}.json',family)
    values=[]
    with gzip.open(run/'original-traces'/f'{ident}.scores.jsonl.gz','rt') as f:
        for line in f:
            r=__import__('json').loads(line);c=r['candidate']
            if r['block']!='base_search' and c['time_signature']['numerator']==4:
                values.append(original_h(c,'original_'+str(r['block'])))
    bank,stats=pool(values,512)
    return {'pools':{'final':bank},'statistics':stats,'source_only':True}


def one(row,run,tracker=None):
    started=time.perf_counter();ident=row['id']
    signal,rate=sf.read(row['audio_path'],dtype='float32',always_2d=True)
    if rate!=row['sample_rate'] or signal.shape!=(row['sample_frames'],row['channels']):
        raise ValueError('Source geometry mismatch')
    duration=len(signal)/rate
    if row.get('cache_path'):
        if digest(row['cache_path'])!=row['cache_sha256']:raise ValueError('Sensor cache changed')
        data=source_array(row['cache_path'])
        if abs(float(data['duration_seconds'])-duration)>.08:raise ValueError('Wrong-source sensor cache')
    else:
        beat,down=tracker(signal,rate)
        data={'beat_logits':beat.cpu().numpy(),'downbeat_logits':down.cpu().numpy(),
              'fps':np.array(50),'duration_seconds':np.array(duration)}
    t,w=event_peaks(data['beat_logits']);raw_t,raw_w=event_peaks(data['beat_logits'],False)
    dt,dw=event_peaks(data['downbeat_logits']);pt,pw=pcm_flux(signal,rate,duration)
    np.savez_compressed(run/'source-evidence'/f'{ident}.npz',**data)
    np.savez_compressed(run/'events'/f'{ident}.npz',times=t,weights=w,raw_times=raw_t,raw_weights=raw_w,
                        downbeat_times=dt,downbeat_weights=dw,pcm_times=pt,pcm_weights=pw,
                        duration=np.array(duration))
    if row.get('final_bank_path'):
        bank=read(row['final_bank_path'])
    else:bank=final_bank(data,run,ident)
    write(run/'final-banks'/f'{ident}.json',{'clocks':bank['pools']['final']})
    receipt={'id':ident,'duration':duration,'neural_events':len(t),'pcm_events':len(pt),
             'fresh_model_run':not bool(row.get('cache_path')),'elapsed_seconds':time.perf_counter()-started,
             'source_array_sha256':digest(run/'source-evidence'/f'{ident}.npz'),
             'events_sha256':digest(run/'events'/f'{ident}.npz'),'final_bank_sha256':digest(run/'final-banks'/f'{ident}.json')}
    write(run/'sensor-receipts'/f'{ident}.json',receipt)
    print('SENSOR',ident,'FRESH' if receipt['fresh_model_run'] else 'CACHE',round(receipt['elapsed_seconds'],2),flush=True)
    return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--shard',type=int,default=0);p.add_argument('--shards',type=int,default=1);a=p.parse_args()
    rows=read(a.run/'source-inputs.json')['samples'][a.shard::a.shards]
    allowed={'id','audio_path','duration_seconds','sample_rate','sample_frames','channels',
             'cache_path','cache_sha256','final_bank_path'}
    if any(set(r)-allowed for r in rows):raise ValueError('Reference field in source manifest')
    for sub in ['source-evidence','events','final-banks','sensor-receipts']:(a.run/sub).mkdir(parents=True,exist_ok=True)
    opened=[];active=[False]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        s=args[0].decode() if isinstance(args[0],bytes) else args[0]
        mode=args[1] if isinstance(args[1],str) else ''
        if any(v in mode for v in 'wax+'):return
        if any(v in s.lower() for v in ['/references/','evaluation','catalog.json','transport-marker','acceptance.json']):
            raise RuntimeError('Forbidden source-worker reference read: '+s)
        if Path(s).suffix in ['.json','.npz','.wav','.ckpt']:opened.append(s)
    sys.addaudithook(audit)
    tracker=None
    if any(not r.get('cache_path') for r in rows):
        import torch
        from beat_this.inference import Audio2Frames
        torch.set_num_threads(4);torch.set_num_interop_threads(1)
        tracker=Audio2Frames(str(ROOT/'data/models/final0.ckpt'),device='cpu',float16=False)
    active[0]=True
    try:
        for row in rows:
            if not (a.run/'sensor-receipts'/f"{row['id']}.json").exists():one(row,a.run,tracker)
    finally:active[0]=False
    write(a.run/'sensor-audit'/f'{a.shard}.json',{'source_schema_checked':True,'actual_read_hook':True,
          'forbidden_reference_reads':0,'opened_data_paths':sorted(set(opened)),
          'not_an_OS_sandbox_claim':True})


if __name__=='__main__':main()
