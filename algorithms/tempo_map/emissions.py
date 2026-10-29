"""Additive source observation costs for continuous affine map segments.

Neural/PCM observations are immutable. Observation roles are latent explanatory
readings, never map events. Channels are a weighted composite likelihood rather
than a claim of independent calibrated probabilities. Missing predicted ticks
are not evidence in this first ablation; the density filter and source gate
remain responsible for unsupported fast subdivisions.
"""
import numpy as np
from .scoring import Score as GateScore
from .common import CONFIG


class Score(GateScore):
    def __init__(self, events):
        super().__init__(events)
        self.emission_cache = {}
        self.tick_cache = {}

    def emission_prefixes(self, bpm, phase, n, d):
        key = (float(bpm), float(phase), int(n), int(d))
        if key in self.emission_cache:
            return self.emission_cache[key]
        noise = CONFIG['evidence_clutter_probability']
        prefixes = []
        for index, ((times, weights), weight_key) in enumerate(zip(
                self.audio.channels, ('beat_weight', 'bar_weight', 'pcm_weight'))):
            if index == 0:
                agreement = self.pulse_values(bpm, phase, times)
            else:
                period = 60. / bpm * (n * 4. / d if index == 1 else 1.)
                sigma = CONFIG['neural_sigma_seconds'] if index == 1 else CONFIG['pcm_sigma_seconds']
                residual = (times - phase + period / 2.) % period - period / 2.
                agreement = np.exp(-.5 * (residual / sigma) ** 2)
            likelihood = noise + (1. - noise) * np.clip(agreement, 0., 1.)
            costs = CONFIG[weight_key] * weights * np.log(likelihood)
            if index == 1: costs *= .5
            if index == 0:
                costs -= CONFIG['meter_prior'][f'{int(n)}/{int(d)}'] * weights
            prefixes.append(np.r_[0., np.cumsum(costs)])
        self.emission_cache[key] = prefixes
        return prefixes

    def totals(self, bpm, phase, numerator, denominator, left, right):
        arrays = np.broadcast_arrays(*[np.atleast_1d(np.asarray(v, float))
            for v in (bpm, phase, numerator, denominator, left, right)])
        result = []
        for b, phi, n, d, a, z in zip(*arrays):
            value = 0.
            for (times, _), prefix in zip(self.audio.channels,
                    self.emission_prefixes(b, phi, n, d)):
                lo, hi = np.searchsorted(times, [max(0., a), min(self.duration, z)])
                value += prefix[hi] - prefix[lo]
            key = (float(b), float(phi), int(n), int(d))
            if key not in self.tick_cache:
                times, weights = self.audio.channels[1]
                period = 60. / b * n * 4. / d
                first = phi + np.ceil((-phi-1e-8)/period)*period
                ticks = np.arange(first, self.duration-1e-8, period)
                if len(times):
                    i = np.searchsorted(times,ticks)
                    before=np.clip(i-1,0,len(times)-1);after=np.clip(i,0,len(times)-1)
                    sigma=CONFIG['neural_sigma_seconds']
                    coverage=np.maximum(weights[before]*np.exp(-.5*((ticks-times[before])/sigma)**2),
                                        weights[after]*np.exp(-.5*((ticks-times[after])/sigma)**2))
                    noise=CONFIG['evidence_clutter_probability']
                    cost=.5*CONFIG['bar_weight']*float(weights.mean())*np.log(noise+(1-noise)*np.clip(coverage,0,1))
                else:cost=np.zeros(len(ticks))
                self.tick_cache[key]=(ticks,np.r_[0.,np.cumsum(cost)])
            ticks, prefix=self.tick_cache[key]
            lo,hi=np.searchsorted(ticks,[max(0.,a)-1e-8,min(self.duration,z)-1e-8])
            value+=prefix[hi]-prefix[lo]
            result.append(value)
        return np.asarray(result)

    def meter_role_score(self, active, left, right):
        # 각 signature에 같은 physical quarter/half-quarter reading을 제공합니다.
        # bar가 짧아질 때만 더 빠른 NN accent 설명을 얻는 counting bias를 막습니다.
        b=active['bpm'];phi=active['phase'];n=active['numerator'];d=active['denominator']
        quarter_phase=active['anchor_time']-active['anchor_quarter']*60./b
        key=(float(b),float(phi),int(n),int(d),float(quarter_phase))
        if not hasattr(self,'meter_role_cache'):self.meter_role_cache={}
        if key not in self.meter_role_cache:
            times,weights=self.audio.channels[1];sigma=CONFIG['neural_sigma_seconds']
            period=60./b*n*4./d
            residual=(times-phi+period/2.)%period-period/2.
            agreement=np.exp(-.5*(residual/sigma)**2)
            for factor,reading_cost in [(1.,1.),(2.,2.)]:
                p=60./b/factor
                residual=(times-quarter_phase+p/2.)%p-p/2.
                role=np.exp(-.5*(residual/sigma)**2-CONFIG['observation_role_cost']*reading_cost)
                agreement=np.maximum(agreement,role)
            noise=CONFIG['evidence_clutter_probability']
            costs=.5*CONFIG['bar_weight']*weights*np.log(noise+(1-noise)*np.clip(agreement,0,1))
            self.meter_role_cache[key]=np.r_[0.,np.cumsum(costs)]
        times=self.audio.channels[1][0]
        lo,hi=np.searchsorted(times,[max(0.,left),min(self.duration,right)])
        point=float(self.meter_role_cache[key][hi]-self.meter_role_cache[key][lo])
        full=float(self.totals(b,phi,n,d,left,right)[0])
        observed=0.
        for (t,_),prefix in zip(self.audio.channels,self.emission_prefixes(b,phi,n,d)):
            a,z=np.searchsorted(t,[max(0.,left),min(self.duration,right)])
            observed+=float(prefix[z]-prefix[a])
        expected=full-observed
        bt=self.audio.channels[0][0];a,z=np.searchsorted(bt,[max(0.,left),min(self.duration,right)])
        mass=float(self.cumulative[0][z]-self.cumulative[0][a])
        prior=CONFIG['meter_prior'][f'{n}/{d}']*mass
        return point+expected-prior
