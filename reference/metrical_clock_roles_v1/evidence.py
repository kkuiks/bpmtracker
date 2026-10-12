"""Interpret neural pulses at latent quarter roles instead of every quarter.

The bar-cycle factor is a nuisance hypothesis, not a certified time signature.
It may represent an observed multi-bar cycle. Raw logits contribute soft tick
coverage; event timestamps contribute explanation and timing. Numeric taps and
evaluation files are not accepted here.
"""
from __future__ import annotations
from fractions import Fraction
import math
import numpy as np
from scipy.special import expit
from .common import CONFIG

def soft_profile(logits,fps,sigma):
    p=expit(logits.astype(np.float64)); result=np.zeros_like(p)
    for j in range(-int(math.ceil(.08*fps)),int(math.ceil(.08*fps))+1):
        if not j: shifted=p
        elif j>0: shifted=np.r_[p[j:],np.zeros(j)]
        else: shifted=np.r_[np.zeros(-j),p[:j]]
        result=np.maximum(result,shifted*math.exp(-.5*(j/fps/sigma)**2))
    return result

def pulse_curves(times,weights,duration,period,phase,centers,soft,fps,sigma):
    phase%=period; first=math.ceil(-phase/period)
    ticks=phase+np.arange(first,math.ceil((duration-phase)/period))*period
    if not len(ticks):return [np.zeros(len(centers))]*4
    k=np.rint((times-phase)/period).astype(int)-first
    residual=times-(phase+(k+first)*period)
    keep=(k>=0)&(k<len(ticks))&(abs(residual)<=min(.08,period*.25))
    reward=weights[keep]*np.exp(-.5*(residual[keep]/sigma)**2)
    matched=np.zeros(len(ticks));np.maximum.at(matched,k[keep],reward)
    raw=np.interp(ticks,np.arange(len(soft))/fps,soft,left=0,right=0)
    # Soft non-thresholded observations retain weak peaks. Event and raw-channel
    # evidence are correlated; this is a heuristic score, not a probability.
    cover=.5*matched+.5*raw
    cp=np.r_[0.,np.cumsum(cover)];mp=np.r_[0.,np.cumsum(matched)]
    wc=np.r_[0.,np.cumsum(weights)];nc=np.r_[0.,np.cumsum(matched>=.25)]
    results=[]
    for window in [2.,8.]:
        left=np.maximum(0,centers-window/2);right=np.minimum(duration,centers+window/2)
        a,b=np.searchsorted(ticks,left),np.searchsorted(ticks,right)
        i,j=np.searchsorted(times,left),np.searchsorted(times,right)
        mass=wc[j]-wc[i]
        coverage=np.divide(cp[b]-cp[a],b-a,out=np.zeros(len(a)),where=b>a)
        explanation=np.minimum(1.,np.divide(mp[b]-mp[a],mass,out=np.zeros(len(a)),where=mass>0))
        q=2*coverage*explanation/np.maximum(coverage+explanation,1e-9)
        results.append(q)
        if window==8.:results.extend([nc[b]-nc[a],mass])
    return [r.astype(np.float32) for r in results]

def bar_base(times,weights,duration,period,centers):
    z=weights*np.exp(2j*np.pi*times/period);prefix=np.r_[0j,np.cumsum(z)]
    mass_prefix=np.r_[0.,np.cumsum(weights)]; result=[]
    for window in [4.,16.]:
        left=np.maximum(0,centers-window/2);right=np.minimum(duration,centers+window/2)
        a,b=np.searchsorted(times,left),np.searchsorted(times,right)
        value=prefix[b]-prefix[a];mass=mass_prefix[b]-mass_prefix[a]
        coherence=abs(value)/np.maximum(mass,1e-9)
        coverage=np.minimum(1.,mass*period/np.maximum(right-left,.01))
        quality=coherence*np.sqrt(coverage)*np.minimum(1.,mass/2.)
        phase=(np.angle(value)*period/(2*np.pi))%period
        result.append((quality,phase,mass))
    return result

