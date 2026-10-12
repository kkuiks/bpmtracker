"""Source-only common evidence, shared without policy-specific recomputation."""
from __future__ import annotations

import math
import numpy as np
from experiments.variable_tempo_interval_consensus_v0 import core as previous
from .common import CONFIG


def ticks(clock, start, end):
    p = 60. / clock['bpm']
    k = np.arange(math.ceil((start-clock['phase'])/p), math.ceil((end-clock['phase'])/p))
    return clock['phase'] + k*p


def equivalent(a, b, start, end, cfg=CONFIG):
    if abs(a['bpm']-b['bpm'])/max(a['bpm'], b['bpm']) > cfg['equiv_rate']:
        return False
    if a['bpm']==b['bpm']:
        p=60./a['bpm']
        if math.ceil((start-a['phase'])/p)>=math.ceil((end-a['phase'])/p) or math.ceil((start-b['phase'])/p)>=math.ceil((end-b['phase'])/p):
            return False
        return abs((a['phase']-b['phase']+p/2)%p-p/2)<=cfg['equiv_time']+1e-12
    qa, qb = ticks(a, start, end), ticks(b, start, end)
    if not len(qa) or not len(qb):
        return False
    for q, other in ((qa, b), (qb, a)):
        p = 60./other['bpm']
        error = np.abs((q-other['phase']+p/2) % p-p/2)
        if np.max(error) > cfg['equiv_time'] + 1e-12:
            return False
    return True


def harmonic(a, b, cfg=CONFIG):
    ratio = a['bpm']/b['bpm']
    power = math.floor(math.log2(ratio)+.5)
    return power != 0 and abs(ratio/(2.**power)-1) <= cfg['harmonic_tolerance']


