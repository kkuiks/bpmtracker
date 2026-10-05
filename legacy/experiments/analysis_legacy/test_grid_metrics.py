import unittest
import math
from grid_metrics import (indexed_grid_metrics, nearest_event_diagnostics,
    tempo_change_metrics, meter_change_metrics, temporal_span_coverage,
    pulse_level_diagnostics, within_tolerance)


class GridMetricsTests(unittest.TestCase):
    def test_correct_rate_wrong_phase_is_not_aligned_away(self):
        ref=[{'index':i,'time_seconds':i*.5} for i in range(12)]
        pred=[{'index':i,'time_seconds':i*.5+.15} for i in range(12)]
        result=indexed_grid_metrics(ref,pred,origin_status='shared_explicit_origin')
        self.assertAlmostEqual(result['grid_errors']['absolute_p95_seconds'],.15)
        self.assertAlmostEqual(result['grid_errors']['last_minus_first_error_seconds'],0)
        self.assertEqual(result['index_and_time_scores']['f1'],0)
        self.assertEqual(temporal_span_coverage([i*.5 for i in range(12)],0,6)['fraction'],1)

    def test_unanchored_indices_cannot_be_compared(self):
        result=indexed_grid_metrics([{'index':0,'time_seconds':1}], [{'index':0,'time_seconds':2}])
        self.assertEqual(result['status'],'unanchored')
        self.assertIsNone(result['grid_errors'])

    def test_missing_index_does_not_renumber_remaining_beats(self):
        ref=[{'index':i,'time_seconds':float(i)} for i in range(5)]
        pred=[e for e in ref if e['index']!=2]
        result=indexed_grid_metrics(ref,pred,origin_status='shared_explicit_origin')
        self.assertEqual(result['missing_indices'],[2])
        self.assertEqual(result['grid_errors']['absolute_max_seconds'],0)
        self.assertEqual(result['index_and_time_scores']['false_negatives'],1)

    def test_same_boundary_wrong_rate_and_direction_fail(self):
        ref=[{'source_seconds':10,'bpm_before':100,'bpm_after':101,'type':'step'}]
        pred=[{'source_seconds':10.01,'bpm_before':100,'bpm_after':99,'type':'step'}]
        result=tempo_change_metrics(ref,pred)
        self.assertEqual(result['timing_only_match_count'],1)
        self.assertEqual(result['full_change_scores']['true_positives'],0)

    def test_unknown_and_empty_meter_are_distinct(self):
        self.assertEqual(meter_change_metrics(None,[])['status'],'unscored_missing_reference')
        pred=[{'source_seconds':2,'numerator':3,'denominator':4}]
        self.assertEqual(meter_change_metrics([],pred)['false_positives'],1)
        self.assertEqual(meter_change_metrics(pred,None)['status'],'unresolved_prediction')

    def test_small_opposite_change_cannot_hide_inside_rate_tolerance(self):
        ref=[{'source_seconds':10,'bpm_before':100,'bpm_after':100.01,'type':'step'}]
        pred=[{'source_seconds':10,'bpm_before':100,'bpm_after':99.99,'type':'step'}]
        self.assertEqual(tempo_change_metrics(ref,pred)['full_change_scores']['true_positives'],0)

    def test_matching_is_one_to_one_and_density_exposes_half_level(self):
        ref=[0.,1.,2.,3.,4.]; pred=[0.,2.,4.]
        self.assertEqual(nearest_event_diagnostics(ref,pred)['true_positives'],3)
        self.assertEqual(pulse_level_diagnostics(ref,pred)['empty_interval_fraction'],.5)

    def test_multiple_declared_tolerances_do_not_shift_predictions(self):
        ref=[0.,1.,2.]; pred=[.015,1.015,2.015]
        self.assertEqual(nearest_event_diagnostics(ref,pred,.01)['true_positives'],0)
        self.assertEqual(nearest_event_diagnostics(ref,pred,.02)['true_positives'],3)
        self.assertEqual(nearest_event_diagnostics(ref,pred,.03)['true_positives'],3)
        self.assertEqual(nearest_event_diagnostics(ref,pred,.07)['true_positives'],3)

    def test_exact_numeric_boundaries_are_inclusive_for_events_and_indices(self):
        for tolerance in (.01,.02,.03,.07):
            for sign in (-1,1):
                predicted=1.+sign*tolerance
                nearest=nearest_event_diagnostics([1.],[predicted],tolerance)
                indexed=indexed_grid_metrics([{'index':4,'time_seconds':1.}],
                    [{'index':4,'time_seconds':predicted}],origin_status='shared_explicit_origin',time_tolerance_seconds=tolerance)
                self.assertEqual(nearest['true_positives'],1)
                self.assertEqual(indexed['index_and_time_scores']['true_positives'],1)
                self.assertEqual(nearest['matched_event_errors']['signed_median_seconds'],predicted-1.)

    def test_real_twenty_point_zero_zero_one_ms_error_is_not_admitted(self):
        for predicted in (1.020001,.979999):
            self.assertFalse(within_tolerance(1.,predicted,.02))
            self.assertEqual(nearest_event_diagnostics([1.],[predicted],.02)['true_positives'],0)
            result=indexed_grid_metrics([{'index':0,'time_seconds':1.}],
                [{'index':0,'time_seconds':predicted}],origin_status='shared_explicit_origin')
            self.assertEqual(result['index_and_time_scores']['true_positives'],0)

    def test_boundary_handling_preserves_one_to_one_counts_and_musical_origin_gate(self):
        score=nearest_event_diagnostics([1.,2.],[.98,1.02,2.02],.02)
        self.assertEqual((score['true_positives'],score['false_positives'],score['false_negatives']),(2,1,0))
        indexed=indexed_grid_metrics([{'index':0,'time_seconds':1.}],[{'index':1,'time_seconds':1.02}],origin_status='shared_explicit_origin')
        self.assertEqual(indexed['index_and_time_scores']['true_positives'],0)
        self.assertEqual(indexed['missing_indices'],[0.])
        self.assertEqual(indexed_grid_metrics([{'index':0,'time_seconds':1.}],[{'index':0,'time_seconds':1.02}])['status'],'unanchored')

    def test_tempo_boundary_requires_time_type_direction_and_both_rates(self):
        ref=[{'source_seconds':1.,'bpm_before':128.,'bpm_after':256.,'type':'step'}]
        for sign in (-1,1):
            pred=[{'source_seconds':1.+sign*.1,'bpm_before':128.+sign*.1,'bpm_after':256.+sign*.1,'type':'step'}]
            score=tempo_change_metrics(ref,pred,time_tolerance_seconds=.1,rate_tolerance_bpm=.1)
            self.assertEqual(score['full_change_scores']['true_positives'],1)
        for field,excess in [('source_seconds',1.100001),('bpm_before',128.100001),('bpm_after',256.100001)]:
            pred=[{**ref[0],field:excess}]
            self.assertEqual(tempo_change_metrics(ref,pred)['full_change_scores']['true_positives'],0)

    def test_meter_boundary_is_numeric_only_and_does_not_relax_signature(self):
        ref=[{'source_seconds':1.,'numerator':3,'denominator':4}]
        for time in (.9,1.1):
            self.assertEqual(meter_change_metrics(ref,[{**ref[0],'source_seconds':time}])['true_positives'],1)
        self.assertEqual(meter_change_metrics(ref,[{**ref[0],'source_seconds':1.100001}])['true_positives'],0)
        self.assertEqual(meter_change_metrics(ref,[{'source_seconds':1.1,'numerator':6,'denominator':8}])['true_positives'],0)

    def test_negative_zero_large_origin_and_nonfinite_inputs(self):
        self.assertTrue(within_tolerance(-0.,0.,-0.))
        self.assertEqual(nearest_event_diagnostics([-0.],[0.],0.)['true_positives'],1)
        origin=1_000_000.
        self.assertTrue(within_tolerance(origin,origin+.02,.02))
        self.assertFalse(within_tolerance(origin,origin+.020001,.02))
        for first,second,tol in [(math.nan,1.,.02),(1.,math.inf,.02),(1.,1.,math.inf),(1.,1.,-.001)]:
            with self.assertRaises(ValueError):within_tolerance(first,second,tol)

    def test_invalid_indices_are_rejected(self):
        with self.assertRaises(ValueError):
            indexed_grid_metrics([{'index':0,'time_seconds':0},{'index':0,'time_seconds':1}],[])


if __name__=='__main__':
    unittest.main()
