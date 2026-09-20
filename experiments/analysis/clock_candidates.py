"""Bounded, reference-independent clock alternatives from saved acoustic evidence.

This experiment preserves different pulse levels and phases before fitting. A
local-period lattice, with a continuity cost, supplies integer pulse indices;
it can fill sustained half-level observations and discard subdivision events.
Neither the ranking score nor an integer index establishes musical correctness.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass

import numpy as np

from fit_clock import clock_time, fit_clock, propose_splits
from run_beat_this import validate_events


@dataclass(frozen=True)
class CandidateConfig:
    window_seconds: float = 12.0
    hop_seconds: float = 6.0
    min_period_seconds: float = 60 / 320
    max_period_seconds: float = 60 / 35
    max_period_paths: int = 4
    phases: tuple = (0.0, 0.5)
    transition_cost: float = 8.0
    seed_band_ratio: float = 1.6
    indexing_tolerance_period: float = 0.35
    max_gap_pulses: int = 32
    min_events: int = 8
    max_events: int = 2000
    max_segments: int = 12
    split_penalty_seconds_squared: float = 0.01


def _probability(logits):
    return 1 / (1 + np.exp(-np.clip(logits, -60, 60)))


def _unique_periods(values, low, high, relative_tolerance=.04):
    result = []
    for value in values:
        if low <= value <= high and all(abs(np.log(value / old)) > relative_tolerance for old in result):
            result.append(float(value))
    return result


def local_period_paths(events, beat_logits, fps, config):
    """Return diverse period paths without consulting annotations or bar labels."""
    intervals = np.diff(events)
    centers = (events[:-1] + events[1:]) / 2
    valid = intervals[(intervals >= config.min_period_seconds) &
                      (intervals <= config.max_period_seconds)]
    if not len(valid):
        return []
    typical = float(np.median(valid))
    # Include both ends so sustained half/full mixtures are represented even
    # when one interpretation occupies only a small fraction of the recording.
    source_periods = [typical, float(np.median(valid[:min(20, len(valid))])),
                      float(np.median(valid[-min(20, len(valid)):]))]
    seeds = _unique_periods([p * factor for factor in (1, .5, 2)
                            for p in source_periods], config.min_period_seconds,
                           config.max_period_seconds)[:config.max_period_paths]
    windows = np.arange(events[0], events[-1] + config.hop_seconds / 2,
                        config.hop_seconds)
    if not len(windows):
        windows = np.array([events[0]])
    probability = _probability(beat_logits)
    observations = []
    for center in windows:
        local = intervals[abs(centers - center) <= config.window_seconds / 2]
        local = local[(local >= config.min_period_seconds / 2) &
                      (local <= config.max_period_seconds * 2)]
        if not len(local):
            local = np.array([typical])
        median = float(np.median(local))
        candidates = _unique_periods([median * f for f in (.5, 1, 2)] + seeds,
                                     config.min_period_seconds, config.max_period_seconds, .005)
        left = max(0, int((center - config.window_seconds / 2) * fps))
        right = min(len(probability), int((center + config.window_seconds / 2) * fps) + 1)
        signal = probability[left:right]
        costs = []
        for period in candidates:
            multiples = np.maximum(1, np.rint(local / period))
            timing = np.minimum(abs(local / period - multiples), 1)
            lag = max(1, round(period * fps))
            correlation = 0.0
            if len(signal) > lag:
                a, b = signal[:-lag], signal[lag:]
                correlation = float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12))
            costs.append(3 * float(np.median(timing)) - .2 * correlation)
        observations.append((np.array(candidates), np.array(costs)))
    paths = []
    for seed in seeds:
        history = []
        prior_periods = prior_cost = None
        for periods, emission in observations:
            allowed = abs(np.log(periods / seed)) <= np.log(config.seed_band_ratio)
            cost = emission + .1 * np.log2(periods / seed) ** 2
            cost[~allowed] = np.inf
            if prior_periods is None:
                back = np.full(len(periods), -1, dtype=int)
            else:
                transitions = prior_cost[:, None] + config.transition_cost * abs(
                    np.log(periods[None, :] / prior_periods[:, None]))
                back = np.argmin(transitions, axis=0)
                cost = cost + transitions[back, np.arange(len(periods))]
            history.append((periods, cost, back))
            prior_periods, prior_cost = periods, cost
        index = int(np.argmin(history[-1][1]))
        if not np.isfinite(history[-1][1][index]):
            continue
        selected = []
        for periods, _, back in reversed(history):
            selected.append(float(periods[index]))
            index = int(back[index])
        selected.reverse()
        if any(np.allclose(selected, p['periods_seconds'], atol=1e-6) for p in paths):
            continue
        paths.append({'seed_period_seconds': seed, 'centers_seconds': windows.tolist(),
                      'periods_seconds': selected, 'lattice_cost_not_confidence': float(np.min(prior_cost))})
    return paths


def index_events(events, path, config):
    """Assign skipped integer positions or reject subdivision/off-grid events."""
    times = [float(events[0])]
    indices = [0]
    discarded = []
    gaps = []
    for input_index, event in enumerate(events[1:], 1):
        midpoint = (times[-1] + event) / 2
        period = float(np.interp(midpoint, path['centers_seconds'], path['periods_seconds']))
        distance = (event - times[-1]) / period
        increment = int(round(distance))
        if not 1 <= increment <= config.max_gap_pulses or abs(distance - increment) > config.indexing_tolerance_period:
            discarded.append(input_index)
            continue
        if increment > 1:
            gaps.append({'after_quarter_position': indices[-1], 'missing_pulses': increment - 1,
                         'source_start_seconds': times[-1], 'source_end_seconds': float(event)})
        indices.append(indices[-1] + increment)
        times.append(float(event))
    return np.asarray(times), np.asarray(indices, dtype=float), discarded, gaps


def _rebuild_clock(proposal, knots, coefficients, span):
    result = deepcopy(proposal)
    knots, coefficients = np.asarray(knots, dtype=float), np.asarray(coefficients, dtype=float)
    slopes = np.cumsum(coefficients[1:])
    if np.any(slopes <= 0) or not np.isfinite(coefficients).all():
        raise ValueError('anchor constraints produce a non-monotonic clock')
    starts, ends = np.r_[0., knots], np.r_[knots, float(span)]
    result['knot_pulse_indices'] = knots.tolist()
    result['coefficients'] = coefficients.tolist()
    result['pulse_index_span'] = [0., float(span)]
    result['segments'] = [{'start_pulse': float(a), 'end_pulse': float(b),
                           'start_seconds': float(clock_time([a], knots, coefficients)[0]),
                           'end_seconds': float(clock_time([b], knots, coefficients)[0]),
                           'pulse_rate_per_minute': float(60 / slope)}
                          for a, b, slope in zip(starts, ends, slopes)]
    result['support_seconds'] = [result['segments'][0]['start_seconds'], result['segments'][-1]['end_seconds']]
    return result


def phase_clock(proposal, phase):
    coefficients = np.asarray(proposal['coefficients'], dtype=float)
    knots = np.asarray(proposal['knot_pulse_indices'], dtype=float)
    span = np.floor(proposal['pulse_index_span'][1] - phase)
    before = knots <= phase
    intercept = coefficients[0] + coefficients[1] * phase + float(
        np.sum(coefficients[2:][before] * (phase - knots[before])))
    slope = coefficients[1] + float(np.sum(coefficients[2:][before]))
    keep = (knots > phase) & (knots < phase + span)
    return _rebuild_clock(proposal, knots[keep] - phase,
                          np.r_[intercept, slope, coefficients[2:][keep]], span)


def apply_time_anchors(proposal, anchors):
    """Apply hard source-time / candidate-quarter anchors; never move audio.

    Quarter positions refer to the displayed candidate index system. A source
    time alone is insufficient to infer an original musical bar numbering.
    The correction is continuous, piecewise linear, constant outside anchors.
    """
    locked = [a for a in anchors if a.get('locked', True)]
    if not locked:
        return deepcopy(proposal), []
    locked.sort(key=lambda a: a['quarter_position'])
    x = np.array([a['quarter_position'] for a in locked], dtype=float)
    y = np.array([a['source_seconds'] for a in locked], dtype=float)
    span = proposal['pulse_index_span'][1]
    if (not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(y < 0) or
            np.any(np.diff(x) <= 0) or np.any(np.diff(y) <= 0) or x[0] < 0 or x[-1] > span):
        raise ValueError('locked anchors require unique increasing supported quarters and increasing source times')
    delta = y - clock_time(x, proposal['knot_pulse_indices'], proposal['coefficients'])
    nodes = np.unique(np.r_[0., proposal['knot_pulse_indices'], x, span])
    values = clock_time(nodes, proposal['knot_pulse_indices'], proposal['coefficients']) + np.interp(nodes, x, delta)
    slopes = np.diff(values) / np.diff(nodes)
    result = _rebuild_clock(proposal, nodes[1:-1], np.r_[values[0], slopes[0], np.diff(slopes)], span)
    if result['support_seconds'][0] < 0:
        raise ValueError('anchor constraints move the proposed first pulse before source zero')
    checks = [{'quarter_position': float(q), 'source_seconds': float(t),
               'absolute_error_seconds': float(abs(clock_time([q], result['knot_pulse_indices'], result['coefficients'])[0] - t)),
               'locked': True} for q, t in zip(x, y)]
    result['anchor_adjustment'] = 'continuous time-map correction; source PCM unchanged'
    result['diagnostics']['event_fit_residual_ms_p50_p95_max'] = None
    result['diagnostics']['residual_invalidated_by_user_anchor'] = True
    return result, checks


def indexed_grid(proposal):
    indices = np.arange(int(np.floor(proposal['pulse_index_span'][1])) + 1, dtype=float)
    times = clock_time(indices, proposal['knot_pulse_indices'], proposal['coefficients'])
    return [{'quarter_position': int(q), 'source_seconds': float(t)} for q, t in zip(indices, times) if t >= 0]


def tempo_events(proposal):
    segments = proposal['segments']
    return [{'source_seconds': b['start_seconds'], 'bpm_before': a['pulse_rate_per_minute'],
             'bpm_after': b['pulse_rate_per_minute'], 'type': 'step'}
            for a, b in zip(segments, segments[1:]) if abs(a['pulse_rate_per_minute'] - b['pulse_rate_per_minute']) > 1e-8]


def _rank(grid, logits, fps, events, proposal):
    times = np.array([p['source_seconds'] for p in grid])
    radius = max(1, round(.04 * fps))
    probability = _probability(logits)
    strengths = []
    for t in times:
        center = round(t * fps)
        left, right = max(0, center - radius), min(len(probability), center + radius + 1)
        strengths.append(float(np.max(probability[left:right])) if right > left else 0.)
    if not len(times):
        return -1e9, {}
    positions = np.searchsorted(times, events)
    distance = np.minimum(abs(events - times[np.clip(positions, 0, len(times)-1)]),
                          abs(events - times[np.clip(positions - 1, 0, len(times)-1)]))
    coverage = float(np.mean(distance <= .07))
    density_cost = .01 * len(tempo_events(proposal)) / max((times[-1] - times[0]) / 60, 1)
    mean_strength = float(np.mean(strengths))
    return mean_strength + .5 * coverage - density_cost, {
        'mean_beat_probability_at_grid': mean_strength,
        'fraction_official_events_near_grid': coverage, 'change_density_cost': density_cost,
        'warning': 'uncalibrated ranking; sparse half-time grids may rank above intended quarters'}


def generate_clock_candidates(beat_logits, downbeat_logits, fps, official_beats_seconds,
                              anchors=None, config=None):
    config = config or CandidateConfig()
    beat = np.asarray(beat_logits, dtype=float)
    downbeat = np.asarray(downbeat_logits, dtype=float)
    events = validate_events(official_beats_seconds)
    if (beat.ndim != 1 or downbeat.shape != beat.shape or not np.isfinite(beat).all() or
            not np.isfinite(downbeat).all() or not np.isfinite(fps) or fps <= 0):
        raise ValueError('finite equal-length logits and positive frame rate required')
    if config.max_period_paths < 1 or not config.phases or config.hop_seconds <= 0:
        raise ValueError('positive candidate budget, phases and hop required')
    anchors = list(anchors or [])
    output = {'schema_version': 'clock-candidates-v1', 'source_origin_seconds': 0,
              'reference_used_for_prediction': False, 'accepted': False,
              'configuration': asdict(config), 'candidates': [], 'rejected_candidates': [],
              'selected_candidate_id': None, 'selection_status': 'insufficient_evidence',
              'scope': 'candidate quarter clocks; meter and original musical index origin unresolved',
              'anchor_input': anchors}
    if not config.min_events <= len(events) <= config.max_events:
        output['selection_status'] = 'event_count_budget_or_insufficient_evidence'
        return output
    for path_index, path in enumerate(local_period_paths(events, beat, fps, config)):
        kept, positions, discarded, gaps = index_events(events, path, config)
        if len(kept) < config.min_events:
            continue
        if len(propose_splits(kept, config.min_events, config.split_penalty_seconds_squared, positions)) - 1 > config.max_segments:
            output['rejected_candidates'].append({'path': path_index, 'reason': 'segment_budget'})
            continue
        try:
            base = fit_clock(kept, config.min_events, config.split_penalty_seconds_squared,
                             pulse_indices=positions)
        except ValueError as error:
            output['rejected_candidates'].append({'path': path_index, 'reason': str(error)})
            continue
        for phase in config.phases:
            candidate_id = f'path{path_index}-phase{phase:g}'
            try:
                proposal = phase_clock(base, phase)
                proposal, checks = apply_time_anchors(proposal, anchors)
                grid = indexed_grid(proposal)
                if grid and grid[-1]['source_seconds'] > len(beat) / fps + 1 / fps:
                    raise ValueError('clock extends beyond observed source duration')
                score, components = _rank(grid, beat, fps, events, proposal)
            except ValueError as error:
                output['rejected_candidates'].append({'id': candidate_id, 'reason': str(error)})
                continue
            output['candidates'].append({'id': candidate_id, 'status': 'unaccepted_clock_candidate',
                'accepted': False, 'quarter_unit': 'hypothesis',
                'musical_index_origin': 'user_anchor_candidate_coordinates' if checks else 'candidate_relative_unanchored',
                'indexed_grid': grid, 'clock': proposal, 'tempo_events': tempo_events(proposal),
                'meter': {'status': 'unresolved', 'events': [], 'downbeat_logits_used': False},
                'evidence_score_not_confidence': float(score), 'ranking_components': components,
                'anchor_checks': checks, 'local_period_path': path,
                'discarded_input_event_indices': discarded, 'missing_pulse_hypotheses': gaps,
                'phase_offset_quarters': float(phase),
                'input_event_indexing': {'source_seconds': kept.tolist(), 'quarter_positions': positions.tolist()}})
    if output['candidates']:
        output['selected_candidate_id'] = max(output['candidates'], key=lambda c: c['evidence_score_not_confidence'])['id']
        output['selection_status'] = 'unaccepted_evidence_ranked_proposal'
    elif anchors:
        output['selection_status'] = 'no_candidate_satisfies_anchors_or_budgets'
    return output
