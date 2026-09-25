"""Bounded continuous-objective clock fitting, including short tempo segments.

Input pulse indices must already have a consistent musical interpretation. This
does not infer missing beat counts, meter, or a source-to-project time offset.
"""
from dataclasses import asdict, dataclass, replace
from numbers import Integral, Real
from itertools import combinations
import numpy as np

from fit_clock import design_matrix, clock_time
from run_beat_this import validate_events


@dataclass(frozen=True)
class FitConfig:
    max_events: int = 2500
    max_knots: int = 16
    candidate_limit: int = 1024
    noise_floor_seconds: float = .00025
    observation_quantization_seconds: float = 0.
    complexity_factor: float = 4.
    refinement_passes: int = 2
    pair_pool_size: int = 12


def _validated_config(config):
    """Reject invalid numerical controls before they reach the bounded search."""
    if not isinstance(config, FitConfig):
        raise ValueError('config must be a FitConfig')
    lower_bounds = {'max_events': 4, 'max_knots': 0, 'candidate_limit': 1,
                    'refinement_passes': 0, 'pair_pool_size': 0}
    counts = {}
    for name, minimum in lower_bounds.items():
        value = getattr(config, name)
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
        counts[name] = int(value)
    for name in ('noise_floor_seconds', 'observation_quantization_seconds', 'complexity_factor'):
        value = getattr(config, name)
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or
                not np.isfinite(value) or value < 0 or (name == 'noise_floor_seconds' and value == 0)):
            raise ValueError(f'invalid finite nonnegative configuration value: {name}')
    # NumPy integer controls are valid, but saved configuration must remain
    # JSON serializable and range() must receive integer objects.
    return replace(config, **counts)


def _solve(x, y, knots, anchors):
    a = design_matrix(x, knots)
    if anchors:
        c = design_matrix(np.array([v['quarter_position'] for v in anchors]), knots)
        d = np.array([v['source_seconds'] for v in anchors])
        base = np.linalg.lstsq(c, d, rcond=None)[0]
        if np.max(abs(c @ base - d)) > 1e-8:
            raise ValueError('locked anchors cannot be satisfied by this clock')
        _, singular, vt = np.linalg.svd(c, full_matrices=True)
        rank = int(np.sum(singular > max(c.shape) * np.finfo(float).eps * singular[0])) if len(singular) else 0
        null = vt[rank:].T
        coefficients = base + null @ np.linalg.lstsq(a @ null, y - a @ base, rcond=None)[0]
    else:
        coefficients = np.linalg.lstsq(a, y, rcond=None)[0]
    residual = y - a @ coefficients
    return coefficients, residual, float(residual @ residual)


def _noise_and_curvature(x, y, floor):
    fraction = (x[1:-1] - x[:-2]) / (x[2:] - x[:-2])
    error = y[1:-1] - ((1 - fraction) * y[:-2] + fraction * y[2:])
    normalized = error / np.sqrt(1 + fraction ** 2 + (1 - fraction) ** 2)
    sigma = max(floor, float(np.median(abs(normalized - np.median(normalized))) / .6744897501960817))
    return sigma, abs(normalized)


