from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSITION = ROOT / 'data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1'
LAST = ROOT / 'data/research/runs/octave_fold_confirmation_v1/20261011T083547Z-v1'
CONFIG = {
    'sample_step_seconds': .05, 'pulse_phase_tolerance_seconds': .07,
    'pulse_rate_relative_tolerance': .005,
    'structural_change_window_seconds': 4.,
    'unnecessary_change_penalty_seconds': 8.,
    'penalty_sensitivity_seconds': [4., 16.],
    'meaningful_phase_jump_seconds': .07,
    'proxy_ratios': [.97, 1., 1.03],
    'no_initial_five_seconds_removed': True,
    'primary_reference_selection': 'one_per_annotated_stable_region_not_per_output_interval',
    'raw_changes_classified_before_reference_selection': True,
    'all_song_fixed_reading_also_reported': True,
}
METHODS = {
    'B0_RAW': {'mode': 'raw', 'tolerance': .05},
    'B1_VETO05': {'mode': 'veto', 'tolerance': .05},
    'F1_FOLD05': {'mode': 'fold', 'tolerance': .05},
    'S1_FOLD03': {'mode': 'fold', 'tolerance': .03},
    'S2_FOLD08': {'mode': 'fold', 'tolerance': .08},
}
PRIMARY_READINGS = [
    {'name': 'QUARTER', 'kind': 'constant', 'factor': 1., 'offset': 0.},
    {'name': 'HALF_EVEN', 'kind': 'constant', 'factor': .5, 'offset': 0.},
    {'name': 'HALF_ODD', 'kind': 'constant', 'factor': .5, 'offset': .5},
    {'name': 'DOUBLE', 'kind': 'constant', 'factor': 2., 'offset': 0.},
    {'name': 'NOTATED_DENOMINATOR', 'kind': 'denominator'},
    {'name': 'COMPOUND_LARGE', 'kind': 'compound_large'},
    {'name': 'COMPOUND_BINARY', 'kind': 'compound_binary'},
]
BROAD_READINGS = []
for name, factor, denominator in [('THIRD', 1/3, 3), ('TWO_THIRDS', 2/3, 3),
                                   ('THREE_QUARTERS', .75, 4), ('FOUR_THIRDS', 4/3, 3),
                                   ('THREE_HALVES', 1.5, 2), ('TRIPLE', 3., 1)]:
    for offset in range(denominator):
        BROAD_READINGS.append({'name': name + '_' + str(offset), 'kind': 'constant',
                              'factor': factor, 'offset': (factor * offset) % 1.})
BROAD_READINGS += [
    {'name': 'QUARTER_OFFBEAT', 'kind': 'constant', 'factor': 1., 'offset': .5},
    {'name': 'PAIR_GROUPING', 'kind': 'pair_grouping'},
    {'name': 'TRIPLE_GROUPING', 'kind': 'triple_grouping'},
]
GATES = {
    'primary_method': 'F1_FOLD05', 'primary_policy': 'proxy100',
    'original21_stable_gain_min': .03,
    'original21_unnecessary_change_reduction_min': .30,
    'expanded11_stable_decline_max': .01,
    'variable10_stable_decline_max': .01,
    'useful_song_stable_fraction_min': .85,
    'useful_song_coverage_min': .95,
    'useful_song_unnecessary_changes_max': 0,
    'component_gate_not_product_acceptance': True,
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def code_hashes():
    paths = list(Path(__file__).parent.glob('*.py'))
    paths += [ROOT / name for name in read(LAST / 'freeze.json')['code_hashes']]
    paths += [ROOT / 'experiments/metronome_reconstruction_v1' / name for name in
              ['infer.py', 'hinted.py', 'config-tap-v2.json']]
    paths += [ROOT / 'experiments/variable_tempo_interval_consensus_v0/candidates.py']
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(paths))}


def guard(run):
    frozen = read(Path(run) / 'freeze.json')
    if frozen['code_hashes'] != code_hashes():
        raise RuntimeError('Source changed after freeze')
    for name, value in [('config', CONFIG), ('methods', METHODS), ('gates', GATES),
                        ('primary_readings', PRIMARY_READINGS), ('broad_readings', BROAD_READINGS)]:
        if frozen[name] != value:
            raise RuntimeError('Frozen settings changed: ' + name)
