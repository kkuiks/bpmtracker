"""Calibrated boundary evidence; full meter vocabulary remains available."""
import numpy as np
from .clock_search import sigmoid

METERS=tuple((n,d) for d in (2,4,8,16,32) for n in range(1,33))
SUBDIVISION=8


def interpolate(clock,q):
    q=np.asarray(q,float);out=np.interp(q,clock[:,0],clock[:,1])
    for a,b,mask in [(clock[0],clock[1],q<clock[0,0]),(clock[-2],clock[-1],q>clock[-1,0])]:
        out=np.where(mask,a[1]+(q-a[0])*(b[1]-a[1])/(b[0]-a[0]),out)
    return out


def logsoft(x):
    x=x-np.max(x,axis=-1,keepdims=True)
    return x-np.log(np.exp(x).sum(axis=-1,keepdims=True))


def decode_meter(clock,logits,structural,change_cost=4.,category_strength=1.,style="softplus"):
    lengths=np.array([round(4*n/d*SUBDIVISION) for n,d in METERS],int)
    end_units=int(np.ceil(clock[-1,0]*SUBDIVISION));max_units=int(lengths.max())
    units=np.arange(-max_units,end_units+max_units+1);quarters=units/SUBDIVISION;times=interpolate(clock,quarters)
    s_times=np.arange(len(structural['events']))/12.5;raw_times=np.arange(len(logits))/50
    raw_down=np.interp(times,raw_times,logits[:,1]);learned_down=np.interp(times,s_times,structural['events'][:,1])
    combined=.6*raw_down+.4*learned_down
    bar_reward=(np.logaddexp(0,np.clip(combined,-15,15))-.15 if style=="softplus" else np.clip(combined,-8,6)-.8)
    bar_reward[times<0]=0
    change=sigmoid(np.interp(times,s_times,structural['events'][:,2]))
    nlog=logsoft(structural['numerator']);dlog=logsoft(structural['denominator'])
    # Small learned categorical terms do not veto unobserved signatures.
    category=np.stack([.04*np.interp(times,s_times,nlog[:,n-1])+.06*np.interp(times,s_times,dlog[:,(2,4,8,16,32).index(d)]) for n,d in METERS],1)
    category*=category_strength
    category[(times<0)|(quarters>clock[-1,0])]=0
    prefix=np.vstack([np.zeros(len(METERS)),np.cumsum(category,axis=0)/SUBDIVISION])
    total=end_units+max_units+1;states=len(METERS)
    dp=np.full((total,states),-1e12);parents=np.full((total,states),-1,np.int16)
    best=np.full(total,-1e12);best_state=np.zeros(total,np.int16)
    complexity=np.array([.15*abs(np.log2((4*n/d)/4)) for n,d in METERS])
    for end in range(1,total):
        starts=end-lengths
        if end>end_units:
            allowed=starts<end_units
        else:allowed=np.ones(states,bool)
        nonnegative=np.maximum(0,starts)
        same=dp[nonnegative,np.arange(states)]
        changed=best[nonnegative]-change_cost*(1-.75*change[starts+max_units])
        use_same=same>=changed
        prior=np.where(use_same,same,changed)
        prev=np.where(use_same,np.arange(states),best_state[nonnegative])
        initial=starts<=0
        prior[initial]=-.05*np.abs(starts[initial])/SUBDIVISION;prev[initial]=-1
        segment=prefix[end+max_units+1]-prefix[starts+max_units+1,np.arange(states)]
        score=prior+bar_reward[starts+max_units]+segment-complexity
        score[~allowed]=-1e12
        dp[end]=score;parents[end]=prev
        best_state[end]=int(np.argmax(score));best[end]=score[best_state[end]]
    terminal=end_units+int(np.argmax(best[end_units:]))
    state=int(best_state[terminal]);bars=[];end=terminal
    while end>0 and state>=0:
        start=end-int(lengths[state]);n,d=METERS[state]
        bars.append(dict(q=start/SUBDIVISION,n=n,d=d))
        previous=int(parents[end,state]);end=start;state=previous
    bars.reverse()
    if not bars:raise ValueError('empty meter path')
    return dict(bars=bars,score=float(best[terminal]/max(1,clock[-1,0])),
                diagnostics=dict(states=states,subdivision=SUBDIVISION,terminal_quarter=terminal/SUBDIVISION))
