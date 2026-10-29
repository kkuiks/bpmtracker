"""Numerical search configuration."""

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
