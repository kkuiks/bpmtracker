"""Whole-sequence beam search over quarter, neural-role and bar-cycle states.

Changes of neural observation role are cheaper than changing the physical clock.
Initial unit constrains only its source-defined initial episode. A true 2x rate
change remains available. There is no sustained-contradiction veto or weak mute.
"""
from __future__ import annotations
import math
import numpy as np
from .common import CONFIG

def layer(bpm,base,cfg):
    f=np.asarray(cfg['unit_multipliers']);v=np.abs(np.log(np.asarray(bpm)[...,None]/base/f))
    return np.argmin(v,axis=-1)

def destinations(emission,bpms,limit,allowed):
    indices=np.flatnonzero(allowed)
    ranked=indices[np.argsort(emission[indices],kind='stable')[::-1]]
    selected=[];counts={}
    for i in ranked:
        rate=float(bpms[i]);count=counts.get(rate,0)
        if count:continue
        selected.append(i);counts[rate]=1
        if len(selected)>=limit:return np.array(selected,dtype=int)
    for i in ranked:
        rate=float(bpms[i]);count=counts.get(rate,0)
        if count>=3:continue
        selected.append(i);counts[rate]=count+1
        if len(selected)>=limit:break
    return np.array(selected,dtype=int)

def predict(tab,method,options,packet=None,cfg=None):
    cfg={**CONFIG,**(cfg or {}),**options};bars=options.get('bars',True);roles=options.get('roles',True)
    if bars:
        states=tab['joint_states'];pulse=np.array([s['pulse_index'] for s in states],int)
        e=(1-cfg['downbeat_weight'])*tab['beat_score'][:,pulse]+cfg['downbeat_weight']*tab['bar_score']
        quality=tab['quality'][:,pulse]
    else:
        states=[{**s,'pulse_index':i,'observed_bar_period_quarters':None} for i,s in enumerate(tab['pulse_states'])]
        e=tab['beat_score'].copy();quality=tab['quality']
    n,k=e.shape;duration=float(tab['duration'])
    if not k:return {'status':'NO_SEED','accepted':[],'latent_context':[],'diagnostic':[],
                     'duration_seconds':duration,'method':method,'initial_unit_scope':None}
    b=np.array([s['bpm'] for s in states]);phi=np.array([s['phase'] for s in states]);p=60/b
    role=np.array([s['role_period_quarters'] for s in states]);off=np.array([s['role_offset_quarters'] for s in states])
    meter=np.array([s.get('meter_quarters',4.) for s in states]);clock=np.array([s['clock_index'] for s in states])
    down_role=np.array([s.get('downbeat_observation_role',1.) for s in states])
    active=np.ones(k,bool) if roles else abs(role-1)<1e-8
    if bars and not cfg.get('allow_subbar',False):active &= down_role>=1.
    if not active.any():return {'status':'NO_SEED','accepted':[],'latent_context':[],'diagnostic':[],
                                  'duration_seconds':duration,'method':method,'initial_unit_scope':None}
    source=tab['source_unit'];constraint=packet is not None and packet.get('available',False)
    chosen_layer=packet.get('unit_index') if constraint else None
    if constraint and (packet['base_bpm']!=source['base_bpm'] or packet['scope_end']!=source['scope_end']):
        raise RuntimeError('Encoded packet is not source-defined')
    masks=active.copy()
    if constraint and source['scope_start']<=0:
        masks &= layer(b,source['base_bpm'],cfg)==chosen_layer
    # The role prior occurs once at the unconstrained start, never once per second.
    # It cannot accumulate evidence that a sparse observation changes BPM.
    initial=e[0]*cfg['step']-cfg['role_prior_cost']*abs(np.log2(role))
    if bars:initial-=cfg['initial_meter_prior']*(meter!=4.)+.015*abs(np.log2(down_role))
    initial[~masks]=-np.inf
    beam=np.argsort(initial,kind='stable')[-cfg['beam']:];beam=beam[np.isfinite(initial[beam])]
    if not len(beam):return {'status':'NO_COMPATIBLE_INITIAL_UNIT','accepted':[],'latent_context':[],
                             'diagnostic':[],'duration_seconds':duration,'method':method,
                             'initial_unit_scope':{'start':source['scope_start'],'end':source['scope_end']}}
    scores=initial[beam];history=[beam.copy()];parents=[None]
    for t in range(1,n):
        allowed=active.copy()
        if constraint and source['scope_start']<=tab['time'][t]<source['scope_end']:
            allowed &= layer(b,source['base_bpm'],cfg)==chosen_layer
        # Equivalent bar/beat-role hypotheses can have exactly the same emission.
        # Rank proposals with the existing context costs so an arbitrary tie does
        # not exclude the continuing meter before the beam can evaluate it.
        lead=int(beam[np.argmax(scores)])
        proposal=e[t]-cfg['role_change_cost']*((role!=role[lead])|(off!=off[lead]))
        if bars:
            proposal=proposal-cfg['meter_change_cost']*(meter!=meter[lead])
            proposal=proposal-cfg['downbeat_role_change_cost']*(down_role!=down_role[lead])
        new=destinations(proposal,b,cfg['destination_count'],allowed)
        dest=np.unique(np.r_[beam[allowed[beam]],new])
        same_clock=clock[beam,None]==clock[dest][None,:]
        same_rate=abs(b[beam,None]-b[dest][None,:])<1e-8
        cost=cfg['tempo_change_cost']*(~same_rate)+cfg['rate_distance_cost']*abs(np.log2(b[beam,None]/b[dest][None,:]))
        cost+=cfg['role_change_cost']*((role[beam,None]!=role[dest][None,:])|(off[beam,None]!=off[dest][None,:]))
        if bars:
            cost+=cfg['meter_change_cost']*(meter[beam,None]!=meter[dest][None,:])
            cost+=cfg['downbeat_role_change_cost']*(down_role[beam,None]!=down_role[dest][None,:])
        # Same-rate phase alternatives can reset after contradictory observations.
        x=tab['time'][t]-cfg['step']/2
        left=phi[beam]+np.rint((x-phi[beam])/p[beam])*p[beam]
        right=phi[dest]+np.rint((x-phi[dest])/p[dest])*p[dest]
        gap=abs(left[:,None]-right[None,:]);gap=np.minimum(gap,np.minimum(p[beam,None],p[dest][None,:])/2)
        cost+=cfg['phase_change_cost']*(same_rate&~same_clock)
        cost+=cfg['phase_change_cost']*(~same_clock)*np.minimum(1.,gap/.07)
        if cfg.get('gauge_change_guard',True):
            # Re-labeling a physically identical neural pulse is not fresh tempo
            # evidence. A changed bar observation may still justify such a rate
            # change. This is not a ban on real 2x changes of neural pulse speed.
            native_old=p[beam]*role[beam];native_new=p[dest]*role[dest]
            native_phi_old=phi[beam]+p[beam]*off[beam];native_phi_new=phi[dest]+p[dest]*off[dest]
            native_same=abs(native_old[:,None]-native_new[None,:])<1e-7
            phase_delta=abs((native_phi_old[:,None]-native_phi_new[None,:]+native_old[:,None]/2)%native_old[:,None]-native_old[:,None]/2)
            gauge=(~same_rate)&native_same&(phase_delta<cfg['beat_sigma_seconds'])
            if bars:
                improvement=tab['bar_score'][t,dest][None,:]-tab['bar_score'][t,beam][:,None]
            else:improvement=np.zeros_like(cost)
            cost[gauge&(improvement<cfg['minimum_bar_gain_for_gauge_change'])]=np.inf
        values=scores[:,None]-cost
        arg=np.argmax(values,axis=0);best=values[arg,np.arange(len(dest))]+e[t,dest]*cfg['step']
        keep=np.argsort(best,kind='stable')[-cfg['beam']:];beam=dest[keep];scores=best[keep]
        history.append(beam.copy());parents.append(arg[keep])
    final=int(np.argmax(scores));path=np.empty(n,int)
    for t in range(n-1,-1,-1):
        path[t]=history[t][final]
        if t:final=int(parents[t][final])
    edges=np.r_[0,np.flatnonzero(path[1:]!=path[:-1])+1,n];latent=[];accepted=[]
    for a,z in zip(edges[:-1],edges[1:]):
        i=int(path[a]);s=states[i];left=float(a*cfg['step']);right=min(duration,float(z*cfg['step']))
        context={**s,'start':left,'end':right,'state_index':i,
                 'quarter_unit_is_inferred':True,'bar_cycle_is_not_certified_meter':True}
        if bars:context['bar_phase_source_midpoint']=float(tab['bar_phase'][(a+z-1)//2,i])
        latent.append(context)
        if accepted and accepted[-1]['clock_index']==s['clock_index']:
            accepted[-1]['end']=right
        else:accepted.append({'start':left,'end':right,'bpm':s['bpm'],'phase':s['phase'],
                              'period':60/s['bpm'],'clock_index':s['clock_index'],
                              'provenance':'source_clock_joint_role_sequence'})
    weak=quality[np.arange(n),path]<cfg['minimum_source_quality']
    starts=np.flatnonzero(weak&~np.r_[False,weak[:-1]]);ends=np.flatnonzero(weak&~np.r_[weak[1:],False])+1
    diagnostic=[{'start':float(a*cfg['step']),'end':min(duration,float(z*cfg['step'])),
                 'status':'HELD_WEAK_EVIDENCE'} for a,z in zip(starts,ends)]
    boundary_refinements=[]
    if cfg.get('refine_boundaries',False):
        # Conditional affine-quarter phase transport was explored previously.
        # This arm tests it only after the new role model has selected clocks.
        for left,right in zip(accepted,accepted[1:]):
            if left['bpm']==right['bpm']:continue
            x=right['start'];slope=left['bpm']/60-right['bpm']/60
            if abs(slope)<1e-9:continue
            intercept=-left['phase']*left['bpm']/60+right['phase']*right['bpm']/60
            crossing=(round(slope*x+intercept)-intercept)/slope
            low=left['start']+.25;high=right['end']-.25
            if low<crossing<high and abs(crossing-x)<=4.:
                boundary_refinements.append({'original':x,'refined':crossing})
                left['end']=crossing;right['start']=crossing
    return {'status':'OK','method':method,'duration_seconds':duration,'accepted':accepted,
            'latent_context':latent,'diagnostic':diagnostic,
            'initial_unit_scope':{'start':source['scope_start'],'end':source['scope_end']} if constraint else None,
            'search_is_approximate':True,'score':float(scores.max()),
            'source_state_count':k,'beam':cfg['beam'],'destination_count':cfg['destination_count'],
            'physical_clock_continues_through_weak_evidence':True,
            'boundary_refinements':boundary_refinements}
