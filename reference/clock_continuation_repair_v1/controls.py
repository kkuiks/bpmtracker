"""Small behavioral controls necessary for the requested no-gap repair."""
from __future__ import annotations

import argparse
from pathlib import Path
import copy
import numpy as np

from .common import write
from .repair import repair_raw, predict


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    clocks = [{'bpm': b, 'phase': .05, 'key': str(b), 'provenance': 'authored_control'} for b in [120., 240., 125.]]
    time = np.arange(.125, 10., .25)
    tab = {'time': time, 'duration': 10., 'clocks': clocks,
           'quality': np.full((len(time), 3), .95), 'count': np.full((len(time), 3), 16.),
           'seed_count': np.full((len(time), 3), 16.), 'information': np.ones(len(time), dtype=bool)}
    def segment(index, start, end):
        h = clocks[index]
        return {'start': start, 'end': end, 'bpm': h['bpm'], 'phase': h['phase'],
                'period': 60/h['bpm'], 'clock_index': index, 'provenance': 'authored_control'}
    packet = {'available': True, 'base_bpm': 120., 'scope_start': 0., 'scope_end': 2., 'clock': 0, 'power': 0}
    checks = []
    def check(name, passed): checks.append({'name': name, 'pass': bool(passed)})
    raw = {'accepted': [segment(0, 0., 2.), segment(1, 2., 4.), segment(2, 6., 9.75)], 'diagnostic': []}
    before = copy.deepcopy(raw)
    repaired = repair_raw(raw, tab, packet)
    check('original_accepted_intervals_are_preserved', [s for s in repaired['accepted'] if not s.get('continuation_gap')] == raw['accepted'])
    check('raw_input_not_mutated', raw == before)
    corrected = predict(raw, tab, packet)
    gap = next(s for s in corrected['accepted'] if s.get('continuation_gap') == 'HOLD' and s['start'] == 4.)
    check('internal_gap_holds_corrected_rate_and_phase', gap['bpm'] == 120. and gap['phase'] == .05)
    check('small_genuine_change_is_retained', any(s['start'] == 6. and s['bpm'] == 125. for s in corrected['accepted']))
    check('last_clock_reaches_real_source_end', corrected['accepted'][-1]['end'] == 10. and corrected['accepted'][-1]['bpm'] == 125.)
    first_gap = {'accepted': [segment(1, 5., 10.)], 'diagnostic': []}
    filled = predict(first_gap, tab, packet)
    check('initial_gap_uses_prepared_source_clock', filled['accepted'][0]['start'] == 0. and filled['accepted'][0]['bpm'] == 120.)
    check('later_half_double_alias_uses_repaired_initial_clock', all(s['bpm'] == 120. for s in filled['accepted']))
    weak = copy.deepcopy(tab); weak['quality'][:] = 0.; weak['count'][:] = 0.; weak['information'][:] = False
    held = predict({'accepted': [segment(0, 0., 10.)], 'diagnostic': []}, weak, packet)
    check('weak_and_absent_information_never_mutes_existing_clock', held['accepted'] == [segment(0, 0., 10.)])
    check('weak_confidence_remains_visible', bool(held['diagnostic']) and all(x['status'] == 'HELD_WEAK_EVIDENCE' for x in held['diagnostic']))
    empty = {'time': time, 'duration': 10., 'clocks': []}
    missing = predict({'accepted': [], 'diagnostic': []}, empty)
    check('no_clock_is_invented_without_source_candidates', missing['accepted'] == [] and missing['diagnostic'][0]['status'] == 'NO_AUDIO_CLOCK_AVAILABLE')
    write(args.output, {'checks': checks, 'all_pass': all(x['pass'] for x in checks),
                        'authored_contract_controls_not_real_music_accuracy': True})
    for x in checks: print(x['name'], x['pass'], flush=True)
    if not all(x['pass'] for x in checks): raise RuntimeError('Continuation control failed')


if __name__ == '__main__': main()
