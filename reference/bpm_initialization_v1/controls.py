"""Semantic clock/output controls, including legitimate fractional rates."""
import argparse
from fractions import Fraction
import math
from pathlib import Path

import numpy as np
from experiments.bpm_continuity_v1.controls import fixture
from experiments.bpm_continuity_v1.evidence import Evidence
from experiments.bpm_continuity_v1.core import bootstrap, source_base
from experiments.metronome_reconstruction_v1.infer import make_evidence, score_candidate
from experiments.variable_tempo_interval_consensus_v0.candidates import pool, original_h
from .common import ROOT, METHODS, read, write, object_hash
from .core import initialize, render


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); run = args.run.resolve(); cfg = read(run / 'config.json'); checks = []
    def check(name, passed, details=None):
        checks.append({'name': name, 'passed': bool(passed), 'details': details})
        print('CONTROL', name, 'PASS' if passed else 'FAIL', flush=True)
    data, bank, _ = fixture(((160., 128),), silence=(15., 21.))
    evs = {int(w): Evidence(data, bank, dict(cfg, window=w)) for w in (6., 12., 24.)}
    initial = {'kind': 'proxy', 'power': 0}
    family = {'audio_base_bpm': 80., 'levels': [{'power': 1, 'best': {'quarter_bpm': 160., 'score': 1.}}]}
    for method in METHODS:
        seed_ev = evs[12] if method == 'I2_LOCAL12' else evs[24] if method == 'I3_LOCAL24' else evs[6]
        boot = initialize(evs[6], seed_ev, family, initial, method)
        pred, traces = render(evs[6], boot)
        check(method + '_SOURCE_SEED', boot['status'] == 'SEEDED', {'time': boot['seed']['time'] if boot['seed'] else None})
        check(method + '_NO_RETROSPECTIVE_OUTPUT', bool(pred['accepted']) and
              min(r['start'] for r in pred['accepted']) >= boot['seed']['time'])
        check(method + '_FIXED_RATE_AND_SILENCE', all(r['bpm'] == 160 for r in pred['accepted']) and
              not any(r['start'] < 21 and r['end'] > 15 for r in pred['accepted']) and
              not any(c['kind'] == 'BPM_CHANGE' for c in pred['changes']))
        if method in ('I2_LOCAL12', 'I3_LOCAL24'):
            check(method + '_MINIMUM_EVIDENCE_TIME', boot['seed']['time'] >= seed_ev.cfg['window'])
    check('BASELINE_BOOTSTRAP_UNCHANGED', object_hash(initialize(evs[6], evs[6], family, initial, METHODS[0])) ==
          object_hash(bootstrap(evs[6], initial)))
    whole = initialize(evs[6], evs[6], family, initial, METHODS[1])
    check('COMMON_POWER_TRANSLATED_ACROSS_FAMILY_BASES', whole['seed']['clock']['bpm'] == 160 and
          whole['whole_rate_choice']['family_power'] == 1 and whole['input']['power'] == 0)
    missing_family = {'audio_base_bpm': 80., 'levels': [{'power': 1, 'best': {'quarter_bpm': 159.75, 'score': 1.}}]}
    missing = initialize(evs[6], evs[6], missing_family, initial, METHODS[1])
    check('NO_INVENTED_RATE_OR_FALLBACK', missing['status'] == 'NO_SEED' and not render(evs[6], missing)[0]['accepted'])
    for window in (12, 24):
        ev = evs[window]
        for i in (round(window / cfg['step']), len(ev.time) - 3):
            j = 0; matches = ev.matches(i, j)
            ts, ws = ev.obs['beat']['times'], ev.obs['beat']['weights']
            mass = float(ws[(ts >= ev.start[i]) & (ts < ev.time[i])].sum())
            reward = sum(m['weight'] * math.exp(-.5 * (m['residual'] / cfg['epsilon']) ** 2) for m in matches)
            check(f'LONG_MATCH_CAPACITY_{window}_{i}', abs((reward / mass if mass else 0.) - ev.G[i, j]) < 1e-9 and
                  sum(m['primary'] for m in matches) == ev.count[i, j])
    # Constructed clocks challenge any tempting integer rounding repair. The
    # family winner below comes from the actual whole-input acoustic scorer,
    # rather than a hand-written rank; they do not enter the eight-song metrics.
    original_cfg = read(ROOT / 'experiments/metronome_reconstruction_v1/config-tap-v2.json')
    for nominal in (Fraction(561, 4), Fraction(569, 3)):
        value = float(nominal); phase = .137
        data, _, _ = fixture(((value, 256),))
        for k in range(0, 256, 4):
            index = round((phase + k * 60. / value) * 50)
            data['downbeat_logits'][index] = 9.
        acoustic = make_evidence(data['beat_logits'], data['downbeat_logits'], float(data['duration_seconds']), original_cfg)
        rates = {nominal, Fraction(math.floor(value)), Fraction(math.ceil(value)), nominal - Fraction(1, 4), nominal + Fraction(1, 4)}
        candidates = [score_candidate(acoustic, rate, 4, phase, original_cfg) for rate in rates]
        ranked = sorted(candidates, key=lambda x: -x['score'])
        bank, _ = pool([original_h(row, 'constructed_source_scored') for row in candidates])
        family = {'audio_base_bpm': value / 2., 'levels': [{'power': 1, 'best': ranked[0], 'top_candidates': ranked}]}
        ev6 = Evidence(data, bank, cfg)
        base = source_base(ev6)['audio_base_bpm']
        from experiments.metronome_reconstruction_v1.hinted import encode_tap_level
        initial = {'kind': 'proxy', 'power': encode_tap_level(base, value)['power']}
        boot = initialize(ev6, ev6, family, initial, METHODS[1]); pred, _ = render(ev6, boot)
        check(f'FRACTIONAL_{nominal}_WHOLE_SCORE', ranked[0]['quarter_bpm'] == value,
              [{'bpm': x['quarter_bpm'], 'score': x['score']} for x in ranked])
        check(f'FRACTIONAL_{nominal}_RENDERED_NO_ROUNDING', bool(pred['accepted']) and
              all(abs(r['bpm'] - value) < 1e-8 for r in pred['accepted']))
        outputs = []
        for ratio in (.95, 1., 1.05):
            encoded = {'kind': 'proxy', 'power': encode_tap_level(base, value * ratio)['power']}
            b = initialize(ev6, ev6, family, encoded, METHODS[1])
            outputs.append(object_hash(render(ev6, b)))
        check(f'FRACTIONAL_{nominal}_SAME_UNIT_IDENTITY', len(set(outputs)) == 1)
    write(run / 'controls.json', {'passed': all(x['passed'] for x in checks), 'checks': checks,
                                  'targets_predicted_or_scored': False,
                                  'constructed_clocks_are_not_real_song_performance': True})
    if not all(x['passed'] for x in checks):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
