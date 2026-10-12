"""Physical map controls separate from owner-reviewed real music accuracy."""
import argparse
from pathlib import Path
import numpy as np
from experiments.beat_event_map_v1.controls import fixture, observations
from experiments.beat_event_map_v1.source import prepare, encode
from experiments.continuous_beat_map_v1.map import grid, validate
from experiments.metronome_benchmark_v1.metrics import event_f1
from .common import write, guard, METHODS
from .core import fit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    guard(args.run)
    base = fixture(16., [])
    three = fixture(16., [])
    three['initial']['numerator'] = 3
    small = fixture(16., [{'time': 4., 'quarter': 12., 'bpm': 175.}])
    small['initial']['bpm'] = 180.
    cases = {
        'early_change': fixture(16., [{'time': 1.5, 'quarter': 3., 'bpm': 150.}]),
        'fourth_beat': fixture(16., [{'time': 3.5, 'quarter': 7., 'bpm': 150.}]),
        'short_excursion': fixture(16., [{'time': 3.5, 'quarter': 7., 'bpm': 150.},
                                      {'time': 5.5, 'quarter': 12., 'bpm': 120.}]),
        'partial_bar_meter': fixture(16., [{'time': 3.5, 'quarter': 7.,
                                          'numerator': 3, 'denominator': 4}]),
        'rhythm_density_only': base,
        'weak_evidence_dropout': base,
        'constant_three_four': three,
        'small_180_to_175': small,
    }
    rows = []
    for name, truth in cases.items():
        for method in METHODS:
            source = observations(truth, name == 'rhythm_density_only')
            if name == 'weak_evidence_dropout':
                for times, weights in [('times', 'weights'), ('downbeat_times', 'downbeat_weights'),
                                       ('pcm_times', 'pcm_weights')]:
                    use = source[times] < 4.
                    source[times], source[weights] = source[times][use], source[weights][use]
            bank = prepare(source)
            packet = encode(bank, truth['initial']['bpm'])
            prediction = fit(source, bank, packet, method)
            emitted, target = grid(prediction, 'quarter'), grid(truth, 'quarter')
            errors = np.array([np.min(abs(emitted - value)) for value in target])
            bar = event_f1(grid(prediction, 'bar'), grid(truth, 'bar'), .03)
            legal = validate(prediction)['legal']
            recall = float(np.mean(errors <= .03))
            no_false = not prediction['events'] if not truth['events'] else None
            passed = legal and recall == 1. and bar['f1'] == 1. and no_false is not False
            rows.append({'name': name, 'method': method, 'pass': passed,
                         'legal': legal, 'quarter_recall_30ms': recall,
                         'bar_f1_30ms': bar, 'expected_events': truth['events'],
                         'emitted_events': prediction['events'], 'prediction': prediction,
                         'no_false_change': no_false, 'synthetic_mechanics_only': True})
            print('CONTROL', name, method, recall, bar['f1'], len(prediction['events']), flush=True)
    write(args.run / 'controls.json', {'rows': rows, 'all_pass': all(r['pass'] for r in rows),
          'real_music_performance': False, 'failed_controls_retained': True})
    guard(args.run)
    print('CONTROLS', sum(r['pass'] for r in rows), '/', len(rows), flush=True)


if __name__ == '__main__':
    main()
