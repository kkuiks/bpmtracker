"""Known-clock mechanics prevent per-frame equivalence laundering."""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np

from .common import read, write
from .references import normalized
from .metrics import score


def fixture(states):
    quarters, bars, tempos, meters = [], [], [], []
    position = 0.
    for start, end, bpm, numerator, denominator in states:
        tempos.append({'time_seconds': start, 'bpm_quarter': bpm})
        meters.append({'time_seconds': start, 'numerator': numerator, 'denominator': denominator})
        finish = position + (end-start)*bpm/60
        for q in np.arange(np.ceil(position-1e-8), np.ceil(finish-1e-8)):
            quarters.append(start+(q-position)*60/bpm)
        length = numerator*4/denominator
        for q in np.arange(position, finish-1e-8, length):
            bars.append(start+(q-position)*60/bpm)
        position = finish
    track = {'reference_support_seconds': [[0, states[-1][1]]]}
    return normalized(track, {'tempo_events': tempos, 'meter_events': meters,
                              'beats_seconds': quarters, 'downbeats_seconds': bars})


def prediction(rows):
    return {'status': 'COMPOSED', 'accepted': [
        {'start': start, 'end': end, 'bpm': bpm, 'phase': phase, 'period': 60/bpm}
        for start,end,bpm,phase in rows], 'diagnostic': []}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); checks = []
    def check(name, passed, detail=None):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})
    ref = fixture([(0,60,120,4,4)])
    for bpm in (60,120,240):
        result = score(prediction([(0,60,bpm,0)]), ref)
        check('steady_permitted_' + str(bpm), result['stable_valid_fraction'] > .999 and result['unnecessary_changes'] == 0)
    result = score(prediction([(0,20,120,0),(20,40,240,0),(40,60,120,0)]), ref)
    check('equivalent_switches_still_count', result['unnecessary_changes'] == 2 and result['frame_permissive_fraction'] > .999)
    check('no_per_output_interval_reference_choice', result['region_coherent_fraction'] < .68 and result['stable_valid_fraction'] < result['region_coherent_fraction'])
    alternating = prediction([(float(i),float(i+1),120 if i%2==0 else 240,0) for i in range(60)])
    result = score(alternating, ref)
    check('frequent_valid_switches_not_success', result['frame_permissive_fraction'] > .999 and result['unnecessary_changes'] == 59 and result['stable_valid_fraction'] < .03)
    genuine = fixture([(0,20,120,4,4),(20,44,125,4,4),(44,60,120,4,4)])
    result = score(prediction([(0,20,120,0),(20,44,125,20),(44,60,120,44)]), genuine)
    check('small_genuine_changes_allowed', result['stable_valid_fraction'] > .995 and result['unnecessary_changes'] == 0 and result['matched_musical_changes'] == 2, result['change_events'])
    octave = fixture([(0,20,120,4,4),(20,60,240,4,4)])
    result = score(prediction([(0,20,120,0),(20,60,240,20)]), octave)
    check('true_double_not_blanket_forbidden', result['stable_valid_fraction'] > .999 and result['unnecessary_changes'] == 0)
    held = score(prediction([(0,60,120,0)]), octave)
    check('pulse_metric_not_exact_tempo_map_certificate', held['region_coherent_fraction'] > .999 and held['single_song_reading_fraction'] < .68)
    compound = fixture([(0,20,108,4,4),(20,60,108,6,8)])
    result = score(prediction([(0,20,108,0),(20,60,144,20)]), compound)
    check('compound_binary_change_at_real_boundary_allowed', result['stable_valid_fraction'] > .995 and result['unnecessary_changes'] == 0, result['change_events'])
    result = score(prediction([(0,30,108,0),(30,60,144,20)]), compound)
    check('same_change_late_is_not_free', result['unnecessary_changes'] == 1 and result['stable_valid_fraction'] < result['frame_permissive_fraction'])
    result = score(prediction([(0,30,120,0),(30,60,137,0)]), ref)
    check('unsupported_new_rate_is_not_equivalence', result['unnecessary_changes'] == 1 and result['region_coherent_fraction'] < .51)
    result = score(prediction([(0,30,120,0),(30,60,120,.25)]), ref)
    check('harmful_phase_jump_still_penalized', result['unnecessary_changes'] == 1 and result['region_coherent_fraction'] < .51)
    result = score(prediction([(0,30,120,0),(30,60,120,.5)]), ref)
    check('identical_physical_phase_not_false_change', result['stable_valid_fraction'] > .999 and result['raw_phase_adjustments'] == 0)
    result = score(prediction([]), ref)
    check('missing_clock_not_dropped', result['coverage_fraction'] == 0 and result['stable_valid_fraction'] == 0)
    small_then_switch = score(prediction([(0,20,120,0),(20,44,250,20),(44,60,120,44)]), genuine)
    check('unit_switch_at_small_change_not_excused', small_then_switch['unnecessary_changes'] >= 1, small_then_switch['change_events'])
    write(args.run / 'controls.json', {'checks': checks, 'all_pass': all(check['passed'] for check in checks),
                                      'not_independent_music_or_product_test': True})
    if not all(check['passed'] for check in checks):
        raise RuntimeError('Pre-target score mechanics failed')
    print('CONTROLS', len(checks), 'PASS', flush=True)


if __name__ == '__main__':
    main()
