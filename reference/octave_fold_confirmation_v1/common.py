from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIOR = ROOT / 'data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1'
CONFIG = {
    'primary_alias_tolerance': .05,
    'exact_folded_rate_tolerance': 1e-8,
    'minimum_folded_quality': .35,
    'minimum_folded_seed_count': 5,
    'maximum_nested_grid_phase_error_seconds': .07,
    'continuity_phase_weight': .15,
    'evaluation_alias_tolerance': .01,
    'small_true_change_max_relative': .05,
    'transition_context_seconds': 16.,
    'initial_proxy_ratios': [.97, 1., 1.03],
    'fallback': 'hold_previous_source_clock_without_muting',
}
METHODS = {
    'B0_RAW': {'mode': 'raw', 'tolerance': .05},
    'B1_VETO05': {'mode': 'veto', 'tolerance': .05},
    'F1_FOLD05': {'mode': 'fold', 'tolerance': .05},
    'S1_FOLD03': {'mode': 'fold', 'tolerance': .03},
    'S2_FOLD08': {'mode': 'fold', 'tolerance': .08},
}
GATES = {
    'primary_method': 'F1_FOLD05', 'primary_policy': 'proxy100',
    'variable_correct_clock_gain_min': .03,
    'variable_alias_error_relative_reduction_min': .25,
    'variable_click_f1_decline_max': .005,
    'control_correct_clock_decline_max': .01,
    'small_change_post_rate_decline_max': .01,
    'individual_variable_decline_max': .03,
    'genuine_octave_post_decline_max': .01,
    'component_direction_not_product_acceptance': True,
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    partial.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def code_hashes():
    own = list(Path(__file__).parent.glob('*.py'))
    prior = [ROOT / name for name in read(PRIOR / 'freeze.json')['code_hashes']]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(own + prior))}


def guard(run):
    frozen = read(Path(run) / 'freeze.json')
    if frozen['code_hashes'] != code_hashes():
        raise RuntimeError('Experiment code changed after freeze')
    if frozen['config'] != CONFIG or frozen['methods'] != METHODS or frozen['gates'] != GATES:
        raise RuntimeError('Experiment settings changed after freeze')
