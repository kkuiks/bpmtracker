"""Bounded acoustic pulse hypotheses and continuous source-clock fitting."""
import numpy as np


def sigmoid(x):return 1/(1+np.exp(-np.clip(x,-30,30)))


def tempo_curve(evidence,fps=50):
    centers=np.arange(0,len(evidence),2*fps);rates=[];previous=None
    for center in centers:
        x=evidence[max(0,center-6*fps):min(len(evidence),center+6*fps)].astype(float)
        x=x-x.mean();nfft=1<<(2*max(1,len(x))-1).bit_length()
        spectrum=np.fft.rfft(x,nfft);acf=np.fft.irfft(spectrum*spectrum.conjugate(),nfft).real
        lags=np.arange(round(60*fps/320),min(len(x)-1,round(60*fps/40))+1)
        if not len(lags):rates.append(previous or 120.);continue
        strength=acf[lags]/max(acf[0],1e-8)
        peaks=(strength>=np.r_[-np.inf,strength[:-1]])&(strength>=np.r_[strength[1:],-np.inf])
        candidates=np.where(peaks)[0]
        if not len(candidates):candidates=np.array([int(np.argmax(strength))])
        score=strength[candidates]
        if previous:score=score-.06*np.abs(np.log2((60*fps/lags[candidates])/previous))
        chosen=candidates[np.argmax(score)];lag=float(lags[chosen])
        k=int(lag)
        if 1<=k<len(acf)-1:
            denom=acf[k-1]-2*acf[k]+acf[k+1]
            if denom<0:lag+=float(np.clip(.5*(acf[k-1]-acf[k+1])/denom,-.5,.5))
        previous=float(60*fps/lag);rates.append(previous)
    return np.interp(np.arange(len(evidence)),centers,rates)


def pulse_path(evidence,rate,fps=50):
    count=len(evidence);score=np.full(count,-1e12);previous=np.full(count,-1,np.int32)
    for i in range(count):
        period=60*fps/rate[i]
        lags=np.arange(max(4,int(period*.55)),max(5,int(period*1.65))+1)
        lags=lags[lags<=i]
        best=-1e12;parent=-1
        if len(lags):
            candidates=score[i-lags]-6*np.log(lags/period)**2
            chosen=int(np.argmax(candidates));best=float(candidates[chosen]);parent=i-int(lags[chosen])
        if i<max(100,2*period) and best<0:best=0.;parent=-1
        score[i]=best+2*evidence[i]-.35;previous[i]=parent
    last=max(1,int(2*60*fps/rate[-1]));end=max(0,count-last)+int(np.argmax(score[max(0,count-last):]))
    path=[];i=end
    while i>=0:path.append(i);i=int(previous[i])
    path=np.asarray(path[::-1],int)
    if len(path)<4:raise ValueError('insufficient acoustic pulse path')
    return path/fps,float(score[end]/max(1,len(path)))


def fit_clock(times,max_error=.040):
    """Piecewise linear q->seconds, with jointly refitted shared knots.

    Adaptive short segments can approximate tempo ramps. No BPM is hard rounded.
    """
    t=np.asarray(times,float);q=np.arange(len(t),dtype=float);n=len(t)
    whole=np.polyfit(q,t,1)
    if np.max(abs(np.polyval(whole,q)-t))<=max_error:
        return np.array([[0.,whole[1]],[n-1.,np.polyval(whole,n-1)]]),dict(segments=1,max_pulse_residual=float(np.max(abs(np.polyval(whole,q)-t))))
    prefix=[np.r_[0.,np.cumsum(v)] for v in (q,q*q,t,t*t,q*t)]
    dp=np.full(n+1,np.inf);parent=np.zeros(n+1,int);dp[0]=-8*max_error**2
    for end in range(2,n+1):
        start=np.arange(0,end-1);valid=(start==0)|(start>=2);start=start[valid]
        count=end-start
        sx,sxx,sy,syy,sxy=[v[end]-v[start] for v in prefix]
        cov=sxy-sx*sy/count;variance=np.maximum(1e-12,sxx-sx*sx/count)
        residual=np.maximum(0,syy-sy*sy/count-cov*cov/variance)
        cost=dp[start]+residual+8*max_error**2
        best=int(np.argmin(cost));dp[end]=cost[best];parent[end]=start[best]
    splits=[n-1];end=n
    while parent[end]>0:
        end=int(parent[end]);splits.append(end)
    splits=np.array(sorted(set([0,*splits])),int)
    # Use a continuous piecewise-linear basis instead of independent phase resets.
    interval=np.clip(np.searchsorted(splits,q,side='right')-1,0,len(splits)-2)
    fraction=(q-splits[interval])/(splits[interval+1]-splits[interval])
    basis=np.zeros((n,len(splits)));basis[np.arange(n),interval]=1-fraction;basis[np.arange(n),interval+1]=fraction
    weights=np.ones(n);fitted=None
    for _ in range(3):
        fitted=np.linalg.lstsq(basis*weights[:,None],t*weights,rcond=None)[0]
        residual=abs(basis@fitted-t);weights=np.minimum(1.,.04/np.maximum(.0001,residual))
    if not np.all(np.diff(fitted)>0):raise ValueError('non-monotonic fitted clock')
    return np.column_stack([splits,fitted]),dict(segments=len(splits)-1,max_pulse_residual=float(np.max(abs(basis@fitted-t))))