class Evidence:
    def __init__(self, data, bank, cfg=None):
        self.cfg = dict(CONFIG if cfg is None else cfg)
        self.obs = previous.observation(data)
        self.silence = previous.silence_intervals(self.obs)
        self.bank = sorted(bank, key=lambda h: h['key'])
        self.duration = self.obs['duration']
        self.time = np.arange(0., self.duration, self.cfg['step'])
        self.start = np.maximum(0., self.time-self.cfg['window'])
        self.S = np.zeros((len(self.time), len(self.bank)))
        self.G = np.zeros_like(self.S)
        self.count = np.zeros_like(self.S, dtype=np.int32)
        self.fresh = np.full_like(self.S, np.inf)
        self.periods = np.array([60./h['bpm'] for h in self.bank])
        ts, ws = self.obs['beat']['times'], self.obs['beat']['weights']
        left, right = np.searchsorted(ts, self.start), np.searchsorted(ts, self.time)
        prefix = np.r_[0., np.cumsum(ws)]
        mass = prefix[right]-prefix[left]
        self.assignments = []
        self._groups_cache = {}
        self._margin_cache = {}
        for j, h in enumerate(self.bank):
            f = previous.clock_features(self.obs, h, dict(previous.DEFAULT, epsilon=self.cfg['epsilon'],
                                                         context_radius=self.cfg['context_radius']))
            if f is not None:
                q = f['q']; a, b = np.searchsorted(q, self.start), np.searchsorted(q, self.time)
                quality = np.r_[0., np.cumsum(f['quality'])]
                self.S[:, j] = np.divide(quality[b]-quality[a], b-a, out=np.zeros(len(a)), where=b>a)
            p = self.periods[j]; pf = p/2
            # Nearest integer with an exact halfway tie assigned to the lower tick.
            ix = np.ceil((ts-h['phase'])/pf-.5).astype(np.int64)
            grid = h['phase']+ix*pf
            residual = ts-grid
            valid = (np.abs(residual)<=min(self.cfg['tau_max'], self.cfg['tau_fraction']*p)) & (grid>=0) & (grid<self.duration)
            source = np.flatnonzero(valid)
            reward = ws[source]*np.exp(-.5*(residual[source]/self.cfg['epsilon'])**2)
            groups = {}
            for si, ri in zip(source.tolist(), reward.tolist()):
                groups.setdefault(int(ix[si]), []).append((si, ri))
            reward_diff = np.zeros(len(self.time)+1)
            count_diff = np.zeros(len(self.time)+1, dtype=np.int32)
            last = np.full(len(self.time), -np.inf)
            for tick, choices in groups.items():
                covered = []
                for si, ri in sorted(choices, key=lambda z: (-z[1], z[0])):
                    lo = int(np.searchsorted(self.time, max(ts[si], grid[si]), side='right'))
                    hi = int(np.searchsorted(self.time, min(ts[si], grid[si])+self.cfg['window'], side='right'))
                    parts = [(lo, hi)]
                    for ca, cb in covered:
                        pieces = []
                        for a, b in parts:
                            if cb<=a or ca>=b:
                                pieces.append((a,b))
                            else:
                                if a<ca: pieces.append((a,ca))
                                if cb<b: pieces.append((cb,b))
                        parts = pieces
                    for a,b in parts:
                        if a>=b: continue
                        reward_diff[a]+=ri; reward_diff[b]-=ri
                        if tick % 2 == 0:
                            count_diff[a]+=1; count_diff[b]-=1
                            last[a:b] = np.maximum(last[a:b], ts[si])
                    covered.append((lo,hi))
            values = np.maximum(0., np.cumsum(reward_diff)[:-1])
            self.G[:,j] = np.clip(np.divide(values,mass,out=np.zeros_like(values),where=mass>0),0.,1.)
            self.count[:,j] = np.cumsum(count_diff)[:-1]
            self.fresh[:,j] = self.time-last
            self.assignments.append((ix, grid, residual, valid))

    def qualified(self, i, seed=False, change=False):
        cfg = self.cfg
        count = cfg['seed_count'] if seed or change else cfg['keep_count']
        threshold = cfg['change_G'] if change else cfg['keep_G']
        mask = (self.G[i]>=threshold-1e-12) & (self.count[i]>=count)
        mask &= self.fresh[i] <= cfg['fresh_periods']*self.periods + 1e-12
        if seed or change:
            mask &= self.S[i]>=cfg['seed_S']-1e-12
        return np.flatnonzero(mask).tolist()

    def groups(self, i, candidates):
        cache_key=(i,tuple(sorted(candidates)))
        if cache_key in self._groups_cache:
            return self._groups_cache[cache_key]
        candidates = sorted(candidates, key=lambda j: (-self.S[i,j], -self.bank[j].get('source_score',0.), self.bank[j]['key']))
        result=[]
        for j in candidates:
            for group in result:
                if equivalent(self.bank[j],self.bank[group[0]],self.start[i],self.time[i],self.cfg):
                    group.append(j)
                    break
            else:
                result.append([j])
        self._groups_cache[cache_key]=result
        return result

    def margin(self, i, j, groups):
        cache_key=(i,j,tuple(g[0] for g in groups))
        if cache_key in self._margin_cache:
            return self._margin_cache[cache_key]
        others = [g[0] for g in groups if not equivalent(self.bank[j],self.bank[g[0]],self.start[i],self.time[i],self.cfg)]
        result=float(self.S[i,j]-max(self.S[i,k] for k in others)) if others else 1.
        self._margin_cache[cache_key]=result
        return result

    def matches(self, i, j):
        ts, ws = self.obs['beat']['times'], self.obs['beat']['weights']
        ix, grid, residual, valid = self.assignments[j]
        use = np.flatnonzero(valid & (ts>=self.start[i]) & (ts<self.time[i]) &
                             (grid>=self.start[i]) & (grid<self.time[i]))
        rewards = ws[use]*np.exp(-.5*(residual[use]/self.cfg['epsilon'])**2)
        order = np.lexsort((use, -rewards, ix[use]))
        selected = use[order]
        if len(selected):
            selected = selected[np.r_[True,np.diff(ix[selected])!=0]]
        return [{'source_index':int(k),'time':float(ts[k]),'tick_index':int(ix[k]),
                 'tick_time':float(grid[k]),'residual':float(residual[k]),'weight':float(ws[k]),
                 'primary':bool(ix[k]%2==0)} for k in selected]

    def detail(self, i, j, matching=False):
        if j is None: return None
        h = self.bank[j]
        r = {'key':h['key'],'bpm':h['bpm'],'phase':h['phase'], 'S':float(self.S[i,j]),
             'G':float(self.G[i,j]),'primary_count':int(self.count[i,j]),
             'freshness':float(self.fresh[i,j]) if np.isfinite(self.fresh[i,j]) else None}
        if matching: r['matches']=self.matches(i,j)
        return r

    def drift(self, i, current, candidate):
        cfg = self.cfg
        ms = sorted([x for x in self.matches(i,candidate) if x['primary']],key=lambda x:x['time'])
        for k in range(len(ms)-1,0,-1):
            if (ms[k]['tick_index']-ms[k-1]['tick_index'])//2 > cfg['drift_max_tick_gap']:
                ms = ms[k:]
                break
        result={'passed':False,'points':ms,'mode':cfg['drift_unwrap']}
        if len(ms)<cfg['seed_count']:
            return dict(result,reason='DRIFT_TOO_FEW_RECENT_MATCHES')
        x=np.array([m['time'] for m in ms]); k=np.array([m['tick_index']//2 for m in ms])
        p=self.periods[current]; pf=p/2; phi=self.bank[current]['phase']; span=float(x[-1]-x[0])
        if span+1e-12<cfg['change_span_periods']*p:
            return dict(result,reason='DRIFT_TOO_SHORT',span=span)
        wrapped=(x-phi+pf/2)%pf-pf/2
        principal=np.unwrap(2*np.pi*wrapped/pf)*pf/(2*np.pi)
        # Retain candidate quarter identity instead of silently choosing a nearby
        # subdivision count when a large rate change aliases the principal unwrap.
        u=wrapped[0]+(x-x[0])-(k-k[0])*p
        xc=x-x.mean(); sxx=float(xc@xc)
        b=float(xc@(u-u.mean())/sxx)
        residual=u-(u.mean()+b*xc)
        se=math.sqrt(float(residual@residual)/((len(x)-2)*sxx))
        principal_b=float(xc@(principal-principal.mean())/sxx)
        outlier=float(np.mean(abs(wrapped)>min(cfg['tau_max'],cfg['tau_fraction']*p)))
        sign_ok=b*(self.bank[candidate]['bpm']-self.bank[current]['bpm'])<0
        passed=(abs(b)>max(cfg['drift_slope_floor'],3*se) and
                abs(b)*span>=max(cfg['drift_absolute'],cfg['drift_period_fraction']*p) and
                outlier>=cfg['drift_outlier_fraction'] and sign_ok)
        return dict(result,passed=bool(passed),reason='DRIFT_PASS' if passed else 'DRIFT_WEAK_OR_CONTRADICTORY',
                    slope=b,slope_se=se,span=span,total_drift=abs(b)*span,outlier_fraction=outlier,
                    direction_ok=bool(sign_ok),principal_unwrap_slope=principal_b,
                    wrapped=wrapped.tolist(),unwrapped=u.tolist())
