"""Permissible pulses do not erase switches in the original output."""
from __future__ import annotations

import numpy as np

from .common import CONFIG, PRIMARY_READINGS, BROAD_READINGS
from .references import inside, coordinate, arrays, templates


def matches(clock, times, ref, template):
    times = np.asarray(times, dtype=float)
    bpm = np.full(len(times), float(clock['bpm'])); phase = np.full(len(times), float(clock['phase']))
    return match_arrays(bpm, phase, times, ref, [template])[0]


def match_arrays(bpm, phase, times, ref, alternatives):
    beta, region, support = arrays(times, ref)
    safe_rate = np.where(np.isfinite(bpm), bpm, 120.)
    period = 60. / safe_rate
    ticks = phase + np.rint((times - phase) / period) * period
    q = coordinate(np.nan_to_num(ticks, nan=0.), ref)
    result = np.zeros((len(alternatives), len(times)), dtype=bool)
    for index, alternative in enumerate(alternatives):
        for state_index, state in enumerate(alternative['states']):
            use = support & (region == state_index) & np.isfinite(bpm) & np.isfinite(phase)
            if not use.any():
                continue
            value = q[use] * state['factor'] - state['offset']
            phase_error = abs(value - np.rint(value)) * 60. / state['pulse_bpm']
            rate_ok = abs(bpm[use] / state['pulse_bpm'] - 1.) <= CONFIG['pulse_rate_relative_tolerance'] + 1e-12
            result[index, use] = rate_ok & (phase_error <= CONFIG['pulse_phase_tolerance_seconds'] + 1e-12)
    return result


def equivalent_phase_jump(left, right, time):
    period = 60. / left['bpm']
    return abs((left['phase'] - right['phase'] + period/2) % period - period/2)


def classify_changes(prediction, ref, alternatives):
    result = []
    for before, after in zip(prediction['accepted'], prediction['accepted'][1:]):
        rate_change = abs(before['bpm'] - after['bpm']) > 1e-8
        phase_jump = equivalent_phase_jump(before, after, after['start']) if not rate_change else 0.
        if not rate_change and phase_jump <= 1e-6:
            continue
        time = after['start']
        kind = 'RATE' if rate_change else 'PHASE'
        record = {'time': time, 'kind': kind, 'before_bpm': before['bpm'], 'after_bpm': after['bpm'],
                  'before_phase': before['phase'], 'after_phase': after['phase'], 'phase_jump_seconds': phase_jump}
        if not inside(np.array([time]), ref['support'])[0]:
            record['classification'] = 'OUTSIDE_APPROVED_SCOPE'; result.append(record); continue
        if time - before['end'] > 1e-7:
            record['classification'] = 'RESTART_AFTER_OUTPUT_GAP'; result.append(record); continue
        if not rate_change and phase_jump <= CONFIG['meaningful_phase_jump_seconds']:
            record['classification'] = 'MINOR_PHASE_ADJUSTMENT'; result.append(record); continue
        genuine = []
        for index in range(1, len(ref['states'])):
            boundary = ref['states'][index]['start']
            if abs(time - boundary) > CONFIG['structural_change_window_seconds']:
                continue
            for alternative in alternatives:
                left_ok = matches(before, np.array([boundary - 1e-5]), ref, alternative)[0]
                right_ok = matches(after, np.array([boundary + 1e-5]), ref, alternative)[0]
                l, r = alternative['states'][index-1:index+1]
                expected_change = abs(l['pulse_bpm'] - r['pulse_bpm']) > 1e-8 or (not rate_change and phase_jump > CONFIG['meaningful_phase_jump_seconds'])
                if left_ok and right_ok and expected_change:
                    genuine.append({'boundary': boundary, 'error_seconds': time-boundary, 'reading': alternative['name']})
        if genuine:
            record['classification'] = 'MUSICAL_CHANGE'; record['matched_structural_changes'] = genuine
        else:
            epsilon = min(.025, max(1e-4, (after['end'] - time) / 4))
            old_before = any(matches(before, np.array([time - epsilon]), ref, a)[0] for a in alternatives)
            old_after = any(matches(before, np.array([time + epsilon]), ref, a)[0] for a in alternatives)
            new_after = any(matches(after, np.array([time + epsilon]), ref, a)[0] for a in alternatives)
            record.update({'old_pulse_valid_before': old_before, 'old_pulse_still_valid_after': old_after,
                           'new_pulse_valid_after': new_after})
            if old_after or (old_before and new_after):
                record['classification'] = 'UNNECESSARY_CHANGE'
            elif new_after:
                record['classification'] = 'RECOVERY'
            else:
                record['classification'] = 'UNSUPPORTED_CHANGE'
        result.append(record)
    return result


