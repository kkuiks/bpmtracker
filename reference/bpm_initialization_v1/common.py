"""Run identities and frozen inputs for the four initialization methods."""
from pathlib import Path

from experiments.bpm_continuity_v1.common import (
    ROOT, CONFIG, read, write, digest, object_hash, code_files as prior_code_files,
)

BASELINE = ROOT / 'data/research/runs/bpm_continuity_v1/20261010T072837Z-v1'
METHODS = ('I0_LOCAL6', 'I1_WHOLE_RATE_LOCAL6', 'I2_LOCAL12', 'I3_LOCAL24')
POLICIES = ('proxy_unit_minus5', 'proxy_unit_zero', 'proxy_unit_plus5')


def code_files():
    return sorted((ROOT / 'experiments/bpm_initialization_v1').glob('*.py')) + prior_code_files()


def guard(run):
    frozen = read(Path(run) / 'frozen.json')
    current = {str(p.relative_to(ROOT)): digest(p) for p in code_files()}
    if current != frozen['code_hashes']:
        raise RuntimeError('Frozen experiment code changed')
    for relative, expected in frozen['run_file_hashes'].items():
        if digest(Path(run) / relative) != expected:
            raise RuntimeError(f'Frozen experiment input changed: {relative}')
    return frozen
