"""Retained Original clocks and separately declared source-only phase generators."""
from collections import defaultdict
import gzip
import math
from pathlib import Path
import numpy as np
from experiments.metronome_reconstruction_v1.infer import make_evidence, broad_candidates, phase_seeds
from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
from experiments.metronome_benchmark_v1.trace import CandidateTrace
from .core import observation, quantize
from .io import read, write


def original_h(row, provenance):
    p = float(row['period_seconds']); phase = float(row['offset_seconds']) % p
    return dict(bpm=float(row['quarter_bpm']), phase=phase, bars=[float(row['offset_seconds']) % (4*p)],
                source_score=float(row['score']), provenance=provenance)


def pool(rows, budget=512):
    unique = {}
    for h in rows:
        if not 30 <= h['bpm'] <= 400 or abs(quantize(h['bpm'])-h['bpm']) > 1e-8: continue
        p = 60/h['bpm']; key = (h['bpm'], round((h['phase'] % p)/.001))
        if key not in unique: unique[key] = dict(h, bars=list(h['bars']))
        else:
            old = unique[key]; old['bars'] = sorted(set(old['bars']+h['bars']))
            if h['source_score'] > old['source_score']:
                old.update({k:v for k,v in h.items() if k != 'bars'})
    by_rate = defaultdict(list)
    for h in unique.values(): by_rate[h['bpm']].append(h)
    for values in by_rate.values(): values.sort(key=lambda h: h['source_score'], reverse=True)
    ordered = sorted(by_rate, key=lambda r: by_rate[r][0]['source_score'], reverse=True)
    selected = []
    for depth in range(max((len(v) for v in by_rate.values()), default=0)):
        for rate in ordered:
            if depth < len(by_rate[rate]): selected.append(by_rate[rate][depth])
    for h in selected:
        p=60/h['bpm']; h['bars']=sorted({(h['phase']+(round((b-h['phase'])/p)%4)*p)%(4*p) for b in h['bars']})
        h['key'] = f"{h['bpm']:.12g}:{h['phase'].hex()}"
    return selected[:budget], dict(raw_unique_quarter_clocks=len(unique), unique_rates=len(by_rate),
                                  budget=budget, censored=max(0,len(unique)-budget))


def local_phases(obs, rates, evidence, original_config):
    t, w = obs['beat']['times'], obs['beat']['weights']; result = []
    if len(t) < 4: return result
    centers = np.linspace(t[0], t[-1], min(48,max(8,round(obs['duration']/4))))
    mass_prefix = np.r_[0.,np.cumsum(w)]
    for bpm in rates:
        bpm = float(bpm); p = 60/bpm
        z = np.r_[0.,np.cumsum(w*np.exp(2j*np.pi*t/p))]
        left, right = np.searchsorted(t, centers-4*p), np.searchsorted(t, centers+4*p)
        mass = mass_prefix[right]-mass_prefix[left]; vector = z[right]-z[left]
        coherence = abs(vector)/np.maximum(mass,1e-9)
        exposure = np.minimum(1,mass/8)
        quality = coherence*np.sqrt(exposure)
        choices = []
        for i in np.argsort(quality)[::-1]:
            if right[i]-left[i] < 4 or coherence[i] < .45: continue
            phase = float((np.angle(vector[i])*p/(2*np.pi)) % p)
            if any(abs((phase-old+p/2) % p-p/2) < .015 for old in choices): continue
            choices.append(phase)
            result.append(dict(bpm=bpm,phase=phase,bars=[phase+j*p for j in range(4)],
                               source_score=float(quality[i]),provenance='broad_rate_local_phase'))
            if len(choices) >= 4: break
        for phase in phase_seeds(evidence,p,original_config):
            result.append(dict(bpm=bpm,phase=phase,bars=[phase+j*p for j in range(4)],
                               source_score=.1,provenance='broad_rate_original_global_phase'))
    return result


