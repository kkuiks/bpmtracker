"""Frozen acoustic evidence, including a deterministic onset channel."""
import numpy as np


def sigmoid(x):return 1/(1+np.exp(-np.clip(x,-30,30)))


def local_peaks(x,threshold):
    return np.flatnonzero((x>=threshold)&(x>np.r_[-np.inf,x[:-1]])&(x>=np.r_[x[1:],-np.inf]))


def refined_times(values,indices,fps):
    """Three-frame log-amplitude peak interpolation; no precision claim."""
    result=[]
    for i in indices:
        delta=0.
        if 0<i<len(values)-1:
            left,center,right=np.log(np.maximum(values[i-1:i+2],1e-5))
            curvature=left-2*center+right
            if curvature<0:delta=float(np.clip(.5*(left-right)/curvature,-.5,.5))
        result.append((i+delta)/fps)
    return np.asarray(result)


def prepare(logits,energy,fps=50.,features=None):
    logits=np.asarray(logits,float);energy=np.asarray(energy,float)
    if logits.shape!=(len(energy),2) or not np.isfinite(logits).all():raise ValueError('invalid observations')
    beat=sigmoid(logits[:,0]);down=sigmoid(logits[:,1])
    # RMS is source-aligned and frozen with Beat This. No stem or new encoder.
    flux=np.maximum(0,np.diff(np.log(np.maximum(energy,1e-6)),prepend=np.log(max(energy[0],1e-6))))
    flux=np.clip(flux/max(float(np.quantile(flux,.95)),.1),0,1)
    ix=np.unique(np.r_[local_peaks(beat,.2),local_peaks(down,.2)])
    # Merge simultaneous detections; preserve quarter/offbeat alternatives.
    kept=[]
    for i in ix:
        if kept and i-kept[-1]<=1:
            if beat[i]+down[i]>beat[kept[-1]]+down[kept[-1]]:kept[-1]=int(i)
        else:kept.append(int(i))
    ix=np.array(kept,int)
    return dict(fps=float(fps),duration=len(energy)/fps,times=np.arange(len(energy))/fps,
                beat=beat,down=down,onset=flux,energy=energy,logits=logits,
                events=refined_times(np.maximum(beat,down),ix,fps),event_strength=beat[ix],
                event_down=down[ix],features=features)


def initial_periods(obs):
    # Estimate from audio only. The hint never enters period estimation.
    # Use the first supported opening window, not the longest later tempo.
    start=0
    for offset in range(0,min(int(obs['duration']),60),4):
        candidate=obs['beat'][int(offset*obs['fps']):int((offset+8)*obs['fps'])]
        if len(local_peaks(candidate,.35))>=6:
            start=int(offset*obs['fps']);break
    x=obs['beat'][start:start+int(8*obs['fps'])].astype(float);x=x-x.mean()
    fft=1<<(max(1,len(x))*2-1).bit_length()
    spec=np.fft.rfft(x,fft);acf=np.fft.irfft(spec*spec.conjugate(),fft)[:len(x)]
    lo=max(2,int(obs['fps']*60/320));hi=min(len(x)-1,int(obs['fps']*60/40))
    lags=np.arange(lo,hi+1);values=acf[lags]
    peaks=local_peaks(values,-np.inf)
    if not len(peaks):peaks=np.array([int(np.argmax(values))])
    order=peaks[np.argsort(values[peaks])[::-1]]
    anchor=float(lags[order[0]])/obs['fps']
    periods=[]
    for multiple in (.5,2/3,1.,1.5,2.):
        estimate=anchor*multiple
        if 60/400<=estimate<=60/25:
            near=lags[abs(lags/obs['fps']/estimate-1)<.06]
            if len(near):
                k=int(near[np.argmax(acf[near])]);delta=0.
                if 0<k<len(acf)-1:
                    denom=acf[k-1]-2*acf[k]+acf[k+1]
                    if denom<0:delta=float(np.clip(.5*(acf[k-1]-acf[k+1])/denom,-.5,.5))
                period=(k+delta)/obs['fps']
            else:period=estimate
            periods.append(dict(period=period,family=multiple))
    return periods,anchor


def pulse_family(periods,anchor,initial_bpm):
    if initial_bpm is None:return periods,dict(mode='unhinted')
    if not np.isfinite(initial_bpm) or initial_bpm<=0:raise ValueError('positive scalar required')
    # Choose discrete metrical level only; nearby hints in this bin do not
    # change numerical clock values or any other inference input.
    families=np.array([p['family'] for p in periods])
    family=float(families[np.argmin(abs(np.log2((60/initial_bpm)/anchor/families)))])
    return [p for p in periods if p['family']==family],dict(mode='pulse_family_only',family=family,numerical_hint_used_for_fit=False)
