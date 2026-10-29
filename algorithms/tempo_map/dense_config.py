"""Numerical search configuration."""

from .search_config import CONFIG as BASE_CONFIG

CONFIG = {
    'base_config': BASE_CONFIG,
    'bar_score': 'symmetric source observation / predicted grid F1',
    'pcm_period': 'quarter period, independent of signature denominator',
    'minimum_proposal_pulse_density': BASE_CONFIG['initial_fit_quality'],
}

METHODS = {
    'GRID_BALANCE': {'dense_proposals': False},
    'DENSE_PROPOSALS': {'dense_proposals': True},
}
