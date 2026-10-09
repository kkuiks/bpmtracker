"""Physical-clock support episodes, with no file I/O or source identity."""
from fractions import Fraction
import math
import numpy as np
from scipy.signal import find_peaks
from scipy.special import expit


DEFAULT = dict(epsilon=.02, quality_threshold=.70, minimum_quarters=4, margin=.05,
               context_radius=2, maximum_unknown_bridge=1, maximum_weak_run=3,
               maximum_contradiction_run=1, minimum_score=.5, max_episodes_per_clock=4,
               max_proposals=64, bar_threshold=.55,period_guard=True,period_guard_radius=12)
POOL = np.array(sorted({float(Fraction(n, d)) for d in range(1, 5)
                        for n in range(30*d, 400*d+1)}))


def quantize(value):
    k = int(np.searchsorted(POOL, value))
    return float(min(POOL[max(0,k-1):min(len(POOL),k+1)], key=lambda v: (abs(v-value), v)))


def observation(data):
    allowed = {'beat_logits', 'downbeat_logits', 'fps', 'duration_seconds', 'silent_frame_mask'}
    if set(data) - allowed: raise ValueError('Unsupported source-array fields')
    duration, fps = float(data['duration_seconds']), float(data['fps'])
    if not math.isfinite(duration) or duration < 0 or fps != 50: raise ValueError('Source geometry')
    arrays = [np.asarray(data[k], dtype=float) for k in ('beat_logits', 'downbeat_logits')]
    if any(v.ndim != 1 or not np.isfinite(v).all() for v in arrays) or len(arrays[0]) != len(arrays[1]):
        raise ValueError('Nonfinite or inconsistent sensor arrays')
    if abs(len(arrays[0])/fps-duration) > .08: raise ValueError('Frame/duration mismatch')
    silent = np.asarray(data.get('silent_frame_mask', np.zeros(len(arrays[0]))), dtype=bool)
    if len(silent) != len(arrays[0]): raise ValueError('Silence geometry')
    result = dict(duration=duration, fps=fps, silent=silent)
    for name, array in zip(('beat', 'downbeat'), arrays):
        p = expit(array)
        positions, _ = find_peaks(p, height=.25, distance=3)
        positions = positions[~silent[positions]]
        result[name] = dict(times=positions/fps, weights=p[positions])
    return result


def moving(values, radius):
    index = np.arange(len(values)); prefix = np.r_[0., np.cumsum(values)]
    return prefix[np.minimum(len(values), index+radius+1)]-prefix[np.maximum(0, index-radius)]


def silence_intervals(obs):
    s = obs['silent']; begin = np.flatnonzero(s & ~np.r_[False, s[:-1]])
    end = np.flatnonzero(s & ~np.r_[s[1:], False])+1
    return [[float(a/obs['fps']), min(float(b/obs['fps']), obs['duration'])] for a, b in zip(begin, end)]


