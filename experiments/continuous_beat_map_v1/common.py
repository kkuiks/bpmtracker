from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/research/runs/clock_continuation_repair_v1/20261011T114302Z-v1'
MULTIPLE = ROOT / 'data/research/runs/multiple_rhythm_continuity_v1/20261011T102117Z-v1'
COMPOSITION = ROOT / 'data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1'
FIXED = ROOT / 'data/research/analyses/fixed_vs_variable/20261011-fixed13-v1'
POLICIES = ['none', 'proxy97', 'proxy100', 'proxy103']
CONFIG = {
    'signatures': [[2, 4], [3, 4], [4, 2], [4, 4], [5, 4], [6, 4], [6, 8], [7, 4]],
    'bpm_domain': [30, 400], 'rational_denominator': 4,
    'proposal_step_seconds': 2., 'beam_size': 24,
    'lookahead_seconds': 12., 'lookahead_score_seconds': 4.,
    'initial_window_seconds': 24., 'initial_rate_proposals': 14,
    'local_rate_proposals': 7, 'initial_phase_proposals_per_rate': 5,
    'initial_states_per_unit': 96, 'local_change_beat_proposals': 3,
    'pulse_factors': [0.5, 1., 2., 2/3, 4/3, 1/3, 3/2, 3/4],
    'pulse_factor_cost': 0.018,
    'neural_sigma_seconds': .025, 'pcm_sigma_seconds': .035,
    'neural_beat_weight': .72, 'neural_bar_weight': .22, 'pcm_weight': .06,
    'tempo_change_cost_seconds': 1.2, 'meter_change_cost_seconds': .6,
    'octave_change_extra_cost_seconds': 3., 'octave_ratio_tolerance': .03,
    'minimum_tempo_hold_seconds': 12., 'minimum_meter_hold_seconds': .8,
    'initial_rate_radius': .12,
    'minimum_source_events': 6, 'minimum_initial_source_score': .15,
    'meter_prior': {'4/4': 0., '3/4': .004, '6/8': .004, '2/4': .008,
                    '4/2': .008, '5/4': .012, '6/4': .012, '7/4': .012},
}

def read(path): return json.loads(Path(path).read_text())
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()
def code_hashes():
    paths=list(Path(__file__).parent.glob('*.py'))
    paths += [ROOT/'experiments/multiple_rhythm_continuity_v1'/name for name in ['common.py','references.py','metrics.py']]
    paths += [ROOT/'experiments/variable_clock_composition_v1'/name for name in ['common.py','evaluate.py']]
    paths += [ROOT/'experiments/metronome_benchmark_v1/metrics.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}
def guard(run):
    if read(Path(run)/'freeze.json')['code_hashes'] != code_hashes():
        raise RuntimeError('Frozen experiment code changed')