def prepare(row, data, output, original_config):
    family_path = row.get('original_family_path')
    evidence = make_evidence(data['beat_logits'],data['downbeat_logits'],float(data['duration_seconds']),original_config)
    trace_path, event_path = row.get('original_trace_path'), row.get('original_events_path')
    reused = bool(family_path and Path(family_path).exists())
    if reused:
        family = read(family_path)
        if family.get('status') == 'audio_family_prepared' and not family.get('all_candidates_and_scores_prepared_before_hint'):
            raise ValueError('Family source provenance')
    else:
        with CandidateTrace(output/'new-original-traces',row['id']) as tracing:
            family = prepare_audio_family(evidence,original_config)
            tracing.finish(family,select_from_family(family))
        write(output/'new-original-families'/f"{row['id']}.json",family)
        trace_path = str(output/'new-original-traces'/f"{row['id']}.scores.jsonl.gz")
        event_path = str(output/'new-original-traces'/f"{row['id']}.events.jsonl.gz")
    original = select_from_family(family)
    final, retained, rates, scored = [], [], [], 0
    trace_available = bool(trace_path and Path(trace_path).exists())
    if trace_available:
        with gzip.open(trace_path,'rt') as stream:
            for line in stream:
                record = __import__('json').loads(line); candidate = record['candidate']; scored += 1
                if candidate['time_signature']['numerator'] != 4: continue
                h = original_h(candidate,'original_scored_'+str(record['block']))
                retained.append(h)
                if record['block'] != 'base_search': final.append(h)
    else:
        for level in family.get('levels',[]):
            for candidate in level['top_candidates']:
                if candidate['time_signature']['numerator'] == 4: final.append(original_h(candidate,'original_stored_top'))
        retained = list(final)
        base = family.get('audio_only_original_proposal',{})
        for candidate in base.get('top_candidates',[]):
            if candidate['time_signature']['numerator'] == 4: retained.append(original_h(candidate,'original_base_stored_top'))
    if event_path and Path(event_path).exists():
        with gzip.open(event_path,'rt') as stream:
            for line in stream:
                event = __import__('json').loads(line)
                if event['event'] == 'broad_bpm_candidates':
                    rates.extend(f['numerator']/f['denominator'] for f in event['bpm_fractions'])
    if not rates: rates = [float(x) for x in broad_candidates(evidence,original_config)[0]] if len(evidence['channels']['beat']['events']) >= 4 else []
    obs = observation(data)
    broad = local_phases(obs,sorted(set(rates)),evidence,original_config)
    phasor = []
    if row.get('phasor_cache_path') and Path(row['phasor_cache_path']).exists():
        alternatives = read(row['phasor_cache_path']).get('source_clock_alternatives',[])
        for center in alternatives:
            for h in center['clocks']:
                p = 60/h['bpm']; phase = h['phase'] % p
                phasor.append(dict(bpm=h['bpm'],phase=phase,bars=[phase+j*p for j in range(4)],
                                   source_score=h['quality'],provenance='frozen_source_phasor_alternative'))
    else:
        from experiments.variable_clock_exploration_v1.phasor import witnesses
        from experiments.variable_clock_exploration_v1.clock import event_axis, noise_scale
        t,w = obs['beat']['times'],obs['beat']['weights']
        if len(t) >= 4:
            _, alternatives = witnesses(t,w,obs['duration'],noise_scale(event_axis(t),t))
            for center in alternatives:
                for h in center['clocks']:
                    p=60/h['bpm']; phase=h['phase'] % p
                    phasor.append(dict(bpm=h['bpm'],phase=phase,bars=[phase+j*p for j in range(4)],
                                       source_score=h['quality'],provenance='new_source_phasor_alternative'))
    banks, stats = {}, {}
    for name, values in [('final',final),('retained',retained),('broad_phase',broad),('phasor',phasor)]:
        banks[name],stats[name] = pool(values)
    return dict(pools=banks,statistics=stats,original=original,source_only=True,reference_fields_read=False,
                original_family_reused=reused,original_trace_available=trace_available,original_score_trials=scored,
                broad_rates_count=len(set(rates)),phasor_existing_cache_used=bool(row.get('phasor_cache_path')))