def build(events,sensors,clocks,cfg=None):
    cfg=dict(CONFIG if cfg is None else cfg);duration=float(events['duration'])
    centers=(np.arange(math.ceil(duration/cfg['step']))+.5)*cfg['step'];n=len(centers)
    times,weights=events['times'],events['weights'];dt,dw=events['downbeat_times'],events['downbeat_weights']
    fps=float(sensors['fps']);soft=soft_profile(sensors['beat_logits'],fps,cfg['beat_sigma_seconds'])
    pulse_cache={};bar_cache={};pulse_states=[];initial_choices=[];per_clock=[]
    for j,h in enumerate(clocks[:cfg['source_candidate_budget']]):
        p=60/h['bpm'];phi=h['phase']%p;options=[]
        for role in cfg['role_periods_in_quarters']:
            f=Fraction(role).limit_denominator(4)
            role_options=[]
            for slot in range(f.numerator):
                offset=slot/f.denominator; period=p*role;phase=(phi+p*offset)%period
                # Reuse exact parameters only; rounded keys are not fit snapping.
                key=(period.hex(),phase.hex())
                if key not in pulse_cache:
                    pulse_cache[key]=pulse_curves(times,weights,duration,period,phase,centers,soft,fps,cfg['beat_sigma_seconds'])
                q2,q8,count,mass=pulse_cache[key]
                supported=(q8>=cfg['minimum_source_quality'])&(count>=cfg['minimum_events'])
                if not supported.any():continue
                rank=float(np.maximum(q8-.45,0)[supported].sum()*cfg['step'])
                role_options.append((rank,slot,offset,q2,q8,count,mass))
            if role_options:
                best=max(role_options,key=lambda x:(x[0],-x[1]))
                options.append((role,best))
                if role==1.:
                    initial_choices.append((j,best[4],best[5],best[0]))
        # Keep the native-quarter ablation plus two alternate observed roles.
        native=[o for o in options if o[0]==1.]
        alternates=sorted([o for o in options if o[0]!=1.],key=lambda o:-o[1][0])[:2]
        options=sorted(native+alternates,key=lambda o:-o[1][0])
        ids=[]
        for role,best in options:
            rank,slot,offset,q2,q8,count,mass=best
            ids.append(len(pulse_states))
            pulse_states.append({'clock_index':j,'bpm':h['bpm'],'phase':phi,
                                 'role_period_quarters':role,'role_offset_quarters':offset,
                                 'source_rank':rank,'q2':q2,'q8':q8,'mass':mass})
        per_clock.append(ids)
    # Round-robin per-clock alternatives preserve local and metrical diversity.
    order=[]
    for depth in range(3):
        selected=[ids[depth] for ids in per_clock if len(ids)>depth]
        selected.sort(key=lambda i:-pulse_states[i]['source_rank']);order.extend(selected)
    order=order[:cfg['state_budget']]
    ps=[pulse_states[i] for i in order]
    if not ps:
        return {'time':centers,'duration':duration,'pulse_states':[],'joint_states':[],
                'beat_score':np.empty((n,0),np.float32),'bar_score':np.empty((n,0),np.float32),
                'quality':np.empty((n,0),np.float32),'bar_phase':np.empty((n,0),np.float32),
                'information':np.zeros(n,bool),'source_unit':{'available':False},'statistics':{}}
    beat=np.column_stack([3*(.75*s['q2']+.25*s['q8']) for s in ps]).astype(np.float32)
    q8=np.column_stack([s['q8'] for s in ps]).astype(np.float32)
    info=ps[0]['mass']>=1.5;beat[~info]=0
    joint=[];bar_columns=[];bar_phase_columns=[];per_pulse=[]
    for i,s in enumerate(ps):
        p=60/s['bpm'];phi=s['phase'];choices=[]
        for meter in cfg['bar_periods_in_quarters']:
            key=(float(s['bpm']),float(meter))
            if key not in bar_cache:bar_cache[key]=bar_base(dt,dw,duration,p*meter,centers)
            small,large=bar_cache[key]
            short,phase_short,_=small;long,phase_long,_=large
            e1=abs((phase_short-phi+p/2)%p-p/2);e2=abs((phase_long-phi+p/2)%p-p/2)
            bq=.5*short*np.exp(-.5*(e1/cfg['downbeat_sigma_seconds'])**2)+.5*long*np.exp(-.5*(e2/cfg['downbeat_sigma_seconds'])**2)
            rank=float(np.sum(bq*np.maximum(s['q8']-.45,0)))
            choices.append((rank,meter,bq,phase_long))
        # Include 4 quarter cycles for the ablations; two additional local cycles.
        selected=[c for c in choices if c[1]==4.]
        selected+=sorted([c for c in choices if c[1]!=4.],key=lambda c:-c[0])[:2]
        selected.sort(key=lambda c:-c[0]);ids=[]
        for rank,meter,bq,phase_long in selected:
            contexts=[(mq,skip) for mq in cfg['meter_quarters'] for skip in cfg['downbeat_observation_roles']
                      if abs(mq*skip-meter)<1e-8]
            contexts.sort(key=lambda v:(v[1]<1.,v[0]!=4.,v[1]!=1.,v[0]))
            for mq,skip in contexts:
                ids.append(len(joint));joint.append({k:v for k,v in s.items() if k not in ['q2','q8','mass']})
                joint[-1].update({'pulse_index':i,'observed_bar_period_quarters':meter,
                                 'meter_quarters':mq,'downbeat_observation_role':skip,
                                 'bar_source_rank':rank})
                bar_columns.append((3*bq).astype(np.float32));bar_phase_columns.append(phase_long.astype(np.float32))
        per_pulse.append(ids)
    jo=[]
    for depth in range(max((len(ids) for ids in per_pulse),default=0)):
        selected=[ids[depth] for ids in per_pulse if len(ids)>depth]
        selected.sort(key=lambda i:-(joint[i]['source_rank']+joint[i]['bar_source_rank']*.2));jo.extend(selected)
    jo=jo[:cfg['state_budget']]
    initial={'available':False}
    for a,center in enumerate(centers):
        if center>cfg['initial_deadline_seconds']:break
        good=[(j,float(q[a:a+4].mean()),rank) for j,q,c,rank in initial_choices
              if len(q[a:a+4])==4 and np.all(q[a:a+4]>=.72) and np.all(c[a:a+4]>=5)]
        if good:
            j,_,_=max(good,key=lambda x:(x[1],x[2],-x[0]));start=max(0.,float(center-cfg['step']/2))
            initial={'available':True,'base_bpm':float(clocks[j]['bpm']),
                     'scope_start':start,'scope_end':min(duration,start+cfg['initial_scope_seconds']),
                     'source_clock_index':j};break
    return {'time':centers,'duration':duration,'pulse_states':[{k:v for k,v in s.items() if k not in ['q2','q8','mass']} for s in ps],
            'joint_states':[joint[i] for i in jo],'beat_score':beat,'quality':q8,
            'bar_score':np.column_stack([bar_columns[i] for i in jo]),
            'bar_phase':np.column_stack([bar_phase_columns[i] for i in jo]),
            'information':info,'source_unit':initial,
            'statistics':{'original_clocks':len(clocks),'pulse_templates':len(pulse_cache),
                          'pulse_states':len(ps),'joint_states':len(jo),'unique_bar_periods':len(bar_cache),
                          'source_only':True,'references_used':False}}