def fit_clock_v2(times, pulse_indices=None, anchors=None, locked_knots=None, config=None):
    config = _validated_config(FitConfig() if config is None else config)
    times = validate_events(times)
    if not 4 <= len(times) <= config.max_events:
        raise ValueError('v2 requires 4 to max_events correctly indexed observations')
    x = np.arange(len(times), dtype=float) if pulse_indices is None else np.asarray(pulse_indices, dtype=float)
    if x.shape != times.shape or not np.isfinite(x).all() or np.any(np.diff(x) <= 0):
        raise ValueError('pulse indices must be finite and strictly increasing')
    anchors = [dict(v) for v in anchors or [] if v.get('locked', True)]
    anchors.sort(key=lambda v: v['quarter_position'])
    for i, anchor in enumerate(anchors):
        if (not np.isfinite([anchor['quarter_position'], anchor['source_seconds']]).all() or
                anchor['source_seconds'] < 0 or not x[0] <= anchor['quarter_position'] <= x[-1] or
                (i and (anchor['quarter_position'] <= anchors[i-1]['quarter_position'] or
                        anchor['source_seconds'] <= anchors[i-1]['source_seconds']))):
            raise ValueError('anchors require distinct ordered supported indices and increasing source times')
    fixed = sorted(set(float(k) for k in (locked_knots or [])) |
                   {float(a['quarter_position']) for a in anchors if x[0] < a['quarter_position'] < x[-1]})
    if any(not np.isfinite(k) or not x[0] < k < x[-1] for k in fixed) or len(fixed) > config.max_knots:
        raise ValueError('locked knots exceed supported span or complexity budget')
    # Center y for numerical stability only; restore the same absolute source
    # origin in the exported intercept and every anchor check.
    origin = float(times[0]); y = times - origin
    centered_anchors = [{**a, 'source_seconds': a['source_seconds'] - origin} for a in anchors]
    # A quantized event stream can have zero median second difference even
    # while a minority of events jump one full frame. Its resolution comes
    # from the input contract, not an unreliable inferred decimal precision.
    floor = max(config.noise_floor_seconds, config.observation_quantization_seconds / np.sqrt(12))
    sigma, curvature = _noise_and_curvature(x, y, floor)
    penalty = config.complexity_factor * sigma ** 2 * np.log(len(x))
    interior = x[1:-1]
    if len(interior) > config.candidate_limit:
        strongest = np.argsort(-curvature, kind='stable')[:config.candidate_limit // 3]
        neighbors = np.clip(np.r_[strongest-1, strongest, strongest+1], 0, len(interior)-1)
        uniform = np.linspace(0, len(interior)-1, config.candidate_limit // 3).astype(int)
        indices = list(dict.fromkeys(np.r_[strongest, uniform, neighbors].tolist()))[:config.candidate_limit]
        candidates = np.sort(interior[indices])
    else:
        candidates = interior.copy()
    candidates = np.unique(np.r_[candidates, fixed])
    knots = list(fixed)
    evaluations = 0

    def solve(ks):
        nonlocal evaluations
        evaluations += 1
        return _solve(x, y, sorted(ks), centered_anchors)

    def available(ks):
        return [float(k) for k in candidates if all(abs(k-old) > 1e-9 for old in ks)]

    def refine(ks):
        ks = sorted(ks)
        for _ in range(config.refinement_passes):
            changed = False
            for old in list(ks):
                if old in fixed:
                    continue
                others = [k for k in ks if k != old]
                best = old; cost = solve(ks)[2]
                # Reposition within adjacent existing knots; short intervals are
                # allowed instead of requiring eight events on either side.
                left = max([x[0]] + [k for k in others if k < old])
                right = min([x[-1]] + [k for k in others if k > old])
                for value in candidates[(candidates > left) & (candidates < right)]:
                    trial = solve(others + [float(value)])[2]
                    if trial < cost - 1e-12:
                        cost, best = trial, float(value)
                if best != old:
                    ks = sorted(others + [best]); changed = True
            if not changed:
                break
        # MIDI changes need not fall on an observed quarter. Refine retained
        # locations continuously without reinstating an eight-event exclusion.
        for radius in (1., .25, .0625, .015625, .00390625):
            for old in list(ks):
                if old in fixed:
                    continue
                others = [k for k in ks if k != old]
                left = max([x[0]] + [k for k in others if k < old]) + 1e-5
                right = min([x[-1]] + [k for k in others if k > old]) - 1e-5
                best = old; cost = solve(ks)[2]
                for value in np.unique(np.clip(old + np.linspace(-radius, radius, 17), left, right)):
                    trial = solve(others + [float(value)])[2]
                    if trial < cost - 1e-14:
                        cost, best = trial, float(value)
                ks = sorted(others + [best])
        return ks

    for _ in range(config.max_knots + 1):
        current = solve(knots)[2]
        additions = [(solve(knots + [k])[2], k) for k in available(knots)] if len(knots) < config.max_knots else []
        additions.sort()
        if additions and current - additions[0][0] > penalty:
            knots = refine(knots + [additions[0][1]])
            continue
        # A brief excursion needs two boundaries. It may be invisible to a
        # one-knot-only greedy update even though the pair improves the cost.
        best_pair = None; pair_cost = current
        if len(knots) + 2 <= config.max_knots:
            pool = [k for _, k in additions[:config.pair_pool_size]]
            for a, b in combinations(pool, 2):
                cost = solve(knots + [a, b])[2]
                if cost + 2 * penalty < pair_cost:
                    best_pair, pair_cost = (a, b), cost + 2 * penalty
        if best_pair:
            knots = refine(knots + list(best_pair))
            continue
        break
    # Remove redundant free knots using the same continuous objective, not a
    # different independent-line segmentation criterion.
    for _ in range(config.max_knots):
        base_cost = solve(knots)[2] + penalty * len(knots)
        choices = [(solve([v for v in knots if v != k])[2] + penalty * (len(knots)-1), k)
                   for k in knots if k not in fixed]
        if not choices or min(choices)[0] >= base_cost - 1e-12:
            break
        knots.remove(min(choices)[1]); knots = refine(knots)
    coefficients, residual, rss = solve(knots)
    coefficients[0] += origin
    slopes = np.cumsum(coefficients[1:])
    if np.any(slopes <= 0):
        raise ValueError('fitted clock is not monotonic; review indices or anchors')
    starts, ends = np.r_[x[0], knots], np.r_[knots, x[-1]]
    segments = [{'start_pulse': float(a), 'end_pulse': float(b),
                 'start_seconds': float(clock_time([a], knots, coefficients)[0]),
                 'end_seconds': float(clock_time([b], knots, coefficients)[0]),
                 'pulse_rate_per_minute': float(60 / slope)} for a, b, slope in zip(starts, ends, slopes)]
    return {'schema_version': 'continuous-clock-fit-v2', 'accepted': False,
            'status': 'unaccepted_continuous_clock_v2', 'source_origin_seconds': 0,
            'pulse_unit': 'input index unit; musical interpretation supplied by caller', 'meter': None,
            'parameters': asdict(config), 'input_event_count': len(times), 'input_pulse_indices': x.tolist(),
            'pulse_index_span': [float(x[0]), float(x[-1])], 'knot_pulse_indices': knots,
            'coefficients': coefficients.tolist(), 'segments': segments,
            'support_seconds': [segments[0]['start_seconds'], segments[-1]['end_seconds']],
            'locked_knots': fixed,
            'anchor_checks': [{**a, 'absolute_error_seconds': abs(float(clock_time([a['quarter_position']], knots, coefficients)[0])-a['source_seconds'])} for a in anchors],
            'diagnostics': {'noise_estimate_seconds': sigma, 'split_penalty_seconds_squared': penalty,
                'residual_sum_squares': rss, 'penalized_objective': rss + penalty * len(knots),
                'candidate_count': len(candidates), 'least_squares_evaluations': evaluations,
                'event_fit_residual_ms_p50_p95_max': (1000*np.quantile(abs(residual), [.5,.95,1])).tolist(),
                'global_optimum_claimed': False, 'candidate_locations': 'observed pulse positions with continuous refinement plus explicit locks',
                'reference_used_for_fitting': False, 'warning': 'Caller must label oracle reference input; precision and residual are not correctness confidence.'}}