def clock_features(obs, h, cfg):
    bpm, phase = float(h['bpm']), float(h['phase'])
    if not 30 <= bpm <= 400 or abs(quantize(bpm)-bpm) > 1e-8:
        raise ValueError('Clock domain')
    period = 60/bpm; phase %= period
    first = math.ceil(-phase/period); last = math.ceil((obs['duration']-phase)/period)
    q = phase + np.arange(first, last)*period; n = len(q)
    if not n: return None
    times, weights = obs['beat']['times'], obs['beat']['weights']
    index = np.rint((times-phase)/period).astype(int)-first
    valid = (index >= 0) & (index < n)
    mass = np.bincount(index[valid], weights=weights[valid], minlength=n)
    event_count = np.bincount(index[valid], minlength=n)
    match = np.zeros(n); matched_time = np.full(n, np.nan)
    residual = times-(phase+(index+first)*period)
    use = valid & (abs(residual) <= min(.08, period*.25))
    options = np.flatnonzero(use)
    reward = weights[options]*np.exp(-.5*(residual[options]/cfg['epsilon'])**2)
    order = np.lexsort((-reward, index[options])); picked = options[order]
    if len(picked):
        picked = picked[np.r_[True, np.diff(index[picked]) != 0]]
        match[index[picked]] = weights[picked]*np.exp(-.5*(residual[picked]/cfg['epsilon'])**2)
        matched_time[index[picked]] = times[picked]
    prefix_silent = np.r_[0, np.cumsum(obs['silent'])]
    a = np.clip(np.floor((q-period/2)*obs['fps']).astype(int), 0, len(obs['silent']))
    b = np.clip(np.ceil((q+period/2)*obs['fps']).astype(int), 0, len(obs['silent']))
    full_silent = (b-a >= period*obs['fps']-1) & (prefix_silent[b]-prefix_silent[a] == b-a)
    radius = cfg['context_radius']
    observed = moving(event_count, radius) >= 2
    information = observed & ~full_silent
    supported = moving(match, radius)
    expected = moving((~full_silent).astype(float), radius)
    event_density=moving(event_count,radius)/np.maximum(expected,1)
    occupancy = np.minimum(1, supported/np.maximum(expected, 1))
    explained = np.minimum(1, supported/np.maximum(moving(mass, radius), 1e-9))
    quality = 2*occupancy*explained/np.maximum(occupancy+explained, 1e-9)
    quality[~information] = 0
    # Matching nearby ticks does not certify the declared rate. Check residual
    # trend over source events; the interval is heuristic, with a quantization floor.
    k=np.arange(n,dtype=float);available=np.isfinite(matched_time)
    residual_time=np.where(available,matched_time-q,0.)
    weight=np.where(available,match,0.)
    radius_period=cfg['period_guard_radius']
    sw=moving(weight,radius_period);sx=moving(weight*k,radius_period);sy=moving(weight*residual_time,radius_period)
    sxx=moving(weight*k*k,radius_period)-sx*sx/np.maximum(sw,1e-9)
    sxy=moving(weight*k*residual_time,radius_period)-sx*sy/np.maximum(sw,1e-9)
    slope=sxy/np.maximum(sxx,1e-9)
    variance=(moving(weight*residual_time**2,radius_period)-sy*sy/np.maximum(sw,1e-9)-sxy*sxy/np.maximum(sxx,1e-9))/np.maximum(sw,1)
    scale=np.maximum(.01,np.sqrt(np.maximum(variance,0.)))
    tolerance=3*scale/np.sqrt(np.maximum(sxx,1e-9))
    period_conflict=(moving(available.astype(float),radius_period)>=8)&(abs(slope)>tolerance)
    score = (quality-cfg['quality_threshold'])*period
    score[~information] = 0
    return dict(h=h, q=q, period=period, quality=quality, score=score, information=information,
                occupancy=occupancy, explanation=explained, matched_time=matched_time,
                event_density=event_density,
                period_conflict=period_conflict,period_slope=slope,period_slope_tolerance=tolerance,
                contradiction=np.zeros(n, dtype=bool))


def relative_clock(h, other, time, epsilon):
    ratio = h['bpm']/other['bpm']
    if min(abs(ratio-.5), abs(ratio-2)) <= .001: return True
    if abs(h['bpm']-other['bpm']) < 1e-8:
        p = 60/h['bpm']; gap = abs((h['phase']-other['phase']+p/2) % p-p/2)
        return gap <= 2*epsilon
    return False


def alternatives(features, obs, cfg):
    centers = np.arange(.125, obs['duration'], .25)
    if not len(centers) or not features: return
    matrix = np.stack([np.interp(centers, f['q'], f['quality'], left=0, right=0) for f in features])
    leaders = np.argsort(matrix, axis=0)[-min(4, len(features)):]
    rates = np.array([f['h']['bpm'] for f in features])
    phases = np.array([f['h']['phase'] for f in features])
    for f in features:
        nearest = np.clip(np.searchsorted(centers, f['q']), 0, len(centers)-1)
        best = np.zeros(len(f['q']))
        for row in leaders:
            indices = row[nearest]; quality = matrix[indices, nearest]
            ratio = f['h']['bpm']/rates[indices]
            family = (abs(ratio-.5) <= .001) | (abs(ratio-2) <= .001)
            gap = abs((f['h']['phase']-phases[indices]+f['period']/2) % f['period']-f['period']/2)
            equivalent = (abs(f['h']['bpm']-rates[indices]) < 1e-8) & (gap <= 2*cfg['epsilon'])
            allowed = ~(family | equivalent)
            best = np.maximum(best, quality*allowed)
        f['contradiction'] = (f['information'] & (f['quality'] < cfg['quality_threshold']-.1)
                              & (best >= cfg['quality_threshold']+.1) & (best-f['quality'] >= .2))


def runs(mask):
    starts = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    ends = np.flatnonzero(mask & ~np.r_[mask[1:], False])+1
    return list(zip(starts.tolist(), ends.tolist()))


