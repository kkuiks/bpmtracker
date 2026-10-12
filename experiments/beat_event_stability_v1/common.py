from pathlib import Path
from experiments.beat_event_map_v1.common import (
    ROOT, CODE_ROOT, CONFIG as BASE_CONFIG, POLICIES, read, write, stamp, digest,
    code_hashes as base_code_hashes,
)

PARENT = ROOT / 'data/research/runs/beat_event_map_v1/20261012-full-v4'
CONFIG = {
    'base_config': BASE_CONFIG,
    'bar_score': 'symmetric source observation / predicted grid F1',
    'pcm_period': 'quarter period, independent of signature denominator',
    'minimum_proposal_pulse_density': BASE_CONFIG['initial_fit_quality'],
}
METHODS = {
    'L1_GRID_BALANCE': {'dense_proposals': False},
    'L2_DENSE_PROPOSALS': {'dense_proposals': True},
}
PILOT_IDS = ['e002', 'e007', 'r019', 'r003', 'r008', 'r005', 'r009']


def code_hashes():
    hashes = base_code_hashes()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        hashes[str(path.relative_to(CODE_ROOT))] = digest(path)
    return hashes


def guard(run):
    freeze = read(Path(run) / 'freeze.json')
    if (freeze['code_hashes'] != code_hashes() or freeze['config'] != CONFIG
            or freeze['methods'] != METHODS):
        raise RuntimeError('Frozen stability experiment changed')
