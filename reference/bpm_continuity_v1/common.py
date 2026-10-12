"""Explicit run I/O, configuration and provenance; no implicit execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / 'data/research/runs/variable_tempo_interval_consensus_v0/20261008-mcc-a-v1'
ARMS = ('C1_STATELESS', 'C2_CONTINUITY', 'C_HOLD')
POLICIES = ('oracle_start', 'proxy_unit_minus5', 'proxy_unit_zero', 'proxy_unit_plus5')
CONFIG = {
    'step': .25, 'window': 6., 'seed_deadline': 30., 'epsilon': .02,
    'tau_max': .04, 'tau_fraction': .15, 'seed_S': .55, 'keep_G': .65,
    'change_G': .80, 'margin': .05, 'keep_count': 4, 'seed_count': 8,
    'fresh_periods': 2., 'change_span_periods': 4., 'confirm_steps': 4,
    'equiv_rate': .005, 'equiv_time': .04, 'harmonic_tolerance': .01,
    'drift_slope_floor': .005, 'drift_absolute': .06, 'drift_period_fraction': .15,
    'drift_outlier_fraction': .5, 'drift_max_tick_gap': 2,
    'drift_unwrap': 'source_candidate_quarter_index', 'context_radius': 2,
    'comparison_epsilon': 1e-12,
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.partial')
    part.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    part.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def code_files():
    local = sorted((ROOT / 'experiments/bpm_continuity_v1').glob('*.py'))
    dependencies = [
        'experiments/variable_tempo_interval_consensus_v0/core.py',
        'experiments/variable_tempo_interval_consensus_v0/candidates.py',
        'experiments/variable_tempo_interval_consensus_v0/io.py',
        'experiments/metronome_reconstruction_v1/hinted.py',
        'experiments/metronome_reconstruction_v1/infer.py',
        'experiments/metronome_reconstruction_v1/grid.py',
        'experiments/metronome_reconstruction_v1/config-tap-v2.json',
        'experiments/metronome_benchmark_v1/metrics.py',
        'experiments/metronome_benchmark_v1/trace.py',
        'tools/project_storage.py',
    ]
    return local + [ROOT / p for p in dependencies]


def code_hashes():
    return {str(p.relative_to(ROOT)): digest(p) for p in code_files()}


def frozen_guard(run):
    frozen = read(Path(run) / 'frozen.json')
    if code_hashes() != frozen['code_hashes']:
        raise RuntimeError('Frozen implementation changed; do not resume or overwrite scored predictions')
    for relative, expected in frozen['run_file_hashes'].items():
        if digest(Path(run) / relative) != expected:
            raise RuntimeError(f'Frozen run input changed: {relative}')
    return frozen