def bar_fit(obs, h, start, end, cfg):
    p = 60/h['bpm']; results = []
    for phase in h.get('bars', [h['phase']+j*p for j in range(4)]):
        period = 4*p; phase %= period
        q = phase+np.arange(math.ceil((start-phase)/period), math.ceil((end-phase)/period))*period
        use = (obs['downbeat']['times'] >= start) & (obs['downbeat']['times'] < end)
        t, w = obs['downbeat']['times'][use], obs['downbeat']['weights'][use]
        if not len(q) or not len(t): results.append((0., phase,0)); continue
        k = np.rint((t-phase)/period).astype(int)
        residual = t-(phase+k*period)
        keep = (phase+k*period >= start) & (phase+k*period < end) & (abs(residual) <= .08)
        indices = k[keep]; rewards = w[keep]*np.exp(-.5*(residual[keep]/cfg['epsilon'])**2)
        total = sum(float(np.max(rewards[indices == i])) for i in np.unique(indices))
        occupancy, explain = total/len(q), total/max(w.sum(), 1e-9)
        quality = 2*occupancy*explain/max(occupancy+explain, 1e-9)
        results.append((float(quality), float(phase),len(np.unique(indices))))
    results.sort(reverse=True)
    best = results[0]; second = results[1][0] if len(results)>1 else 0.
    status = 'SUPPORTED' if best[0] >= cfg['bar_threshold'] and best[0]-second >= .1 and best[2]>=2 else 'UNKNOWN'
    return dict(bar_phase=best[1], bar_quality=best[0], bar_status=status, bar_margin=best[0]-second,bar_matched_events=best[2])


def episode(f, a, b, obs, cfg):
    information = f['information'][a:b]; count = int(information.sum())
    if count < cfg['minimum_quarters']: return None
    integral = float(f['score'][a:b].sum())
    if integral < cfg['minimum_score']: return None
    quality = float(np.mean(f['quality'][a:b][information]))
    start = max(0., float(f['q'][a]-f['period']/2))
    end = min(obs['duration'], float(f['q'][b-1]+f['period']/2))
    h = f['h']; bar = bar_fit(obs, h, start, end, cfg)
    rank = .8*quality + (.2*bar['bar_quality'] if bar['bar_status']=='SUPPORTED' else 0.) + min(.1, .02*math.log1p(count))
    return dict(bpm=h['bpm'], phase=h['phase'] % f['period'], period=f['period'], start=start, end=end,
                quality=quality, integral_score=integral, informative_quarters=count, rank=rank,
                occupancy=float(np.mean(f['occupancy'][a:b])), explanation=float(np.mean(f['explanation'][a:b])),
                provenance=h.get('provenance', 'source'), hypothesis_id=h.get('key', ''), **bar)


def extract(f, obs, cfg, global_mode=False):
    n = len(f['q'])
    if global_mode:
        e = episode(f, 0, n, obs, cfg)
        if e and e['quality'] >= cfg['quality_threshold']:
            e['start'], e['end'] = 0., obs['duration']; return [e]
        return []
    blocked = np.zeros(n, dtype=bool)
    masks = [(~f['information'], cfg['maximum_unknown_bridge']),
             (f['contradiction'], cfg['maximum_contradiction_run']),
             (f['information'] & (f['quality'] < cfg['quality_threshold']), cfg['maximum_weak_run'])]
    for mask, limit in masks:
        for a, b in runs(mask):
            if b-a > limit: blocked[a:b] = True
    output = []
    for a, b in runs(~blocked):
        prefix = np.r_[0., np.cumsum(f['score'][a:b])]
        minimum, at, winner = 0., 0, (0., 0, 0)
        for j in range(1, len(prefix)):
            if prefix[j]-minimum > winner[0]: winner = (prefix[j]-minimum, at, j)
            if prefix[j] < minimum: minimum, at = prefix[j], j
        e = episode(f, a+winner[1], a+winner[2], obs, cfg) if winner[2]>winner[1] else None
        if e: output.append(e)
    output.sort(key=lambda r: r['integral_score'], reverse=True)
    return output[:cfg['max_episodes_per_clock']]


