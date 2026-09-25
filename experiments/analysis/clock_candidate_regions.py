"""Development v2: restart candidates in observable regions without inventing gap indices.

The frozen v1 predictor is unchanged. Every returned map covers one region only;
multiple regions never imply that their quarter-zero coordinates are aligned.
"""
from dataclasses import asdict, dataclass
import numpy as np

from clock_candidates import (CandidateConfig, generate_clock_candidates, validate_candidate_inputs,
                              _positive_integer)
from run_beat_this import validate_events


@dataclass(frozen=True)
class RegionConfig:
    minimum_stable_events: int = 8
    stable_fractional_period_tolerance: float = .2
    gap_floor_seconds: float = 4.
    gap_period_multiple: float = 8.
    max_regions: int = 2
    max_candidates: int = 8



def validate_region_config(config):
    _positive_integer(config.minimum_stable_events, 'minimum_stable_events', 2)
    _positive_integer(config.max_regions, 'max_regions')
    _positive_integer(config.max_candidates, 'max_candidates')
    if (not np.isfinite(config.stable_fractional_period_tolerance) or
            config.stable_fractional_period_tolerance < 0):
        raise ValueError('stable_fractional_period_tolerance must be finite and nonnegative')
    for name in ('gap_floor_seconds', 'gap_period_multiple'):
        value = getattr(config, name)
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')


def evidence_regions(events, config=None):
    config = config or RegionConfig()
    validate_region_config(config)
    events = validate_events(events)
    if len(events) < config.minimum_stable_events:
        return [], [], []
    intervals = np.diff(events)
    plausible = intervals[(intervals >= 60 / 320) & (intervals <= 60 / 35)]
    typical = float(np.median(plausible)) if len(plausible) else float(np.median(intervals))
    gap_threshold = max(config.gap_floor_seconds, config.gap_period_multiple * typical)
    cuts = np.r_[0, np.flatnonzero(intervals > gap_threshold) + 1, len(events)]
    bridges = [{'source_start_seconds': float(events[i-1]), 'source_end_seconds': float(events[i]),
                'quarter_count': None, 'status': 'unknown_bridge_do_not_interpolate',
                'gap_threshold_seconds': gap_threshold} for i in cuts[1:-1]]
    eligible, rejected = [], []
    for left, right in zip(cuts[:-1], cuts[1:]):
        found = None
        for start in range(int(left), int(right) - config.minimum_stable_events + 1):
            sample = np.diff(events[start:start + config.minimum_stable_events])
            period = float(np.median(sample))
            multiples = np.rint(sample / period)
            if (60 / 320 <= period <= 60 / 35 and np.all((multiples >= 1) & (multiples <= 2)) and
                    np.max(abs(sample / period - multiples)) <= config.stable_fractional_period_tolerance):
                found = {'input_start_index': start, 'input_end_index_exclusive': int(right),
                         'source_support_seconds': [float(events[start]), float(events[right-1])],
                         'excluded_prefix_seconds': [float(events[left]), float(events[start])],
                         'stable_window_event_count': config.minimum_stable_events,
                         'stable_window_period_seconds': period, 'gap_threshold_seconds': gap_threshold}
                break
        if found is None:
            rejected.append({'source_support_seconds': [float(events[left]), float(events[right-1])],
                             'event_count': int(right-left), 'reason': 'no_eight_event_periodic_window'})
        else:
            eligible.append(found)
    # Long regions get a bounded opportunity. This is source evidence, not label
    # quality or the best-performing region selected after seeing references.
    ranked = sorted(eligible, key=lambda r: (-(r['source_support_seconds'][1]-r['source_support_seconds'][0]),
                                           r['source_support_seconds'][0]))
    for omitted in ranked[config.max_regions:]:
        rejected.append({**omitted, 'reason': 'region_budget'})
    retained = sorted(ranked[:config.max_regions], key=lambda r: r['source_support_seconds'][0])
    return retained, bridges, rejected


def generate_region_candidates(beat_logits, downbeat_logits, fps, official_beats_seconds,
                               config=None, *, source_duration_seconds=None, ranking_policy='legacy'):
    config = config or RegionConfig()
    validate_region_config(config)
    beat_logits, downbeat_logits, events, fps, duration = validate_candidate_inputs(
        beat_logits, downbeat_logits, fps, official_beats_seconds, source_duration_seconds)
    if ranking_policy != 'legacy':
        raise ValueError('experimental ranking is limited to full-source candidates; region candidates require legacy ranking')
    regions, bridges, rejected = evidence_regions(events, config)
    output = {'schema_version': 'clock-candidate-regions-v2', 'accepted': False,
              'reference_used_for_prediction': False, 'source_origin_seconds': 0,
              'configuration': {'regions': asdict(config), 'frozen_predictor': asdict(CandidateConfig())},
              'ranking_policy': ranking_policy, 'source_window_seconds': [0., duration],
              'scope': 'one observable region per candidate; source origin preserved; unknown quarter bridges',
              'full_song_map': False, 'regions': regions, 'unknown_bridges': bridges,
              'rejected_regions': rejected, 'rejected_candidates': [], 'candidates': [],
              'selected_candidate_id': None, 'selection_status': 'no_supported_region',
              'evaluation_role': 'development iteration after observing v1 failures; not unseen validation'}
    if not regions:
        return output
    budget = max(1, config.max_candidates // len(regions))
    for number, region in enumerate(regions):
        subset = events[region['input_start_index']:region['input_end_index_exclusive']]
        generated = generate_clock_candidates(beat_logits, downbeat_logits, fps, subset,
            source_duration_seconds=duration, ranking_policy=ranking_policy)
        # Retain different period paths before alternate phases; never rank or
        # prune with reference scores. Total emitted candidates remains <= 8.
        remaining = max(0, config.max_candidates - len(output['candidates']))
        candidates = sorted(generated['candidates'], key=lambda c: (c['phase_offset_quarters'], c['id']))[:min(budget, remaining)]
        if generated['candidates'] and not remaining:
            output['rejected_regions'].append({**region, 'reason': 'global_candidate_budget'})
        region['v1_selection_status'] = generated['selection_status']
        region['v1_candidate_count'] = len(generated['candidates'])
        output['rejected_candidates'].extend({'region': number, **r} for r in generated['rejected_candidates'])
        for candidate in candidates:
            candidate['id'] = f'region{number}-' + candidate['id']
            candidate['status'] = 'unaccepted_partial_region_clock'
            candidate['full_song_map'] = False
            candidate['musical_index_origin'] = 'region_relative_unanchored_no_cross_region_index_mapping'
            candidate['region'] = {'id': number, **region}
            candidate['source_support_seconds'] = candidate['clock']['support_seconds']
            candidate['unknown_bridges'] = bridges
            candidate['region_selection_score_not_confidence'] = candidate['evidence_score_not_confidence']
            output['candidates'].append(candidate)
    if output['candidates']:
        output['selected_candidate_id'] = max(output['candidates'], key=lambda c: c['region_selection_score_not_confidence'])['id']
        output['selection_status'] = 'unaccepted_partial_region_proposal'
    else:
        output['selection_status'] = 'supported_region_but_v1_candidate_budget_or_indexing_failure'
    return output
