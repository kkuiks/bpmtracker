"""Score inferred variable-length pieces and individual source observations."""
from __future__ import annotations
import numpy as np
from .continuous_score import AudioScore
from .common import CONFIG

class Score:
    def __init__(self,events,role_mixture=False):
        self.audio=AudioScore(events);self.duration=self.audio.duration
        self.role_mixture=role_mixture
        self.t,self.w=self.audio.channels[0]
        self.bt,self.bw=self.audio.channels[1]
        self.cumulative=[np.r_[0.,np.cumsum(weights)] for _,weights in self.audio.channels]

    def pulse_values(self,bpm,phase,times=None):
        times=self.t if times is None else np.asarray(times)
        p=60/float(bpm);result=np.zeros(len(times))
        offsets=[0.,.5*p] if self.role_mixture else [0.]
        for factor in CONFIG['pulse_factors']:
            period=p/factor;cost=CONFIG['observation_role_cost']*abs(np.log2(factor))
            for offset in offsets:
                residual=(times-phase-offset+period/2)%period-period/2
                values=np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)-cost
                if offset:values-=CONFIG['offbeat_role_cost']
                result=np.maximum(result,values)
        return result

    def bar_values(self,bpm,phase,n,d,times=None):
        times=self.bt if times is None else np.asarray(times)
        period=60/bpm*n*4/d
        residual=(times-phase+period/2)%period-period/2
        return np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)

    def batch(self,bpm,phase,numerator,denominator,left,right,components=False):
        arrays=np.broadcast_arrays(*[np.atleast_1d(np.asarray(v,float)) for v in [bpm,phase,numerator,denominator,left,right]])
        b,phi,n,d,left,right=arrays;p=60/b
        preferred=np.where((d==8)&(n%3==0),2/3,np.where(d==2,.5,1.))
        neural=[]
        for factor in CONFIG['pulse_factors']:
            value=self.audio.channel(0,p/factor,phi,left,right,CONFIG['neural_sigma_seconds'])
            neural.append(value-CONFIG['observation_role_cost']*abs(np.log2(factor/preferred)))
        beat=np.maximum(0.,np.max(neural,axis=0))
        bar=self.audio.channel(1,p*n*4/d,phi,left,right,CONFIG['neural_sigma_seconds'])
        if self.role_mixture:
            # Latent neural rhythmic readings may vary inside a held musical map.
            # They are observation explanations, never output tempo/phase events.
            obs=self.t[None,:];mass=self.w[None,:]
            use=(obs>=left[:,None])&(obs<right[:,None])
            values=np.zeros((len(b),len(self.t)))
            for factor in CONFIG['pulse_factors']:
                period=p[:,None]/factor
                for offset in [0.,.5]:
                    residual=(obs-phi[:,None]-offset*p[:,None]+period/2)%period-period/2
                    value=np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)
                    value-=CONFIG['observation_role_cost']*abs(np.log2(factor/preferred[:,None]))
                    if offset:value-=CONFIG['offbeat_role_cost']
                    values=np.maximum(values,value)
            explained=(values*mass*use).sum(axis=1)/np.maximum((mass*use).sum(axis=1),1e-9)
            # Retain reverse grid coverage; a denser clock is not automatically
            # correct merely because it can explain more observed peaks.
            beat=.60*explained+.40*beat
            obs=self.bt[None,:];mass=self.bw[None,:]
            use=(obs>=left[:,None])&(obs<right[:,None])
            period=(p*n*4/d)[:,None]
            residual=(obs-phi[:,None]+period/2)%period-period/2
            explained=(np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)*mass*use).sum(axis=1)/np.maximum((mass*use).sum(axis=1),1e-9)
            bar=.80*explained+.20*bar
        pcm=self.audio.channel(2,p*4/d,phi,left,right,CONFIG['pcm_sigma_seconds'])
        prior=np.array([CONFIG['meter_prior'][f'{int(a)}/{int(z)}'] for a,z in zip(n,d)])
        observed=np.searchsorted(self.t,right)-np.searchsorted(self.t,left)
        value=CONFIG['beat_weight']*beat+CONFIG['bar_weight']*bar+CONFIG['pcm_weight']*pcm-prior*(observed>0)
        return (value,beat,bar,pcm) if components else value

    def one(self,state,left,right):
        return float(self.batch(state['bpm'],state['phase'],state['numerator'],state['denominator'],left,right)[0])

    def totals(self,bpm,phase,numerator,denominator,left,right):
        _,beat,bar,pcm=self.batch(bpm,phase,numerator,denominator,left,right,True)
        arrays=np.broadcast_arrays(*[np.atleast_1d(np.asarray(v,float)) for v in [numerator,denominator,left,right]])
        n,d,left,right=arrays;result=np.zeros(len(left));masses=[]
        noise=CONFIG['evidence_clutter_probability']
        for index,(values,key) in enumerate([(beat,'beat_weight'),(bar,'bar_weight'),(pcm,'pcm_weight')]):
            times=self.audio.channels[index][0];a=np.searchsorted(times,left);b=np.searchsorted(times,right)
            mass=self.cumulative[index][b]-self.cumulative[index][a];masses.append(mass)
            likelihood=noise+(1-noise)*np.clip(values,0.,1.)
            result+=CONFIG[key]*mass*np.log(likelihood)
        prior=np.array([CONFIG['meter_prior'][f'{int(a)}/{int(z)}'] for a,z in zip(n,d)])
        return result-prior*masses[0]

    def gate(self,old,new,left,right,changed_rate,changed_meter):
        left=max(0.,left);right=min(self.duration,right)
        if right<=left+1e-8:return False,{'reason':'no_evidence_interval'}
        values=[];pcm_values=[]
        for state in [old,new]:
            _,beat,bar,pcm=self.batch(state['bpm'],state['phase'],state['numerator'],state['denominator'],left,right,True)
            pcm_values.append(float(pcm[0]))
            values.append((float(beat[0]),float(bar[0])))
        ob,om=values[0];nb,nm=values[1]
        mass=float(self.w[(self.t>=left)&(self.t<right)].sum())
        bar_mass=float(self.bw[(self.bt>=left)&(self.bt<right)].sum())
        pulse=mass>=CONFIG['gate_minimum_source_mass'] and ob<=CONFIG['gate_old_ceiling'] and nb>=CONFIG['gate_new_floor'] and nb-ob>=CONFIG['gate_improvement']
        accent=bar_mass>=1. and om<=CONFIG['gate_old_ceiling'] and nm>=CONFIG['gate_new_floor'] and nm-om>=CONFIG['gate_improvement']
        # A real metrical-rate change can keep neural pulse alignment while
        # contradicting the old bar progression. Do not require pulse loss alone.
        tempo_ok=not changed_rate or pulse or accent and nb>=ob-.08
        pcm_mass=float(self.audio.channels[2][1][(self.audio.channels[2][0]>=left)&(self.audio.channels[2][0]<right)].sum())
        if changed_rate and pcm_mass>=2.:
            tempo_ok=tempo_ok and pcm_values[1]>=pcm_values[0]+.02
        meter_ok=not changed_meter or accent
        passed=tempo_ok and meter_ok
        return passed,{'old_beat':ob,'new_beat':nb,'old_bar':om,'new_bar':nm,'beat_mass':mass,'bar_mass':bar_mass,
                       'pulse_mismatch_resolved':bool(pulse),'bar_mismatch_resolved':bool(accent),
                       'adaptive_evidence_start':left,'adaptive_evidence_end':right,'permit':bool(passed)}
