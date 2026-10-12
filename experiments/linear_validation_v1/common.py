from pathlib import Path
from experiments.beat_event_stability_v1.common import (
    ROOT, CODE_ROOT, CONFIG, METHODS, POLICIES, read, write, digest, stamp,
    code_hashes as candidate_hashes,
)

CANDIDATE = ROOT / 'data/research/runs/beat_event_stability_v1/20261012-full-v2'
GTZAN = ROOT / 'data/research/runs/metronome_benchmark_v1/20261007-gtzan-development280-frozen-v1'
FIXED = ROOT / 'data/research/runs/metronome_reconstruction_v1/20261005-tap26-v2'
PRIMARY = 'L2_DENSE_PROPOSALS'


def code_hashes():
    hashes = candidate_hashes()
    dependencies = [CODE_ROOT / 'experiments/metronome_reconstruction_v1' / name
                    for name in ('infer.py', 'hinted.py', 'grid.py', 'config-tap-v2.json')]
    dependencies += [CODE_ROOT / 'experiments/variable_clock_composition_v1/sensors.py',
                     CODE_ROOT / 'experiments/multiple_rhythm_continuity_v1/references.py',
                     CODE_ROOT / 'experiments/multiple_rhythm_continuity_v1/metrics.py',
                     CODE_ROOT / 'experiments/multiple_rhythm_continuity_v1/common.py',
                     CODE_ROOT / 'experiments/metronome_benchmark_v1/metrics.py']
    dependencies += list(Path(__file__).parent.glob('*.py'))
    for path in dependencies:
        hashes[str(path.relative_to(CODE_ROOT))] = digest(path)
    return hashes


def guard(run):
    candidate = read(CANDIDATE / 'freeze.json')
    if candidate['code_hashes'] != candidate_hashes() or candidate['config'] != CONFIG:
        raise RuntimeError('The candidate selected by the owner changed')
    freeze = read(Path(run) / 'freeze.json')
    if freeze['code_hashes'] != code_hashes() or freeze['config'] != CONFIG:
        raise RuntimeError('Frozen validation code or candidate changed')