def refit(e, obs, cfg, rate=False):
    t, w = obs['beat']['times'], obs['beat']['weights']; p, phase = e['period'], e['phase']
    k = np.rint((t-phase)/p)
    keep = (t >= e['start']) & (t < e['end']) & (abs(t-(phase+k*p)) <= min(.08, p*.25))
    if keep.sum() < cfg['minimum_quarters']: return None
    t, w, k = t[keep], w[keep], k[keep]
    if rate:
        mean = np.average(k, weights=w); spread = np.sum(w*(k-mean)**2)
        if spread <= 0: return None
        fitted = np.sum(w*(k-mean)*(t-np.average(t, weights=w)))/spread
        if fitted <= 0: return None
        bpm = quantize(60/fitted)
        if abs(bpm-e['bpm']) > .5: return None
        p = 60/bpm
    else: bpm = e['bpm']
    origin = float(np.average(t-k*p, weights=w)); phase = origin % p
    j = round((e['bar_phase']-e['phase'])/e['period']) % 4
    h = dict(bpm=bpm, phase=phase, bars=[(origin+j*p)%(4*p)], provenance='local_rate_phase_refit' if rate else 'local_phase_refit')
    f = clock_features(obs, h, cfg)
    if f is None: return None
    if cfg['period_guard']:
        f['quality']=np.where(f['period_conflict'],0.,f['quality'])
        f['score']=np.where(f['information'],(f['quality']-cfg['quality_threshold'])*f['period'],0.)
    choices = extract(f, obs, cfg)
    choices = [r for r in choices if min(r['end'], e['end'])-max(r['start'], e['start']) > 0]
    if not choices: return None
    result = max(choices, key=lambda r: r['integral_score'])
    result['start'], result['end'] = max(result['start'], e['start']), min(result['end'], e['end'])
    result['refit_from'] = dict(bpm=e['bpm'], phase=e['phase'])
    return result


def decision(proposals, obs, cfg, initial=None, policy='none', initial_anchors=None):
    if not proposals: return [], [], None
    silence = silence_intervals(obs)
    initial_scope = None
    initial_layer = None
    if initial is not None and policy != 'none' and len(obs['beat']['times']):
        if set(initial) != {'initial_bpm', 'bpm_unit_quarters', 'scope', 'origin'} or initial['scope'] != 'initial_audio_section':
            raise ValueError('Invalid explicit initial-information channel')
        value = float(initial['initial_bpm'])*float(initial['bpm_unit_quarters'])
        if not math.isfinite(value) or value <= 0: raise ValueError('Initial BPM')
        # Scope comes from source pulses, not the supplied number or a reference boundary.
        gaps = np.diff(obs['beat']['times'][:17])
        native_period = float(np.median(gaps)) if len(gaps) else .5
        native_rate = 60/native_period
        initial_layer = math.floor(math.log2(value/native_rate)+.5)
        start = float(obs['beat']['times'][0]); initial_scope = [start, min(obs['duration'], start+min(8., 8*native_period))]
        anchors = list(initial_anchors or [])
        if policy=='initial_exact': anchors=[r for r in anchors if 30<=value<=400 and abs(r['bpm']-quantize(value))<1e-8]
        elif policy=='initial_unit': anchors=[r for r in anchors if math.floor(math.log2(r['bpm']/native_rate)+.5)==initial_layer]
        if anchors:
            # Same source-only anchor operator for matched-global and interval conditions.
            anchor=max(anchors,key=lambda r:(r['rank'],-r['start']))
            initial_scope[1]=max(initial_scope[1],anchor['end'])
    ends = {r['start'] for r in proposals} | {r['end'] for r in proposals}
    for a, b in silence: ends.update((a, b))
    if initial_scope: ends.update(initial_scope)
    ends = sorted(ends); accepted, ambiguous = [], []
    for a, b in zip(ends, ends[1:]):
        middle = (a+b)/2
        if any(x <= middle < y for x, y in silence): continue
        options = [r for r in proposals if r['start'] <= middle < r['end']]
        if initial_scope and initial_scope[0] <= middle < initial_scope[1]:
            if policy == 'initial_exact': options = [r for r in options if 30<=value<=400 and abs(r['bpm']-quantize(value)) < 1e-8]
            elif policy == 'initial_unit': options = [r for r in options if math.floor(math.log2(r['bpm']/native_rate)+.5) == initial_layer]
            else: raise ValueError('Unknown initial policy')
        if not options: continue
        options.sort(key=lambda r: (r['rank'], r['integral_score']), reverse=True); winner = options[0]
        rivals = [r for r in options[1:] if not (abs(r['bpm']-winner['bpm']) < 1e-8 and
                   abs((r['phase']-winner['phase']+winner['period']/2) % winner['period']-winner['period']/2) <= 2*cfg['epsilon'])]
        gap = winner['rank']-rivals[0]['rank'] if rivals else 1.
        record = dict(winner, start=a, end=b, decision_margin=gap)
        if gap < cfg['margin']:
            ambiguous.append(dict(start=a, end=b, status='AMBIGUOUS', alternatives=[{k:r[k] for k in ('bpm','phase','rank')} for r in options[:5]]))
        else: accepted.append(record)
    merged = []
    for r in accepted:
        if merged and abs(merged[-1]['end']-r['start']) < 1e-9 and all(merged[-1][k] == r[k] for k in ('bpm','phase','bar_phase','bar_status')):
            merged[-1]['end'] = r['end']
        else: merged.append(r)
    return merged, ambiguous, initial_scope


