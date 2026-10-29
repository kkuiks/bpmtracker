"""Build adaptive runs of beat and downbeat observations."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import math
import numpy as np
from .search_config import CONFIG

def rational(value):return float(Fraction(float(value)).limit_denominator(CONFIG['rational_denominator']))

@dataclass
class Run:
    first: int
    last: int
    period: float
    phase: float
    mass: float
    sx: float
    sy: float
    sxx: float
    sxy: float
    syy: float
    count: int
    ordinal: int
    bad: float=0.

def adaptive_runs(times,weights,channel):
    use=np.flatnonzero(weights>=CONFIG['source_peak_floor'])
    t=np.asarray(times)[use];w=np.asarray(weights)[use]
    live=[];finished=[];all_opening=[]
    def record(run):
        if run.count<CONFIG['source_minimum_fit_observations']:return
        spread=run.sxx-run.sx*run.sx/run.mass
        if spread<=1e-8:return
        p=(run.sxy-run.sx*run.sy/run.mass)/spread
        if p<=0:return
        phi=(run.sy-p*run.sx)/run.mass
        error=max(0.,run.syy-2*phi*run.sy-2*p*run.sxy+phi*phi*run.mass+2*phi*p*run.sx+p*p*run.sxx)
        rms=math.sqrt(error/run.mass)
        density=min(1.,run.count/max(1,round((t[run.last]-t[run.first])/p)+1))
        confidence=math.exp(-.5*(rms/CONFIG['source_run_sigma_seconds'])**2)*density
        if confidence<.35:return
        item={'pulse_bpm':60/p,'phase':phi,'start':float(t[run.first]),'end':float(t[run.last]),
              'first_index':int(use[run.first]),'last_index':int(use[run.last]),'mass':run.mass,
              'observations':run.count,'rms_seconds':rms,'quality':confidence,
              'observed_expected_pulse_fraction':density,
              'channel':channel,'source_only':True,'duration_selected_from_evidence':True}
        finished.append(item)
    for i in range(len(t)):
        survivors=[]
        for run in live:
            ordinal=int(round((t[i]-run.phase)/run.period))
            residual=t[i]-(run.phase+ordinal*run.period)
            compatible=ordinal>run.ordinal and abs(residual)<=3*CONFIG['source_run_sigma_seconds']
            if compatible:
                x=float(ordinal);mass=float(w[i])
                run.mass+=mass;run.sx+=mass*x;run.sy+=mass*t[i]
                run.sxx+=mass*x*x;run.sxy+=mass*x*t[i];run.syy+=mass*t[i]*t[i]
                run.count+=1;run.ordinal=ordinal;run.last=i;run.bad=max(0.,run.bad-.5*mass)
                spread=run.sxx-run.sx*run.sx/run.mass
                if spread>1e-8:
                    p=(run.sxy-run.sx*run.sy/run.mass)/spread
                    if p>0:
                        run.period=p;run.phase=(run.sy-p*run.sx)/run.mass
                record(run)
            else:run.bad+=float(w[i])
            if run.bad>CONFIG['source_run_bad_mass']:record(run)
            else:survivors.append(run)
        if i:
            p=float(t[i]-t[i-1])
            if channel=='BEAT':
                minimum=60/CONFIG['bpm_domain'][1]/max(CONFIG['pulse_factors'])
                maximum=60/CONFIG['bpm_domain'][0]/min(CONFIG['pulse_factors'])
            else:
                lengths=[n*4/d for n,d in CONFIG['signatures']]
                minimum=60/CONFIG['bpm_domain'][1]*min(lengths)
                maximum=60/CONFIG['bpm_domain'][0]*max(lengths)
            if minimum<=p<=maximum:
                a,b=float(w[i-1]),float(w[i]);mass=a+b
                survivors.append(Run(i-1,i,p,float(t[i-1]),mass,b,a*t[i-1]+b*t[i],b,b*t[i],a*t[i-1]**2+b*t[i]**2,2,1))
        unique={}
        for run in survivors:
            key=(round(run.period/.001),round((run.phase%run.period)/.006))
            if key not in unique or run.mass>unique[key].mass:unique[key]=run
        rows=list(unique.values());budget=CONFIG['source_run_budget']
        # Preserve fresh alternatives as well as long supported runs. Neither
        # retention rule fixes a musical region's wall-clock duration.
        fresh=sorted(rows,key=lambda r:-r.first)[:budget//3]
        mature=sorted(rows,key=lambda r:-(r.mass/(1+r.bad)))
        live=fresh+[r for r in mature if all(r is not x for x in fresh)][:budget-len(fresh)]
    for run in live:record(run)
    unique={}
    for row in finished:
        key=(round(row['pulse_bpm']*4),round((row['phase']%(60/row['pulse_bpm']))/.006),row['first_index'])
        if key not in unique or row['mass']>unique[key]['mass']:unique[key]=row
    rows=sorted(unique.values(),key=lambda r:-(r['quality']*math.sqrt(r['mass'])))
    qualified=[r for r in finished if r['mass']>=CONFIG['initial_information_mass'] and r['quality']>=CONFIG['initial_fit_quality']]
    endpoint=min((r['end'] for r in qualified),default=min((r['end'] for r in finished),default=0.))
    # An initial observation can be noise. Keep alternative seeds starting before
    # the first information-qualified endpoint, including their later updates.
    opening=sorted([r for r in finished if r['start']<=endpoint],key=lambda r:-(r['quality']*math.sqrt(r['mass'])))
    return rows[:CONFIG['source_clock_budget']],opening

def prepare(events,family=None):
    pulses,opening=adaptive_runs(np.asarray(events['times']),np.asarray(events['weights']),'BEAT')
    bars,_=adaptive_runs(np.asarray(events['downbeat_times']),np.asarray(events['downbeat_weights']),'BAR')
    if not pulses:return {'available':False,'units':[],'pulses':[],'bars':bars,'duration_seconds':float(events['duration'])}
    first=opening[0] if opening else min(pulses,key=lambda r:(r['start'],-r['quality']*math.sqrt(r['mass'])))
    root=first['pulse_bpm']
    qualified=[r for r in opening if r['mass']>=CONFIG['initial_information_mass'] and r['quality']>=CONFIG['initial_fit_quality']]
    initial_evidence=min(qualified,key=lambda r:r['end']) if qualified else first
    family_rows=[]
    if family:
        family_rows=[family['audio_only_original_proposal']]
        for level in family.get('levels',[]):
            if level.get('best'):family_rows.append(level['best'])
            family_rows+=level.get('top_candidates',[])[:2]
    earliest=sorted(opening,key=lambda r:r['end'])[:6]
    starters=(earliest+opening[:6]) if opening else [first]
    units=[]
    centers=[root/f for f in CONFIG['pulse_factors']]
    centers += [float(row['quarter_bpm'])*f for row in family_rows for f in [.5,1.,2.]]
    groups=[]
    for value in sorted(set(c for c in centers if 30<=c<=400)):
        if groups and math.log(value/groups[-1][0])<=CONFIG['initial_role_merge_log']:groups[-1].append(value)
        else:groups.append([value])
    role_centers=[group[len(group)//2] for group in groups]
    def belongs(bpm,center):
        return min(role_centers,key=lambda value:(abs(math.log(bpm/value)),value))==center
    for center in role_centers:
        multiplier=center/root
        initials=[]
        for run in starters:
            for factor in CONFIG['pulse_factors']:
                bpm=rational(run['pulse_bpm']/factor)
                if not 30<=bpm<=400 or not belongs(bpm,center):continue
                period=60/bpm
                for n,d in CONFIG['signatures']:
                    length=period*n*4/d
                    phases=[run['phase']+k*period for k in range(math.ceil(n*4/d))]
                    phases += [run['phase']-.5*period+k*period for k in range(math.ceil(n*4/d))]
                    db=np.asarray(events['downbeat_times']);dw=np.asarray(events['downbeat_weights'])
                    available=np.flatnonzero((db<=run['end']+1e-8)&(dw>=CONFIG['source_peak_floor']))
                    phases += [float(db[i]) for i in available[np.argsort(-dw[available],kind='stable')[:4]]]
                    for value in phases:
                        phi=value%length
                        if phi>1e-8:phi-=length
                        initials.append({'bpm':bpm,'numerator':n,'denominator':d,'bar_zero_source_seconds':phi,
                            'bootstrap_end':initial_evidence['end'],'bootstrap_source_mass':initial_evidence['mass'],'family_prior':0.,
                            'initial_source_origin':'adaptive_opening_run'})
        expanded=[{**row,'quarter_bpm':float(row['quarter_bpm'])*f} for row in family_rows for f in [.5,1.,2.]]
        for row in expanded:
            bpm=float(row['quarter_bpm'])
            if not 30<=bpm<=400 or not belongs(bpm,center):continue
            signature=row.get('time_signature') or row.get('signature') or '4/4'
            if isinstance(signature,str):
                n,d=map(int,signature.split('/'))
            elif isinstance(signature,dict):n,d=int(signature['numerator']),int(signature['denominator'])
            else:n,d=map(int,signature)
            if [n,d] not in CONFIG['signatures']:n,d=4,4
            length=60/bpm*n*4/d;phi=float(row['offset_seconds'])%length
            if phi>1e-8:phi-=length
            initials.append({'bpm':bpm,'numerator':n,'denominator':d,'bar_zero_source_seconds':phi,
                             'bootstrap_end':initial_evidence['end'],'bootstrap_source_mass':initial_evidence['mass'],
                             'family_prior':CONFIG['family_initial_prior'],'initial_source_origin':'audio_family_proposal_only'})
        if initials:
            unique={}
            for candidate in initials:
                key=(candidate['bpm'],candidate['numerator'],candidate['denominator'],round(candidate['bar_zero_source_seconds']/.004))
                if key not in unique or candidate['family_prior']>unique[key]['family_prior']:unique[key]=candidate
            units.append({'id':len(units),'representative_bpm':center,'counting_multiplier':multiplier,'initials':list(unique.values())})
    return {'available':bool(units),'units':units,'pulses':pulses,'bars':bars,
            'audio_initial_pulse_bpm':root,'adaptive_initial_evidence_end':initial_evidence['end'],
            'duration_seconds':float(events['duration']),'source_only':True,'prepared_before_tap':True,
            'fixed_wall_clock_windows_used':False,'table_or_old_bank_read':False}

def encode(prepared,tap):
    if not prepared['available']:return {'available':False}
    unit=min(prepared['units'],key=lambda u:(abs(math.log(float(tap)/u['representative_bpm'])),u['id']))
    return {'available':True,'unit_id':unit['id'],'numeric_tap_discarded':True}
