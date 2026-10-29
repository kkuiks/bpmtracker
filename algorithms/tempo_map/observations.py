"""Frozen neural peak refinement and independent PCM onset observation."""
from __future__ import annotations
import math
import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, resample_poly, stft
from scipy.special import expit


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