def clip_initial_anchor(anchor,f,obs):
    """A harmonic clock can survive a genuine octave change: end the initial
    declaration at a persistent change in observed pulse density, too."""
    use=np.flatnonzero((f['q']>=anchor['start'])&(f['q']<anchor['end'])&f['information'])
    if len(use)<8:return dict(anchor)
    baseline=float(np.median(f['event_density'][use[:8]]))
    if baseline<=0:return dict(anchor)
    altered=np.abs(np.log(np.maximum(f['event_density'],1e-9)/baseline))>math.log(1.5)
    altered&=f['information']
    for a,b in runs(altered):
        if b-a>=3 and f['q'][a]>f['q'][use[7]] and f['q'][a]<anchor['end']:
            return dict(anchor,end=max(anchor['start'],float(f['q'][a]-f['period']/2)),
                        source_density_regime_truncation=True)
    return dict(anchor)


def support_prediction(obs, stored_features, cfg, global_mode=False, refinement=None, initial=None, policy='none'):
    features=[]
    for f in stored_features:
        quality=np.where(f['period_conflict'],0.,f['quality']) if cfg['period_guard'] else f['quality']
        features.append(dict(f,quality=quality,score=np.where(f['information'],(quality-cfg['quality_threshold'])*f['period'],0.),
                             contradiction=np.zeros(len(f['q']),dtype=bool)))
    alternatives(features, obs, cfg)
    # An initial BPM declaration labels the first source-supported physical clock.
    # Its applicability ends where that source support ends, never at a supplied true boundary.
    initial_anchors=[]
    if len(obs['beat']['times']):
        first_event=float(obs['beat']['times'][0])
        for f in features:
            candidates=extract(f,obs,cfg,False)
            for e in candidates:
                if e['start']<=first_event+min(2*f['period'],2.) and e['end']>first_event+2*f['period']:
                    initial_anchors.append(clip_initial_anchor({k:e[k] for k in ('bpm','phase','start','end','rank')},f,obs))
    proposals = [e for f in features for e in extract(f, obs, cfg, global_mode)]
    before_cap = len(proposals)
    proposals.sort(key=lambda e: (e['integral_score'],e['rank']), reverse=True)
    proposals = proposals[:cfg['max_proposals']]
    refit_trials = len(proposals) if refinement else 0
    if refinement: proposals = [r for e in proposals if (r := refit(e, obs, cfg, refinement == 'rate_phase')) is not None]
    accepted, ambiguous, scope = decision(proposals, obs, cfg, initial, policy,initial_anchors)
    return dict(status='partial_clock_support' if accepted else 'UNKNOWN_or_AMBIGUOUS',
                episodes=proposals, accepted=accepted, ambiguous=ambiguous,
                initial_information_policy=policy, initial_information_scope=scope,
                initial_information_is_assumed_not_measured=initial is not None,
                initial_anchor_episodes=initial_anchors,
                reference_fields_read=False, full_tempo_map_returned=False, meter_inference=False,
                hypotheses_tested=len(features), proposals_before_cap=before_cap,
                refitted_hypotheses_tested=refit_trials,
                proposals_censored=max(0,before_cap-cfg['max_proposals']),
                silence_intervals=silence_intervals(obs), configuration=cfg,
                global_mode=global_mode, refinement=refinement)


def predict(data, hypotheses, configuration=None, global_mode=False, refinement=None, initial=None, policy='none'):
    cfg = {**DEFAULT, **(configuration or {})}; obs = observation(data)
    features = [f for h in hypotheses if (f := clock_features(obs, h, cfg)) is not None]
    return support_prediction(obs,features,cfg,global_mode,refinement,initial,policy)
