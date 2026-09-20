import unittest
from grid_metrics import (indexed_grid_metrics, nearest_event_diagnostics,
    tempo_change_metrics, meter_change_metrics, temporal_span_coverage,
    pulse_level_diagnostics)


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

    def test_invalid_indices_are_rejected(self):
        with self.assertRaises(ValueError):
            indexed_grid_metrics([{'index':0,'time_seconds':0},{'index':0,'time_seconds':1}],[])


if __name__=='__main__':
    unittest.main()
