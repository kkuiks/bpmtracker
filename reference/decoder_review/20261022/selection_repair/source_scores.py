"""Source-only whole-map criteria; no reference/evaluator dependencies.

The preserved G21 expected-bar penalty is included explicitly. Some historical
G21 docstrings/decoder metadata incorrectly say it is absent.
"""
from pathlib import Path
import sys
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
G21 = ROOT / 'data/research/runs/l2_improvement_autoresearch_v1/20261014-01a138e6-v1/phases/phase-B-c250ba38c4af/trials/G21/full'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(G21))
from candidate_emissions import Score as Pointwise
from candidate_common import CONFIG
from experiments.beat_event_stability_v1.scoring import Score as Legacy
from experiments.beat_event_map_v1.core import state, child_state

VARIANTS = {
    'legacy_pool': 'Original interval criterion, on the identical finite pool',
    'pointwise_pool': 'Original G21 pointwise criterion, including expected bars',
    'role_pool': 'G21 pointwise with quarter/half-quarter accent roles for every meter',
    'pointwise_mdl_pool': 'Pointwise plus log(number of legal boundary positions) per event',
    'role_mdl_pool': 'Role pointwise plus the same source-derived boundary code length',
    'legacy_mdl_pool': 'Legacy plus the same source-derived boundary code length',
}


def geometry(value):
    return {'initial': {k: value['initial'][k] for k in ('bpm','numerator','denominator','bar_zero_source_seconds')},
            'events': [{k: e[k] for k in ('time','quarter','bpm','numerator','denominator') if k in e} for e in value['events']]}


def geometry_key(value):
    import json
    return json.dumps(geometry(value), sort_keys=True)


