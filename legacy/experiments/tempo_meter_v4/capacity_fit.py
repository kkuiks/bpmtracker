"""Robust clock fitting with new event-derived change points and bar feedback."""
import numpy as np
from .latent_clock import time_at


def fit(path,obs,bars=None,penalty=.025):
    assignments=path['assignments'];q=assignments[:,1];t=obs['events'][assignments[:,0].astype(int)]
    weight=np.maximum(.1,obs['event_strength'][assignments[:,0].astype(int)])
    if bars is not None:
        bq=np.array([b['q'] for b in bars]);bt=time_at(path['clock'],bq)
        from .observations import local_peaks,refined_times
        observed=refined_times(obs['down'],local_peaks(obs['down'],.2),obs['fps'])
        for position,predicted in zip(bq,bt):
            if not len(observed):break
            i=int(np.argmin(abs(observed-predicted)))
            if abs(observed[i]-predicted)<.12:
                q=np.r_[q,position];t=np.r_[t,observed[i]];weight=np.r_[weight,.75]
    order=np.argsort(q);q,t,weight=q[order],t[order],weight[order]
    # Candidate change coordinates include observed quarter/subdivision events
    # and bar boundaries. They are not inherited from the old v3 knot bank.
    unique=np.unique(q);n=len(unique)
    if n<4:return path['clock'],dict(reason='insufficient_assignments')
    # Robustify observed outliers against the incoming path before segmentation.
    residual=t-time_at(path['clock'],q)
    w=weight*np.minimum(1.,.04/np.maximum(abs(residual),1e-8))
    prefix=[np.r_[0.,np.cumsum(v)] for v in (w,w*q,w*q*q,w*t,w*t*t,w*q*t)]
    first=np.searchsorted(q,unique);last=np.searchsorted(q,unique,side='right')
    cost=np.full(n+1,np.inf);parent=np.zeros(n+1,int);cost[0]=-penalty
    for stop in range(2,n+1):
        starts=np.arange(0,stop-1);valid=(starts==0)|(starts>=2);starts=starts[valid]
        a=first[starts];b=last[stop-1]
        sw,sx,sxx,sy,syy,sxy=[v[b]-v[a] for v in prefix]
        variance=np.maximum(1e-9,sxx-sx*sx/sw)
        slope=(sxy-sx*sy/sw)/variance
        sse=np.maximum(0,syy-sy*sy/sw-(sxy-sx*sy/sw)**2/variance)
        score=cost[starts]+sse+penalty
        score[(slope<60/400)|(slope>60/25)]=np.inf
        k=int(np.argmin(score));cost[stop]=score[k];parent[stop]=starts[k]
    parts=[];stop=n
    while stop:
        start=int(parent[stop]);parts.append((start,stop));stop=start
    parts.reverse()
    lines=[]
    for start,stop in parts:
        mask=(q>=unique[start])&(q<=unique[stop-1])
        slope,intercept=np.polyfit(q[mask],t[mask],1,w=np.sqrt(w[mask]))
        lines.append((float(slope),float(intercept)))
    proposed=[unique[0]]
    for i in range(1,len(parts)):
        left,right=lines[i-1],lines[i]
        lower=unique[parts[i-1][0]];upper=unique[parts[i][1]-1]
        gap_left=unique[parts[i-1][1]-1];gap_right=unique[parts[i][0]]
        crossing=(right[1]-left[1])/(left[0]-right[0]) if abs(left[0]-right[0])>1e-8 else (gap_left+gap_right)/2
        if not max(lower,gap_left-1)<=crossing<=min(upper,gap_right+1):crossing=(gap_left+gap_right)/2
        proposed.append(float(crossing))
    proposed.append(unique[-1]);knots=np.asarray(proposed)
    # Keep the full source domain and allow genuine changes inside a bar.
    knots=np.unique(knots)
    if len(knots)<2:return path['clock'],dict(reason='insufficient_supported_domain')
    index=np.clip(np.searchsorted(knots,q,side='right')-1,0,len(knots)-2)
    fraction=(q-knots[index])/(knots[index+1]-knots[index])
    basis=np.zeros((len(q),len(knots)));basis[np.arange(len(q)),index]=1-fraction;basis[np.arange(len(q)),index+1]=fraction
    initial=time_at(path['clock'],knots);fitted=initial.copy()
    for _ in range(5):
        residual=basis@fitted-t;robust=np.minimum(1.,.04/np.maximum(abs(residual),1e-8))*weight
        fitted=np.linalg.solve(basis.T@(robust[:,None]*basis)+np.eye(len(knots))*1e-8,basis.T@(robust*t)+1e-8*initial)
    if np.any(np.diff(fitted)<=0):return path['clock'],dict(reason='nonmonotonic_proposal_rejected')
    clock=np.column_stack([knots,fitted])
    # Unobserved source margins inherit the last fitted rate. Do not pin an
    # old uncertain fractional endpoint and invent a final tempo segment.
    if clock[0,0]>path['clock'][0,0]:
        slope=(fitted[1]-fitted[0])/(knots[1]-knots[0])
        firstq=path['clock'][0,0]
        clock=np.vstack([[firstq,fitted[0]+(firstq-knots[0])*slope],clock])
    if fitted[-1]<obs['duration']:
        slope=(fitted[-1]-fitted[-2])/(knots[-1]-knots[-2])
        endq=knots[-1]+(obs['duration']-fitted[-1])/slope
        clock=np.vstack([clock,[endq,obs['duration']]])
    return clock,dict(reason='joint_coordinates_and_new_change_points',knots=len(knots),bar_feedback=bars is not None)
