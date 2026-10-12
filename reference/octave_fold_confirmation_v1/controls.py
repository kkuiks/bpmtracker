"""Requested mechanics checks, distinct from real-music outcomes."""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np

from .common import METHODS, read, write, stamp
from .correct import apply


def fixture(rates, extra=(), phases=None, unsupported=()):
    phases = phases or [0.] * len(rates)
    clocks = []
    for rate, phase in list(zip(rates, phases)) + list(extra):
        if not any(abs(c['bpm'] - rate) < 1e-8 and abs(c['phase'] - phase) < 1e-8 for c in clocks):
            clocks.append({'bpm': float(rate), 'phase': float(phase), 'key': str(len(clocks))})
    times = np.arange(.125, 8 * len(rates), .25)
    quality = np.full((len(times), len(clocks)), .8)
    counts = np.full_like(quality, 12.)
    for index, clock in enumerate(clocks):
        if clock['bpm'] in unsupported:
            quality[:, index] = .1
    tab = {'time': times, 'clocks': clocks, 'quality': quality, 'seed_count': counts}
    accepted = []
    for i, (rate, phase) in enumerate(zip(rates, phases)):
        index = next(j for j, c in enumerate(clocks) if c['bpm'] == rate and c['phase'] == phase)
        accepted.append({'start': float(8 * i), 'end': float(8 * (i + 1)), 'bpm': float(rate),
                         'phase': float(phase), 'period': 60. / rate, 'clock_index': index})
    return {'status': 'COMPOSED', 'accepted': accepted, 'diagnostic': []}, tab


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    results = []
    cases = [
        ('unchanged', [120, 120], [], [120, 120], {}),
        ('double_count', [120, 240, 120], [], [120, 120, 120], {}),
        ('half_count', [120, 60, 120], [], [120, 120, 120], {}),
        ('small_change', [180, 175, 180], [], [180, 175, 180], {}),
        ('double_plus_small_change', [180, 350, 180], [(175, 0)], [180, 175, 180], {}),
        ('half_plus_small_change', [120, 61, 120], [(122, 0)], [120, 122, 120], {}),
        ('three_to_two_allowed', [120, 180], [], [120, 180], {}),
        ('two_to_three_allowed', [120, 80], [], [120, 80], {}),
        ('outside_alias_band_allowed', [120, 264], [], [120, 264], {}),
        ('dynamic_not_start_band', [120, 246, 248, 126, 140, 152], [(123, 0), (124, 0)],
         [120, 123, 124, 126, 140, 152], {}),
        ('missing_candidate_hold', [120, 246], [], [120, 120], {}),
        ('unsupported_candidate_hold', [120, 246], [(123, 0)], [120, 120], {'unsupported': (123,)}),
        ('same_rate_phase_return', [120, 120], [], [120, 120], {'phases': [0, .25]}),
        ('nested_phase_parity', [120, 240], [(120, .25)], [120, 120], {}),
    ]
    for name, rates, extra, expected, kwargs in cases:
        raw, tab = fixture(rates, extra, **kwargs)
        output = apply(raw, tab, 'F1_FOLD05', METHODS['F1_FOLD05'])
        actual = [span['bpm'] for span in output['accepted']]
        passed = actual == expected
        if name == 'same_rate_phase_return':
            passed &= output['accepted'][-1]['phase'] == .25
        if name == 'nested_phase_parity':
            passed &= output['accepted'][-1]['phase'] == 0.
        results.append({'name': name, 'passed': bool(passed), 'actual': actual, 'expected': expected})
    raw, tab = fixture([120, 246], [(123, 0)])
    output = apply(raw, tab, 'B1_VETO05', METHODS['B1_VETO05'])
    results.append({'name': 'veto_is_not_fold', 'passed': [s['bpm'] for s in output['accepted']] == [120, 120]})
    empty = apply({'status': 'NO_SEED', 'accepted': [], 'diagnostic': []}, tab, 'F1_FOLD05', METHODS['F1_FOLD05'])
    results.append({'name': 'no_initial_source_clock_no_creation', 'passed': empty['accepted'] == []})
    # Exact same source fixture, two possible musical annotations: correction
    # cannot distinguish genuine 2x from changed counting without extra evidence.
    raw, tab = fixture([120, 240])
    output = apply(raw, tab, 'F1_FOLD05', METHODS['F1_FOLD05'])
    limitations = [{'name': 'genuine_double_change_suppressed', 'raw_bpm': [120, 240],
                    'selected_bpm': [s['bpm'] for s in output['accepted']],
                    'genuine_reference': [120, 240], 'counting_change_reference': [120, 120],
                    'expected_known_loss_not_a_success': True}]
    write(args.run / 'controls.json', {'at_utc': stamp(), 'mechanics': results,
                                       'all_mechanics_pass': all(r['passed'] for r in results),
                                       'constructed_ambiguity_limitations': limitations,
                                       'not_independent_real_music': True})
    if not all(r['passed'] for r in results):
        raise RuntimeError('Mechanics controls failed')
    print('CONTROLS', len(results), 'PASS; genuine 2x limitation retained', flush=True)


if __name__ == '__main__':
    main()