class MapScorer:
    def __init__(self, events, prepared, family=None):
        self.events = events
        self.duration = float(events['duration'])
        self.legacy = Legacy(events)
        self.pointwise = Pointwise(events)
        self.initials = [c for u in prepared['units'] for c in u['initials']]
        self.rebuilt = False
        self.cache = {}
        self.family_initials = []
        for level in (family or {}).get('levels', []):
            best = level['best'];bpm = best['quarter_bpm'];sig = best['time_signature']
            period = 60./bpm*sig['numerator']*4./sig['denominator']
            phase = best['offset_seconds'] % period
            if phase > 1e-8:phase -= period
            self.family_initials.append({'bpm':bpm,'numerator':sig['numerator'],'denominator':sig['denominator'],
                'bar_zero_source_seconds':phase,'family_prior':CONFIG['family_initial_prior'],
                'initial_source_origin':'existing_audio_family_fixed_candidate'})

    def meta(self, initial):
        def matching():
            return [c for c in self.initials if all(abs(c[k]-initial[k]) <= 1e-9 for k in initial)]
        matches = matching()
        if not matches and not self.rebuilt:
            import candidate_initial_source as source
            old = source.CONFIG['initial_information_mass']
            source.CONFIG['initial_information_mass'] = old * 4.
            try:
                rebuilt = source.prepare(self.events, None)
            finally:
                source.CONFIG['initial_information_mass'] = old
            self.initials += [c for u in rebuilt.get('units', []) for c in u['initials']]
            self.rebuilt = True
            matches = matching()
        if not matches:
            # The original prepared bank merges phases in 4ms cells. The
            # independently preserved fixed-family output can therefore have
            # a slightly different exact phase. Admit only that source-derived
            # family geometry, with the existing family prior; never snap it.
            matches = [c for c in self.family_initials if all(abs(c[k]-initial[k])<=1e-9 for k in initial)]
        if not matches:
            raise ValueError(('Map initial was not source-qualified',initial))
        return max(matches, key=lambda c: c['family_prior'])

    def segment(self, active, left, right):
        b,phi,n,d = (active[k] for k in ('bpm','phase','numerator','denominator'))
        key = (b,phi,n,d,left,right,active['anchor_time'],active['anchor_quarter'])
        if key in self.cache:
            return self.cache[key]
        s = self.legacy
        _, beat, bar, pcm = s.batch(b,phi,n,d,left,right,True)
        legacy = {}
        noise = CONFIG['evidence_clutter_probability']
        for i,(label,weight,value) in enumerate(zip(('beat','bar','PCM'),('beat_weight','bar_weight','pcm_weight'),(beat,bar,pcm))):
            times,_ = s.audio.channels[i]
            lo,hi = np.searchsorted(times,[left,right])
            mass = float(s.cumulative[i][hi]-s.cumulative[i][lo])
            legacy[label] = CONFIG[weight] * mass * float(np.log(noise+(1-noise)*np.clip(value[0],0,1)))
        lo,hi = np.searchsorted(s.t,[left,right])
        prior = -CONFIG['meter_prior'][f'{n}/{d}'] * float(s.cumulative[0][hi]-s.cumulative[0][lo])
        legacy['meter_prior'] = prior
        p = self.pointwise
        prefixes = p.emission_prefixes(b,phi,n,d)
        point = {}
        for i,label in enumerate(('beat','bar','PCM')):
            times,_ = p.audio.channels[i]
            lo,hi = np.searchsorted(times,[max(0.,left),min(self.duration,right)])
            point[label] = float(prefixes[i][hi]-prefixes[i][lo])
        point['beat'] -= prior
        point['meter_prior'] = prior
        total = float(p.totals(b,phi,n,d,left,right)[0])
        point['expected_bar'] = total - sum(point.values())
        # meter_role_score already includes the original expected-bar cost and
        # the meter prior; replace only the observed-bar contribution.
        role_bar = float(p.meter_role_score(active,left,right)) - point['expected_bar'] - prior
        result = {'legacy': legacy, 'pointwise': point, 'role_bar': role_bar,
                  'legacy_exact': float(s.totals(b,phi,n,d,left,right)[0]),
                  'pointwise_exact': total}
        self.cache[key] = result
        return result

    def score(self, value, initial_family_prior=None):
        initial = value['initial']
        meta = self.meta(initial) if initial_family_prior is None else {'family_prior':initial_family_prior,'initial_source_origin':'explicit_common_initial_prior'}
        prior = meta['family_prior'] * float(self.legacy.w.sum())
        parts = {scheme: {'initial_family_prior': prior, 'transition':0., 'boundary_code':0.} for scheme in ('legacy','pointwise','role')}
        active = state(initial)
        segments = []
        boundaries = 0.
        for event in value['events'] + [{'time': self.duration}]:
            left,right = active['start'],event['time']
            row = self.segment(active,left,right)
            role = {**row['pointwise'], 'bar': row['role_bar']}
            for scheme,channels in [('legacy',row['legacy']),('pointwise',row['pointwise']),('role',role)]:
                for label,cost in channels.items():
                    parts[scheme][label] = parts[scheme].get(label,0.) + cost
            segments.append({'left':left,'right':right,'state':dict(active),**row})
            if 'quarter' not in event:
                break
            b,n,d = (active[k] for k in ('bpm','numerator','denominator'))
            new = child_state(active,event['time'],event['quarter'],event.get('bpm',b),event.get('numerator',n),event.get('denominator',d))
            rate = new['bpm'] != b
            meter = (new['numerator'],new['denominator']) != (n,d)
            cost = CONFIG['tempo_change_cost']*rate + CONFIG['meter_change_cost']*meter
            if rate and min(abs(new['bpm']/b/2-1),abs(new['bpm']/b/.5-1)) <= CONFIG['octave_ratio_tolerance']:
                cost += CONFIG['octave_change_extra_cost']
            # An event location was selected among old notated beats. This is
            # a controlled model-selection penalty, not a calibrated posterior.
            legal_positions = max(1., (self.duration-active['start'])*b/60.*d/4.)
            boundaries += math.log(legal_positions)
            for part in parts.values():
                part['transition'] -= cost
            active = new
        totals = {s: sum(p.values()) for s,p in parts.items()}
        legacy_check = sum(x['legacy_exact'] for x in segments) + prior + parts['legacy']['transition']
        point_check = sum(x['pointwise_exact'] for x in segments) + prior + parts['pointwise']['transition']
        residual = {'legacy': totals['legacy']-legacy_check, 'pointwise':totals['pointwise']-point_check}
        if max(map(abs,residual.values())) > 1e-7:
            raise ValueError('Source component decomposition failed')
        return {'components':parts, 'segments':segments, 'decomposition_residual':residual,
                'initial_prior_origin':meta.get('initial_source_origin'),
                'boundary_code':boundaries, 'scores':{
                    'legacy_pool':totals['legacy'], 'pointwise_pool':totals['pointwise'], 'role_pool':totals['role'],
                    'legacy_mdl_pool':totals['legacy']-boundaries,
                    'pointwise_mdl_pool':totals['pointwise']-boundaries,
                    'role_mdl_pool':totals['role']-boundaries}}
