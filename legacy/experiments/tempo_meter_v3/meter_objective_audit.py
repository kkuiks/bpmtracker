"""Reference-only diagnostics of the frozen meter objective; never inference.

Direct path scoring is independent of dynamic programming and reproduces its
boundary, category, duration and transition terms. All totals are unnormalized.
"""
import numpy as np
from .meter_search import METERS, SUBDIVISION, interpolate, logsoft
from .clock_search import sigmoid


def objective_arrays(clock, logits, structural):
    lengths = np.array([round(4*n/d*SUBDIVISION) for n,d in METERS])
    end = int(np.ceil(clock[-1,0]*SUBDIVISION))
    guard = int(lengths.max())
    q = np.arange(-guard, end+guard+1)/SUBDIVISION
    times = interpolate(clock, q)
    st = np.arange(len(structural['events']))/12.5
    rt = np.arange(len(logits))/50
    reward = np.clip(.6*np.interp(times,rt,logits[:,1])+
                     .4*np.interp(times,st,structural['events'][:,1]),-8,6)-.8
    reward[times<0] = 0
    change = sigmoid(np.interp(times,st,structural['events'][:,2]))
    nlog,dlog = logsoft(structural['numerator']),logsoft(structural['denominator'])
    category = np.stack([.04*np.interp(times,st,nlog[:,n-1])+
                         .06*np.interp(times,st,dlog[:,(2,4,8,16,32).index(d)])
                         for n,d in METERS],1)
    category[(times<0)|(q>clock[-1,0])] = 0
    return dict(lengths=lengths,end=end,guard=guard,reward=reward,change=change,
                prefix=np.vstack([np.zeros(len(METERS)),np.cumsum(category,axis=0)/SUBDIVISION]))


def score_path(bars, arrays, change_cost=4.):
    """Reject paths that the exact frozen DP cannot represent."""
    result=dict(boundary=0.,category=0.,length_prior=0.,transition=0.,initial=0.)
    previous=None;last_end=None;g=arrays['guard'];details=[]
    for index,bar in enumerate(bars):
        state=METERS.index((bar['n'],bar['d']))
        scaled=bar['q']*SUBDIVISION
        if abs(scaled-round(scaled))>1e-4:
            raise ValueError('bar phase is outside the 1/8-quarter lattice')
        start=int(round(scaled));end=start+int(arrays['lengths'][state])
        if index==0:
            if not start<=0<end:raise ValueError('first bar must straddle clock origin')
        elif start!=last_end:raise ValueError('discontinuous bar path')
        if end>=arrays['end']+g+1 or (end>arrays['end'] and start>=arrays['end']):
            raise ValueError('bar exceeds frozen terminal support')
        term=dict(boundary=float(arrays['reward'][start+g]),
                  category=float(arrays['prefix'][end+g+1,state]-arrays['prefix'][start+g+1,state]),
                  length_prior=-.15*abs(float(np.log2((4*bar['n']/bar['d'])/4))),
                  transition=0. if previous is None or state==previous else
                  -change_cost*(1-.75*float(arrays['change'][start+g])),
                  initial=-.05*abs(start)/SUBDIVISION if index==0 else 0.)
        for key,value in term.items():result[key]+=value
        details.append(dict(**bar,terms=term))
        previous=state;last_end=end
    if last_end is None or last_end<arrays['end']:raise ValueError('path ends before terminal')
    return dict(**result,total=sum(result.values()),bar_count=len(bars),details=details)


def reference_problem(raw):
    """Qualified support only; retain original quarter origin and partial bars.

    The first complete quarter at/after support start anchors q=0. This may
    omit less than one opening quarter from this diagnostic, never from scoring.
    """
    factor=raw['quarters_per_pulse']['numerator']/raw['quarters_per_pulse']['denominator']
    knots=np.array([[k['pulse']*factor,k['source_seconds']] for k in raw['clock_knots']])
    if len(raw['support_seconds'])!=1:raise ValueError('diagnostic requires a single qualified span')
    lo,hi=raw['support_seconds'][0]
    qlo,qhi=np.interp([lo,hi],knots[:,1],knots[:,0])
    origin=float(np.ceil(qlo-1e-6))
    first=float(interpolate(knots,[origin])[0])
    clock=np.vstack([[origin,first],knots[(knots[:,0]>origin)&(knots[:,0]<qhi)],[qhi,hi]])
    clock[:,0]-=origin
    events=[dict(q=e['pulse']*factor-origin,n=e['numerator'],d=e['denominator']) for e in raw['meter_events']]
    anchor=raw['bar_anchor_pulse']*factor-origin
    active=max(0,max((i for i,e in enumerate(events) if e['q']<=1e-6),default=0))
    if active:anchor=events[active]['q']
    length=4*events[active]['n']/events[active]['d']
    start=anchor+np.floor((0-anchor)/length+1e-8)*length
    bars=[];end_units=int(np.ceil(clock[-1,0]*SUBDIVISION))
    while start*SUBDIVISION < end_units-1e-4:
        while active+1<len(events) and events[active+1]['q']<=start+1e-5:
            active+=1
        event=events[active];length=4*event['n']/event['d']
        if active+1<len(events) and start+1e-5<events[active+1]['q']<start+length-1e-5:
            raise ValueError('reference requires non-barline meter transition')
        bars.append(dict(q=float(start),n=event['n'],d=event['d']))
        start+=length
    return clock,bars,dict(reference_support=[lo,hi],diagnostic_clock_support=[first,hi],
                           original_quarter_origin=origin)


def ideal_observations(clock,bars,logits,structural):
    """Perfect labels rendered at the existing 50/12.5 Hz interfaces."""
    value={k:v.copy() for k,v in structural.items()}
    times=np.arange(len(logits))/50;st=np.arange(len(value['events']))/12.5
    starts=interpolate(clock,[b['q'] for b in bars])
    def peaks(t,events,width):
        out=np.full(len(t),-7.)
        for at in events:
            out=np.maximum(out,-7+16*np.exp(-.5*((t-at)/width)**2))
        return out
    raw=logits.copy();raw[:,1]=peaks(times,starts,.045)
    value['events'][:,1]=peaks(st,starts,.045)
    changes=[starts[i] for i in range(1,len(bars)) if (bars[i]['n'],bars[i]['d'])!=(bars[i-1]['n'],bars[i-1]['d'])]
    value['events'][:,2]=peaks(st,changes,.12)
    nums=np.full_like(value['numerator'],-6.);dens=np.full_like(value['denominator'],-6.)
    for i,bar in enumerate(bars):
        stop=starts[i+1] if i+1<len(bars) else float('inf')
        mask=(st>=starts[i])&(st<stop)
        nums[mask,bar['n']-1]=6.;dens[mask,(2,4,8,16,32).index(bar['d'])]=6.
    value['numerator']=nums;value['denominator']=dens
    return raw,value
