"""Synthetic evidence checks for constrained rates, phase and topology."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
import numpy as np

from fit_clock import clock_time
from tempo_prior import PriorConfig, refine_tempo_clock


def seed(times,x,knots=()):
    from fit_clock import design_matrix
    co=np.linalg.lstsq(design_matrix(x,knots),times,rcond=None)[0]
    return {'accepted':False,'knot_pulse_indices':list(knots),'coefficients':co.tolist()}


class TempoPriorTests(unittest.TestCase):
    def test_integer_rate_reduces_noise_drift_with_refitted_phase(self):
        x=np.arange(100,dtype=float)
        truth=2.+x*60/79
        observed=truth+.009*np.sin(x*1.7)+.00013*(x-x.mean())
        original=seed(observed,x)
        result=refine_tempo_clock(observed,x,original)
        self.assertEqual(result['rate_constraints_bpm'],[79.])
        self.assertLess(np.max(abs(clock_time(x,[],result['coefficients'])-truth)),.002)
        self.assertFalse(result['accepted']);self.assertFalse(result['reference_used_for_prediction'])

    def test_supported_half_rate_is_not_replaced_by_integer(self):
        x=np.arange(220,dtype=float);times=4+x*60/79.5+.006*np.sin(x)
        result=refine_tempo_clock(times,x,seed(times,x))
        self.assertEqual(result['rate_constraints_bpm'],[79.5])

    def test_real_fractional_rate_survives_long_span_without_false_changes(self):
        x=np.arange(601,dtype=float);truth=1.+x*60/120.2
        observed=truth+.008*np.sin(x*1.41)
        result=refine_tempo_clock(observed,x,seed(observed,x))
        self.assertEqual(result['rate_constraints_bpm'],[None])
        self.assertEqual(result['knot_pulse_indices'],[])
        self.assertLess(max(abs(clock_time(x,[],result['coefficients'])-truth)),.001)

    def test_phase_and_existing_boundaries_refit_together(self):
        x=np.arange(150,dtype=float);periods=np.array([.6,60/110,60/115])
        truth=clock_time(x,[40,90],np.r_[1.2,periods[0],np.diff(periods)])
        observed=truth+.001*np.sin(x*1.2)
        initial=seed(observed,x,[41.5,88.5]);saved=deepcopy(initial)
        result=refine_tempo_clock(observed,x,initial)
        self.assertEqual(result['rate_constraints_bpm'],[100.,110.,115.])
        np.testing.assert_allclose(result['knot_pulse_indices'],[40,90],atol=.02)
        self.assertLess(max(abs(clock_time(x,result['knot_pulse_indices'],result['coefficients'])-truth)),.001)
        self.assertEqual(initial,saved)
        self.assertEqual(result['diagnostics']['new_changes_added'],0)

    def test_zero_strength_is_unrestricted_control(self):
        x=np.arange(100,dtype=float);times=1+x*60/78.972
        result=refine_tempo_clock(times,x,seed(times,x),PriorConfig(strength=0))
        self.assertEqual(result['rate_constraints_bpm'],[None])
        self.assertLess(max(abs(clock_time(x,[],result['coefficients'])-times)),1e-9)

    def test_multiple_model_observations_can_share_index(self):
        x=np.repeat(np.arange(80,dtype=float),2)
        times=1+x*.5+np.tile([-.004,.004],80)
        result=refine_tempo_clock(times,x,seed(times,x))
        self.assertEqual(result['rate_constraints_bpm'],[120.])
        self.assertAlmostEqual(result['coefficients'][0],1.)

    def test_accepted_anchored_and_invalid_inputs_are_rejected(self):
        x=np.arange(20,dtype=float);times=1+x*.5
        initial=seed(times,x)
        for key,value in [('accepted',True),('anchor_checks',[{}]),('locked_knots',[4.]),('assistance',{'anchors':[]})]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):refine_tempo_clock(times,x,{**initial,key:value})
        with self.assertRaises(ValueError):refine_tempo_clock(times,x[::-1],initial)
        with self.assertRaises(ValueError):refine_tempo_clock(times,x,initial,PriorConfig(strength=-1))
        with self.assertRaises(ValueError):refine_tempo_clock(times,x,initial,PriorConfig(strength=float('nan')))
        with self.assertRaises(ValueError):refine_tempo_clock(times,x,initial,PriorConfig(max_iterations=1.5))

    def test_prior_assembly_is_opt_in_and_does_not_mutate_inputs(self):
        from test_complete_song_clock import conditional_fixture
        from complete_song_clock import assemble_clock
        regions,observations,logits,_=conditional_fixture()
        original=deepcopy(regions)
        baseline=assemble_clock(regions,observations,logits,55.)
        result=assemble_clock(regions,observations,logits,55.,tempo_prior_config=PriorConfig())
        self.assertFalse(result['reference_used_for_prediction'])
        self.assertFalse(result['bridge_certified']);self.assertFalse(result['accepted'])
        self.assertIn('tempo_prior',result);self.assertNotIn('tempo_prior',baseline)
        self.assertEqual(regions,original)
        self.assertEqual(baseline,assemble_clock(regions,observations,logits,55.))

    def test_iteration_counts_require_actual_integers(self):
        x = np.arange(12, dtype=float); times = 1 + x * .5; initial = seed(times, x)
        for name in ('max_iterations', 'coordinate_passes'):
            for value in (2.0, True, np.bool_(True), float('nan')):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    refine_tempo_clock(times, x, initial, replace(PriorConfig(), **{name: value}))

    def test_numpy_integer_counts_preserve_valid_result_and_serialization(self):
        x = np.arange(12, dtype=float); times = 1 + x * .5; initial = seed(times, x)
        config = PriorConfig(max_iterations=np.int64(2), coordinate_passes=np.int64(1))
        result = refine_tempo_clock(times, x, initial, config)
        self.assertEqual(result, refine_tempo_clock(times, x, initial,
                                                   PriorConfig(max_iterations=2, coordinate_passes=1)))
        json.dumps(result, allow_nan=False)
        self.assertIsInstance(config.max_iterations, np.integer)


if __name__=='__main__':unittest.main()
