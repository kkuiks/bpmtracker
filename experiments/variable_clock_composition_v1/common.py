from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'data/research/runs/variable_tempo_interval_consensus_v0/20261008-mcc-a-v1'
CONTINUITY = ROOT / 'data/research/runs/bpm_continuity_v1/20261010T072837Z-v1'
CONFIG = {
    'step': .25, 'windows': [8., 24.], 'epsilon': .025,
    'proposal_spans': [4., 8., 16., 32., 64.], 'proposal_step': 2.,
    'proposal_rates_per_window': 4, 'proposal_min_events': 5,
    'candidate_budget': 1536, 'small_budget': 512,
    'quality_threshold': .62, 'minimum_seed_seconds': 3.,
    'minimum_seed_quarters': 8, 'information_mass': 1.5,
    'change_penalty': 1.25, 'phase_penalty': .35, 'octave_penalty': .35,
    'contradiction_margin': .15, 'contradiction_quality': .67,
    'contradiction_unexplained': .25, 'contradiction_seconds': 1.,
    'beam': 24, 'destination_beam': 12,
    'initial_deadline': 30., 'refit_passes': 1,
}
METHODS = {
    'M0_LOCAL': {'mode': 'local'},
    'M1_NARROW_HOLD': {'bank': 'final'},
    'M2_INITIAL_FORWARD': {'anchor': 'initial'},
    'M3_REGION_HOLD': {},
    'M4_WEAK_MUTE': {'mute_weak': True},
    'M5_NO_PHASE_LINK': {'phase_penalty': 0.},
    'M6_NO_REFIT': {'bank': 'unrefined'},
    'M7_PCM': {'pcm': True},
    'M8_SMALL_BANK': {'bank': 'small'},
    'S0_LOW_CHANGE_COST': {'change_penalty': .625},
    'S1_HIGH_CHANGE_COST': {'change_penalty': 2.5},
    'S2_LOW_SEED_THRESHOLD': {'quality_threshold': .56},
    'S3_HIGH_SEED_THRESHOLD': {'quality_threshold': .68},
}
GATES = {
    'primary_method': 'M3_REGION_HOLD', 'primary_policy': 'none',
    'viable_real_songs_required': 2, 'confirmation_songs_required': 1,
    'song_correct_clock_min': .70, 'song_quarter_f1_min': .80,
    'song_wrong_clock_max': .15, 'successful_transitions_per_song_min': 2,
    'long_region_correct_min': .80, 'long_regions_per_song_min': 2,
    'long_region_min_seconds': 20., 'transition_quarters_each_side': 8,
    'transition_matching_fraction': .75, 'transition_boundary_tolerance_seconds': 2.,
    'transition_maximum_recovery_delay_seconds': 4.,
    'oracle_long_region_min': .80, 'oracle_viable_songs_min': 2,
    'control_wrong_clock_increase_max': .05,
    'gate_is_research_decision_not_product_acceptance': True,
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_suffix(p.suffix + '.partial')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    part.replace(p)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def code_hashes():
    files = list(Path(__file__).parent.glob('*.py'))
    files += [ROOT/'experiments/variable_tempo_interval_consensus_v0/core.py',
              ROOT/'experiments/metronome_reconstruction_v1/grid.py',
              ROOT/'experiments/metronome_benchmark_v1/metrics.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}


def guard(run):
    f = read(Path(run)/'freeze.json')
    if f['code_hashes'] != code_hashes(): raise RuntimeError('Research source changed after freeze')
    if f['config'] != CONFIG or f['methods'] != METHODS or f['gates'] != GATES:
        raise RuntimeError('Research settings changed after freeze')
