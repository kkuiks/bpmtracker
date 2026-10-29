"""Numerical search configuration."""

CONFIG = {
    'signatures': [[2,4],[3,4],[4,2],[4,4],[5,4],[6,4],[6,8],[7,4]],
    'bpm_domain': [30,400], 'rational_denominator': 4,
    'source_peak_floor': .20, 'source_run_sigma_seconds': .035,
    'source_run_bad_mass': 1.5, 'source_run_budget': 48,
    'source_minimum_fit_observations': 3, 'source_clock_budget': 512,
    'initial_information_mass': 4., 'initial_fit_quality': .8,
    'pulse_factors': [.5,1.,2.,2/3,4/3,1/3,1.5,.75],
    'initial_role_radius_log': .12, 'initial_candidate_budget': 96,
    'initial_role_merge_log': .08, 'initial_family_path_reserve': 2,
    'initial_path_budget': 8, 'map_path_budget': 4,
    'pending_path_budget': 2, 'evidence_candidate_reserve': 16,
    'extension_candidates': 48, 'max_declarations': 24,
    'maximum_stagnant_search_depths': 3,
    'proposal_phase_tolerance_seconds': .08,
    'neural_sigma_seconds': .025, 'pcm_sigma_seconds': .035,
    'beat_weight': .62, 'bar_weight': .28, 'pcm_weight': .10,
    'observation_role_cost': .018, 'offbeat_role_cost': .025,
    'tempo_change_cost': 1.2, 'meter_change_cost': 1.0,
    'octave_change_extra_cost': 3., 'octave_ratio_tolerance': .03,
    'gate_old_ceiling': .55, 'gate_new_floor': .65,
    'gate_improvement': .12, 'gate_minimum_source_mass': 2.,
    'meter_prior': {'4/4':0.,'3/4':.006,'6/8':.008,'2/4':.024,
                    '4/2':.04,'5/4':.016,'6/4':.026,'7/4':.018},
    'family_initial_prior': .04,
    'evidence_clutter_probability': .05,
}

METHODS = {
    'EVENT_SEARCH': {'gate':False,'role_mixture':False},
    'MISMATCH_GATE': {'gate':True,'role_mixture':False},
    'RHYTHM_ROLES': {'gate':True,'role_mixture':True},
    'SAME_UNIT_GATE': {'gate':True,'role_mixture':True,'unit_hold':True},
}
