import unittest
import json
from dataclasses import replace
import numpy as np

from fit_clock import clock_time
from fit_clock_v2 import FitConfig, fit_clock_v2


def events(rates, lengths, start=.37):
    return np.r_[start, start+np.cumsum(np.concatenate([np.full(n,60/r) for r,n in zip(rates,lengths)]))]


class ContinuousClockV2Tests(unittest.TestCase):
    def test_two_and_three_pulse_excursions_keep_exact_continuous_boundaries(self):
        truth = events([110,111.1,113.1,117.1], [40,2,3,40])
        result = fit_clock_v2(truth)
        self.assertEqual(result['knot_pulse_indices'], [40.,42.,45.])
        np.testing.assert_allclose([s['pulse_rate_per_minute'] for s in result['segments']],
                                   [110,111.1,113.1,117.1], atol=1e-7)
        np.testing.assert_allclose(clock_time(np.arange(len(truth)),result['knot_pulse_indices'],result['coefficients']),truth,atol=1e-9)

    def test_noise_does_not_create_changes_in_constant_control(self):
        truth = events([137.3],[180])
        for seed in (34,35,36):
            observed = truth+np.random.default_rng(seed).normal(0,.004,len(truth))
            result = fit_clock_v2(observed)
            self.assertEqual(result['knot_pulse_indices'], [])
            fitted = clock_time(np.arange(len(truth)),[],result['coefficients'])
            self.assertLess(np.max(abs(fitted-truth)), .004)

    def test_nonconsecutive_indices_and_locked_anchors_preserve_source_coordinates(self):
        truth=events([103],[60],start=2.31); keep=np.ones(len(truth),dtype=bool);keep[10:14]=False
        x=np.arange(len(truth),dtype=float)[keep]; original=truth.copy()
        anchors=[{'quarter_position':5.,'source_seconds':float(truth[5])},
                 {'quarter_position':45.,'source_seconds':float(truth[45])}]
        result=fit_clock_v2(truth[keep],x,anchors=anchors)
        for anchor in result['anchor_checks']:self.assertLess(anchor['absolute_error_seconds'],1e-9)
        self.assertEqual(result['source_origin_seconds'],0)
        np.testing.assert_array_equal(truth,original)
        self.assertFalse(result['accepted'])
        with self.assertRaises(ValueError):
            fit_clock_v2(truth,anchors=[{'quarter_position':2.,'source_seconds':4.},
                                       {'quarter_position':3.,'source_seconds':3.}])

    def test_frame_quantization_with_sparse_jitter_does_not_look_noise_free(self):
        truth=events([120],[180],start=0.)
        observed=np.rint((truth+np.random.default_rng(43).normal(0,.004,len(truth)))*50)/50
        result=fit_clock_v2(observed,config=FitConfig(observation_quantization_seconds=.02))
        self.assertEqual(result['knot_pulse_indices'],[])
        self.assertGreaterEqual(result['diagnostics']['noise_estimate_seconds'],.02/np.sqrt(12))

    def test_change_between_observed_quarters_is_not_rounded_to_a_quarter(self):
        x=np.arange(90,dtype=float);knot=40.35
        truth=1+x*(60/110)+np.maximum(0,x-knot)*(60/116-60/110)
        result=fit_clock_v2(truth)
        self.assertEqual(len(result['knot_pulse_indices']),1)
        self.assertLess(abs(result['knot_pulse_indices'][0]-knot),.002)

    def test_invalid_configuration_is_rejected_before_fitting(self):
        truth = events([120], [12])
        invalid = [('max_events', 3), ('max_events', True), ('max_knots', -1), ('max_knots', 2.0),
                   ('candidate_limit', 0), ('candidate_limit', float('nan')), ('refinement_passes', -1),
                   ('refinement_passes', 1.0), ('pair_pool_size', False), ('pair_pool_size', -1),
                   ('noise_floor_seconds', 0), ('noise_floor_seconds', -1),
                   ('noise_floor_seconds', float('inf')), ('observation_quantization_seconds', -.02),
                   ('complexity_factor', float('nan')), ('complexity_factor', -1)]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                fit_clock_v2(truth, config=replace(FitConfig(), **{key: value}))

    def test_numpy_integer_configuration_matches_python_integer_control(self):
        truth = events([120], [12])
        config = FitConfig(max_events=np.int64(20), max_knots=np.int64(0), candidate_limit=np.int64(8),
                           refinement_passes=np.int64(0), pair_pool_size=np.int64(0))
        control = FitConfig(max_events=20, max_knots=0, candidate_limit=8, refinement_passes=0, pair_pool_size=0)
        result = fit_clock_v2(truth, config=config)
        self.assertEqual(result, fit_clock_v2(truth, config=control))
        json.dumps(result, allow_nan=False)
        self.assertIsInstance(config.max_events, np.integer)


if __name__=='__main__':unittest.main()