def longest(mask, step):
    start = np.flatnonzero(mask & ~np.r_[False, mask[:-1]])
    end = np.flatnonzero(mask & ~np.r_[mask[1:], False]) + 1
    return float(max((b-a for a,b in zip(start,end)), default=0) * step)


def score(prediction, ref, broad=False):
    duration = max(end for _, end in ref['support'])
    times = np.arange(CONFIG['sample_step_seconds']/2, duration, CONFIG['sample_step_seconds'])
    support = inside(times, ref['support']); n = int(support.sum())
    bpm = np.full(len(times), np.nan); phase = np.full(len(times), np.nan)
    for segment in prediction['accepted']:
        use = (times >= segment['start']) & (times < segment['end'])
        bpm[use] = segment['bpm']; phase[use] = segment['phase']
    readings = PRIMARY_READINGS + (BROAD_READINGS if broad else [])
    alternatives = templates(ref, readings)
    matching = match_arrays(bpm, phase, times, ref, alternatives)
    permissive = matching.any(axis=0)
    choices, coherent = [], np.zeros(len(times), dtype=bool)
    for index, state in enumerate(ref['states']):
        use = support & (times >= state['start']) & (times < state['end'])
        if not use.any():
            continue
        counts = matching[:, use].sum(axis=1)
        winner = int(np.argmax(counts))
        coherent[use] = matching[winner, use]
        choices.append({'start': state['start'], 'end': state['end'], 'reference_bpm': state['bpm'],
                        'meter': [state['numerator'], state['denominator']], 'reading': alternatives[winner]['name'],
                        'valid_fraction': float(counts[winner] / use.sum())})
    full_counts = matching[:, support].sum(axis=1); global_winner = int(np.argmax(full_counts))
    changes = classify_changes(prediction, ref, alternatives)
    unnecessary = [event for event in changes if event['classification'] == 'UNNECESSARY_CHANGE']
    stable_masks = {}
    for seconds in [CONFIG['unnecessary_change_penalty_seconds']] + CONFIG['penalty_sensitivity_seconds']:
        penalty = np.zeros(len(times), dtype=bool)
        for event in unnecessary:
            penalty |= (times >= event['time']) & (times < event['time'] + seconds)
        stable_masks[str(int(seconds))] = coherent & ~penalty & support
    stable = stable_masks[str(int(CONFIG['unnecessary_change_penalty_seconds']))]
    return {'frame_permissive_fraction': float((permissive & support).sum()/n),
            'region_coherent_fraction': float((coherent & support).sum()/n),
            'single_song_reading_fraction': float(full_counts[global_winner]/n),
            'single_song_reading': alternatives[global_winner]['name'],
            'stable_valid_fraction': float(stable.sum()/n),
            'stable_penalty_sensitivity': {key: float(mask.sum()/n) for key,mask in stable_masks.items()},
            'longest_stable_valid_seconds': longest(stable, CONFIG['sample_step_seconds']),
            'coverage_fraction': float((support & np.isfinite(bpm)).sum()/n),
            'unnecessary_changes': len(unnecessary),
            'unnecessary_changes_per_minute': len(unnecessary)/(n*CONFIG['sample_step_seconds']/60),
            'raw_rate_changes': sum(e['kind'] == 'RATE' and e['classification'] != 'OUTSIDE_APPROVED_SCOPE' for e in changes),
            'raw_phase_adjustments': sum(e['kind'] == 'PHASE' and e['classification'] != 'OUTSIDE_APPROVED_SCOPE' for e in changes),
            'unsupported_changes': sum(e['classification'] == 'UNSUPPORTED_CHANGE' for e in changes),
            'recovery_changes': sum(e['classification'] == 'RECOVERY' for e in changes),
            'matched_musical_changes': sum(e['classification'] == 'MUSICAL_CHANGE' for e in changes),
            'region_readings': choices, 'change_events': changes,
            'scope_seconds': n*CONFIG['sample_step_seconds'], 'readings': [a['name'] for a in alternatives],
            'full_meter_prediction_scored': False,
            'operational_reading_rules_not_individual_alternate_listening_certificates': True}
