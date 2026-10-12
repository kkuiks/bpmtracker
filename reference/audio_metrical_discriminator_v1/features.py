"""Tempo-normalized multi-band accent patterns; no evaluation inputs."""
from __future__ import annotations
import math
import numpy as np
from scipy.signal import resample_poly,stft
from scipy.special import expit
import soundfile as sf
from .common import CONFIG,FACTORS

def audio_channels(path,cfg=None):
    cfg=cfg or CONFIG;data,sr=sf.read(path,dtype='float32',always_2d=True)
    mono=data.mean(axis=1);del data
    target=cfg['sample_rate'];g=math.gcd(sr,target)
    if sr!=target:mono=resample_poly(mono,target//g,sr//g).astype(np.float32)
    f,t,z=stft(mono,fs=target,nperseg=cfg['nfft'],noverlap=cfg['nfft']-cfg['hop_samples'],
               boundary='zeros',padded=True);del mono
    magnitude=abs(z).astype(np.float32);del z
    log=np.log1p(100*magnitude);diff=np.maximum(0,np.diff(log,axis=1,prepend=log[:,:1]));del log
    channels=[]
    for lo,hi in cfg['frequency_bands']:
        select=(f>=lo)&(f<hi)
        channels.append(diff[select].mean(axis=0))
    return t,np.column_stack(channels).astype(np.float32)

def autocorrelation(data):
    x=data-data.mean(axis=0);n=len(x);length=1<<int(math.ceil(math.log2(max(2,2*n))))
    spectrum=np.fft.rfft(x,n=length,axis=0);ac=np.fft.irfft(abs(spectrum)**2,n=length,axis=0)[:n]
    return ac/np.maximum(ac[0],1e-9)

def patterns(time,data,period,phase,cfg=None):
    cfg=cfg or CONFIG;nch=data.shape[1];width=len(data);fps=1/np.median(np.diff(time)) if width>1 else 100.
    scale=np.maximum(data.mean(axis=0),1e-6);x=data/scale
    ac=autocorrelation(x);features=[]
    for lag in cfg['autocorrelation_lags_quarters']:
        position=lag*period*fps
        features.extend([float(np.interp(position,np.arange(len(ac)),ac[:,c],left=0,right=0)) for c in range(nch)])
    for meter in cfg['bars_quarters']:
        length=period*meter
        # Sub-nanosecond rounding only resolves exact-bin floating point ties.
        # Shifting source time and its source phase together must not change a
        # profile by assigning boundary frames to the opposite side of a bar.
        bin_index=np.floor((((time-phase)/length)%1+1e-10)*cfg['profile_bins']).astype(int)%cfg['profile_bins']
        count=np.bincount(bin_index,minlength=cfg['profile_bins']).astype(float)
        profile=np.zeros((cfg['profile_bins'],nch))
        for c in range(nch):np.add.at(profile[:,c],bin_index,x[:,c])
        profile/=np.maximum(count[:,None],1.)
        spectrum=np.fft.rfft(profile,axis=0);dc=np.maximum(abs(spectrum[0]),1e-6)
        features.extend((abs(spectrum[1:cfg['profile_harmonics']+1])/dc).ravel().tolist())
        features.extend(np.std(profile,axis=0).tolist())
        # Relative phase between low and high accents is preserved without a
        # reference bar/downbeat origin or a fixed four-quarter template.
        for harmonic in [1,2,4]:
            cross=spectrum[harmonic,0]*np.conj(spectrum[harmonic,-1])
            denominator=max(float(abs(spectrum[harmonic,0])*abs(spectrum[harmonic,-1])),1e-6)
            features.extend([float(cross.real/denominator),float(cross.imag/denominator)])
        low=profile[:,0]-profile[:,0].mean();high=profile[:,-1]-profile[:,-1].mean()
        features.append(float(np.dot(low,high)/max(np.linalg.norm(low)*np.linalg.norm(high),1e-6)))
    return np.nan_to_num(np.asarray(features,dtype=np.float32),nan=0,posinf=0,neginf=0)

def source_table(row,bank,tab,sensors,events,cfg=None):
    cfg=cfg or CONFIG;duration=row['duration_seconds'];window=cfg['window_seconds'];hop=cfg['hop_seconds']
    centers=np.arange(window/2,duration-window/2+1e-8,hop)
    at=np.clip((centers/.25).astype(int),0,len(tab['quality'])-1)
    if not len(bank):raise RuntimeError('No source bank')
    best=np.argmax(tab['quality'][at],axis=1);base=np.array([bank[j]['bpm'] for j in best]);phase=np.array([bank[j]['phase'] for j in best])
    quality=tab['quality'][at,best]
    nbeats=np.searchsorted(events['times'],centers+window/2)-np.searchsorted(events['times'],centers-window/2)
    available=(quality>=cfg['source_quality_min'])&(nbeats>=cfg['minimum_neural_events'])
    anchor=-1
    for i,c in enumerate(centers):
        if c>cfg['anchor_deadline_seconds']:break
        right=min(len(centers),i+3)
        if right-i<2:continue
        if (quality[i:right]>=cfg['anchor_quality_min']).all() and (abs(base[i:right]/base[i]-1)<=cfg['anchor_stability_fraction']).all():anchor=i;break
    native_median=[]
    for c in centers:
        a,b=np.searchsorted(events['times'],[c-window/2,c+window/2]);t=events['times'][a:b]
        native_median.append(float(60/np.median(np.diff(t))) if len(t)>=5 else 0.)
    audio_time,audio=audio_channels(row['audio_path'],cfg)
    fps=float(sensors['fps']);neural_time=np.arange(len(sensors['beat_logits']))/fps
    neural=np.column_stack([expit(sensors['beat_logits']),expit(sensors['downbeat_logits'])]).astype(np.float32)
    af=[];nf=[];valid=[]
    for i,c in enumerate(centers):
        a,b=np.searchsorted(audio_time,[c-window/2,c+window/2]);aa=audio[a:b];ta=audio_time[a:b]
        na,nb=np.searchsorted(neural_time,[c-window/2,c+window/2]);nn=neural[na:nb];tn=neural_time[na:nb]
        arow=[];nrow=[];v=[]
        for factor in FACTORS:
            rate=base[i]*factor;p=60/rate
            arow.append(patterns(ta,aa,p,phase[i],cfg));nrow.append(patterns(tn,nn,p,phase[i],cfg));v.append(30<=rate<=400)
        af.append(arow);nf.append(nrow);valid.append(v)
    af=np.asarray(af,np.float32);nf=np.asarray(nf,np.float32)
    anchor_audio=af[anchor].copy() if anchor>=0 else np.zeros_like(af[0])
    anchor_neural=nf[anchor].copy() if anchor>=0 else np.zeros_like(nf[0])
    return {'time':centers,'base_bpm':base,'base_phase':phase,'source_quality':quality,
            'source_available':available,'valid_candidates':np.array(valid,bool),
            'neural_median_bpm':np.asarray(native_median),'audio':af,'neural':nf,
            'anchor_audio':anchor_audio,'anchor_neural':anchor_neural,'anchor_index':np.array(anchor),
            'anchor_base_bpm':np.array(base[anchor] if anchor>=0 else 0.),
            'anchor_time':np.array(centers[anchor] if anchor>=0 else -1.),
            'duration':np.array(duration)}, {'audio_frames':len(audio),'audio_dimensions':af.shape[-1],
                                            'neural_dimensions':nf.shape[-1],'windows':len(centers),
                                            'raw_audio_time_preserved':True,'no_reference_reads':True}
