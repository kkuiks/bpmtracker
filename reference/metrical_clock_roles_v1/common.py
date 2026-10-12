"""Frozen source/evaluation boundaries and shared research settings."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIOR = ROOT / 'data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1'
FOCUS = ['r002', 'r008', 'r010']
CONFIG = {
    'step': .25, 'beat_sigma_seconds': .025, 'downbeat_sigma_seconds': .035,
    'role_periods_in_quarters': [.5, 2/3, 1., 1.5, 2., 3., 4.],
    'bar_periods_in_quarters': [2., 3., 4., 5., 6., 7., 8., 12.],
    'meter_quarters': [2., 3., 4., 5., 6., 7., 8.],
    'downbeat_observation_roles': [.5, 1., 2.],
    'unit_multipliers': [.25, 1/3, .5, 2/3, 1., 1.5, 2., 3., 4.],
    'initial_deadline_seconds': 30., 'initial_scope_seconds': 8.,
    'role_window_seconds': 8., 'bar_window_seconds': 16.,
    'source_candidate_budget': 1536, 'state_budget': 4096,
    'minimum_source_quality': .55, 'minimum_events': 5,
    'downbeat_weight': .20, 'role_prior_cost': .035,
    'tempo_change_cost': 1.25, 'role_change_cost': .25,
    'meter_change_cost': 4., 'downbeat_role_change_cost': .25,
    'initial_meter_prior': 4., 'phase_change_cost': .8,
    'rate_distance_cost': .5, 'beam': 128, 'destination_count': 48,
    'tap_error_fraction': .03,
    'gauge_change_guard': True, 'minimum_bar_gain_for_gauge_change': .30,
}
METHODS = {
    'R0_QUARTER_ONLY': {'roles': False, 'bars': False},
    'R1_ROLES': {'roles': True, 'bars': False},
    'R2_ROLES_BARS': {'roles': True, 'bars': True},
    'R3_NO_ROLE_PRIOR': {'roles': True, 'bars': True, 'role_prior_cost': 0.},
    'R4_LOW_CHANGE_COST': {'roles': True, 'bars': True, 'tempo_change_cost': .625},
    'R5_HIGH_CHANGE_COST': {'roles': True, 'bars': True, 'tempo_change_cost': 2.5},
    'R6_WIDE_SEARCH': {'roles': True, 'bars': True, 'beam': 256, 'destination_count': 96},
    'R7_PHASE_BOUNDARIES': {'roles': True, 'bars': True, 'refine_boundaries': True},
    'R8_ALLOW_SUBBAR': {'roles': True, 'bars': True, 'allow_subbar': True},
    'R9_LOW_METER_COST': {'roles': True, 'bars': True, 'meter_change_cost': .15},
    'R10_WEAK_INITIAL_METER': {'roles': True, 'bars': True, 'initial_meter_prior': .10},
    'R11_NO_GAUGE_GUARD': {'roles': True, 'bars': True, 'gauge_change_guard': False},
}
CRITERIA = {
    'primary_method': 'R2_ROLES_BARS', 'primary_policy': 'proxy100',
    'focus_octave_correct_gain_min': .05,
    'focus_quarter_f1_max_loss': .02,
    'focus_underoath_correct_min': .95, 'focus_underoath_f1_min': .98,
    'focus_underoath_unmatched_rate_seconds_max': 1.,
    'focus_underoath_boundary_tolerance_seconds': 5.,
    'focus_cases_improved_required': 2,
    'broad_correct_gain_min': .05, 'broad_octave_error_reduction_min': .10,
    'broad_control_wrong_increase_max': .03,
    'broad_songs_correct_85_required': 6,
    'boundary_tolerances_seconds': [2., 4., 8.],
    'event_tolerances_seconds': [.02, .03, .07],
    'no_single_score_is_project_abandonment_rule': True,
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
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def stamp(): return datetime.now(timezone.utc).isoformat()

def code_hashes():
    files = list(Path(__file__).parent.glob('*.py'))
    files += [ROOT/'experiments/variable_clock_composition_v1/proposals.py',
              ROOT/'experiments/variable_clock_composition_v1/evaluate.py',
              ROOT/'experiments/variable_clock_composition_v1/common.py',
              ROOT/'experiments/variable_tempo_interval_consensus_v0/core.py',
              ROOT/'experiments/metronome_reconstruction_v1/grid.py',
              ROOT/'experiments/metronome_benchmark_v1/metrics.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}

def guard(run):
    f = read(Path(run)/'freeze.json')
    if f['code_hashes'] != code_hashes() or f['config'] != CONFIG or f['methods'] != METHODS:
        raise RuntimeError('Frozen implementation/settings changed')
    if f['criteria'] != CRITERIA: raise RuntimeError('Frozen criteria changed')
