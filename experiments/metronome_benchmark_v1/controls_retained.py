"""Structural controls for source-candidate retention and discrete hints."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from .inference import write_json
from .retained_clock import prepare_family, predict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(Path('experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    def clock(bpm, score):
        evidence = {'weighted_smooth_f1': .9}
        return {'quarter_bpm': float(bpm), 'bpm_fraction': {'numerator': bpm, 'denominator': 1},
                'period_seconds': 60 / bpm, 'time_signature': {'numerator': 4, 'denominator': 4},
                'offset_seconds': .1, 'score': score, 'beat_evidence': evidence,
                'downbeat_evidence': evidence}
    original = {'status': 'audio_family_prepared', 'audio_base_bpm': 160,
                'input_duration_seconds': 30, 'config': config, 'levels': []}
    before = deepcopy(original)
    rows = [clock(160, .8), clock(53, .7), clock(80, .6), clock(53, .75), clock(165, .79)]
    family = prepare_family(original, ({'candidate': row} for row in rows))
    tests = []
    def check(name, result):
        tests.append({'name': name, 'passed': bool(result)})
    check('broad clock survives single-base narrowing', predict(family, 53)['quarter_bpm'] == 53)
    check('same discrete unit ignores numeric fine tempo', predict(family, 155) == predict(family, 160) == predict(family, 165))
    check('original family and scores preserved', original == before and predict(family)['score'] == .8)
    check('best source score retained per unit', predict(family, 53)['score'] == .75)
    check('octave boundary abstains', predict(family, 160 * 2 ** .5)['status'] == 'ambiguous_initial_tap_unit')
    check('reference fields absent from preparation', family['reference_fields_used'] is False
          and family['all_candidates_and_scores_prepared_before_hint'])
    invalid = clock(160, .9); invalid['time_signature']['numerator'] = 5
    try:
        prepare_family(original, [{'candidate': invalid}])
        rejected = False
    except ValueError:
        rejected = True
    check('unsupported clock domain rejected', rejected)
    write_json(args.output, {'cases': tests, 'all_passed': all(row['passed'] for row in tests),
                             'audio_accuracy_claim': False})
    print(json.dumps(tests), flush=True)
    if not all(row['passed'] for row in tests):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