def clock_bank(logits,structural,energy):
    raw=sigmoid(logits[:,0]);grid=np.arange(len(raw));head=np.interp(grid,np.arange(len(structural['events']))*4,sigmoid(structural['events'][:,0]))
    evidence=.75*raw+.25*head
    flux=np.maximum(0,np.diff(np.log(np.maximum(energy,1e-5)),prepend=np.log(max(energy[0],1e-5))))
    flux=np.clip(flux/max(.1,float(np.quantile(flux,.9))),0,1)
    beat_curve=tempo_curve(evidence)
    curves=[('beat',beat_curve),('onset',tempo_curve(flux)),
            ('global',np.full(len(evidence),float(np.median(beat_curve))))]
    bank=[]
    for name,curve in curves:
        for multiplier in (.5,2/3,1.,1.5,2.):
            rates=np.clip(curve*multiplier,25,400)
            times,quality=pulse_path(evidence if name in ('beat','global') else .6*evidence+.4*flux,rates)
            clock,fit=fit_clock(times)
            bank.append(dict(name=f'{name}_{multiplier:g}',clock=clock,score=quality,fit=fit,
                observed_pulses=times))
    return bank


def initial_pulse_rate(candidate):
    """Earliest >=8s stable fitted span within the first minute, audio-derived."""
    clock=np.asarray(candidate['clock']);rates=60*np.diff(clock[:,0])/np.diff(clock[:,1])
    weights=np.maximum(0,np.minimum(clock[1:,1],60)-np.maximum(clock[:-1,1],0))
    stable=np.flatnonzero(weights>=8)
    if len(stable):return float(rates[stable[0]])
    if weights.sum()>0:
        order=np.argsort(rates);cum=np.cumsum(weights[order]);return float(rates[order[np.searchsorted(cum,weights.sum()/2)]])
    return float(rates[0])


def select_pulse_level(bank, initial_bpm=None):
    """Select a discrete binary/compound pulse family; never refit to a hint.

    Candidate clocks, phases, boundaries and acoustic scores never use the hint.
    Nearby guide values that select the same family return the identical map.
    """
    ordered=sorted(bank,key=lambda c:c['joint_score'],reverse=True)
    anchor=initial_pulse_rate(ordered[0])
    units=np.array([.25,1/3,.5,2/3,1.,1.5,2.,3.,4.,6.,8.])
    def family(rate):return float(units[np.argmin(abs(np.log2(rate/anchor/units)))])
    if initial_bpm is None:
        return ordered,dict(mode='unhinted',anchor_bpm=anchor,selected_level=0,selected_pulse_multiplier=1.)
    if not np.isfinite(initial_bpm) or initial_bpm<=0:raise ValueError('positive finite BPM hint required')
    unit=family(initial_bpm);level=float(np.log2(unit))
    accepted=[c for c in ordered if family(initial_pulse_rate(c))==unit]
    if not accepted:
        return ordered,dict(mode='pulse_level_only',anchor_bpm=anchor,requested_level=level,
                            selected_level=0,selected_pulse_multiplier=1.,hint_conflict=True,clock_fit_uses_hint=False)
    return accepted+[c for c in ordered if not any(c is a for a in accepted)],dict(
        mode='pulse_level_only',anchor_bpm=anchor,requested_level=level,selected_level=level,
        selected_pulse_multiplier=unit,hint_conflict=False,clock_fit_uses_hint=False)
