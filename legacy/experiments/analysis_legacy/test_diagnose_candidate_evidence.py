from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
import numpy as np
from diagnose_candidate_evidence import (score_pool,event_scores,eligible_region_cache,
    probe_channel,file_record,verify_files,ulp_event_counts)


def candidate(name,times,support=None):
    return {'id':name,'indexed_grid':[{'source_seconds':t,'quarter_position':i} for i,t in enumerate(times)],
            'source_support_seconds':support or [times[0],times[-1]],'quarter_unit':'hypothesis',
            'musical_index_origin':'candidate_relative_unanchored','meter':None}


def pool(candidates,selected=None):
    return {'candidates':candidates,'selected_candidate_id':selected,'selection_status':'unaccepted_saved_selection'}


class CandidateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.reference={'evaluation_support_seconds':[0.,4.],'beats_seconds':[0.,1.,2.,3.,4.]}

    def test_automatic_choice_stays_distinct_from_finite_pool_oracle(self):
        candidates=[candidate('bad',[.2,1.2,2.2,3.2]),candidate('good',[0.,1.,2.,3.,4.])]
        result=score_pool(self.reference,pool(candidates,'bad'),5.,family='whole_source')
        self.assertEqual(result['automatic']['candidate_id'],'bad')
        self.assertEqual(result['automatic']['scores']['20ms']['f1'],0)
        oracle=result['oracle_diagnostic']
        self.assertTrue(oracle['reference_used_for_choice'])
        self.assertEqual(oracle['profiles']['20ms']['tied_best_candidate_ids'],['good'])
        self.assertEqual(oracle['profiles']['20ms']['gap_from_automatic'],1)
        self.assertIsNone(result['full_map_accuracy'])

    def test_missing_and_empty_pool_are_not_silently_dropped(self):
        missing=score_pool(self.reference,None,5.,family='whole_source')
        empty=score_pool(self.reference,pool([],None),5.,family='whole_source')
        self.assertEqual(missing['status'],'missing_pool')
        self.assertIsNone(missing['candidate_count'])
        self.assertEqual(empty['status'],'empty_pool')
        self.assertEqual(empty['automatic']['scores']['20ms']['false_negatives'],5)
        self.assertIsNone(empty['oracle_diagnostic']['profiles']['20ms']['best_f1'])

    def test_region_local_perfection_is_not_whole_song_perfection(self):
        result=score_pool(self.reference,pool([candidate('part',[1.,2.,3.],[1.,3.])],'part'),5.,family='partial_regions')
        row=result['candidate_rows'][0]
        self.assertEqual(row['within_proposed_support_diagnostic']['20ms']['f1'],1)
        self.assertLess(row['whole_annotation_diagnostic']['20ms']['f1'],1)
        self.assertEqual(row['reference_duration_fraction'],.5)
        self.assertTrue(result['partial_region_family'])

    def test_cache_requires_prediction_reference_evaluator_and_named_pool_binding(self):
        p=pool([candidate('a',[0.,1.,2.,3.,4.])],'a')
        score={'prediction_sha256':'p','reference':{'sha256':'r'},'scores':{'selected_candidate_id':'a',
            'candidate_scores':{'a':{'source_support_seconds':[0.,4.]}}}}
        self.assertTrue(eligible_region_cache(score,'p','r',p,True))
        self.assertFalse(eligible_region_cache(score,'changed','r',p,True))
        self.assertFalse(eligible_region_cache(score,'p','changed',p,True))
        self.assertFalse(eligible_region_cache(score,'p','r',p,False))
        changed=deepcopy(p);changed['candidates'][0]['source_support_seconds']=[1.,4.]
        self.assertFalse(eligible_region_cache(score,'p','r',changed,True))

    def test_reused_metrics_match_fresh_without_selecting_new_candidate(self):
        p=pool([candidate('a',[0.,1.,2.,3.,4.])],'a')
        metrics=event_scores(self.reference,[0.,1.,2.,3.,4.])
        wrapped={'event_'+k:v for k,v in metrics.items()}
        cached={'a':{'whole_annotation_diagnostic':wrapped,'within_proposed_region_diagnostic':wrapped}}
        fresh=score_pool(self.reference,p,5.,family='partial_regions')
        reused=score_pool(self.reference,p,5.,family='partial_regions',cached_scores=cached)
        self.assertEqual(fresh['automatic'],reused['automatic'])
        self.assertIn('reused_exact_bound_whole_scores_and_local_scores',reused['score_modes'])

    def test_rank_and_peak_distance_are_invariant_to_positive_affine_amplitude_change(self):
        values=np.zeros(101);values[50]=1.;values[52]=3.
        a=probe_channel(values,100.,[.5],source_duration=1.)['rows'][0]
        b=probe_channel(values*100-200,100.,[.5],source_duration=1.)['rows'][0]
        self.assertEqual(a['nearest_frame_window_rank'],2)
        self.assertEqual(a['nearest_frame_window_rank'],b['nearest_frame_window_rank'])
        self.assertAlmostEqual(a['window_maximum_error_seconds'],.02)
        self.assertEqual(a['native_local_peak_count'],2)
        self.assertEqual(a['window_maximum_error_seconds'],b['window_maximum_error_seconds'])

    def test_flat_window_has_rank_one_ties_but_no_local_peak(self):
        row=probe_channel(np.full(101,-100.),100.,[.5],source_duration=1.)['rows'][0]
        self.assertEqual(row['nearest_frame_window_rank'],1)
        self.assertEqual(row['nearest_frame_tied_value_count'],row['frame_count'])
        self.assertEqual(row['native_local_peak_count'],0)
        self.assertIsNone(row['nearest_local_peak_error_seconds'])
        self.assertFalse(row['window_maximum_is_native_local_peak'])

    def test_window_does_not_reach_outside_seventy_ms_or_physical_source(self):
        values=np.zeros(101);values[58]=10.;values[100]=20.;values[53]=1.
        row=probe_channel(values,100.,[.5],source_duration=1.)['rows'][0]
        self.assertEqual(row['window_maximum_frame_index'],53)
        self.assertAlmostEqual(row['window_maximum_error_seconds'],.03)
        end=probe_channel(values,100.,[1.],source_duration=1.)['rows'][0]
        self.assertLess(end['window_maximum_frame_index'],100)

    def test_decoded_absence_differs_from_unavailable_channel(self):
        result=probe_channel(np.zeros(101),100.,[.5],source_duration=1.,decoded={'official':[],'common_minimal':None})
        available=result['rows'][0]['decoded_event_availability']
        self.assertEqual(available['official']['status'],'available')
        self.assertFalse(available['official']['within70ms'])
        self.assertEqual(available['common_minimal']['status'],'unavailable')
        self.assertIsNone(result['summary']['decoded_event_availability']['common_minimal']['within70ms'])

    def test_exact_twenty_ms_decoded_boundary_is_inclusive_in_native_probe(self):
        result=probe_channel(np.zeros(201),100.,[1.],source_duration=2.,decoded={'official':[1.02]})
        self.assertTrue(result['rows'][0]['decoded_event_availability']['official']['within20ms'])
        farther=probe_channel(np.zeros(201),100.,[1.],source_duration=2.,decoded={'official':[1.020001]})
        self.assertFalse(farther['rows'][0]['decoded_event_availability']['official']['within20ms'])

    def test_seventy_ms_native_window_boundary_has_numerical_inclusivity(self):
        values=np.zeros(201);values[109]=5.
        result=probe_channel(values,100.,[1.02],source_duration=2.)
        self.assertEqual(result['rows'][0]['window_maximum_frame_index'],109)

    def test_raw_float_control_is_distinct_from_ulp_sensitivity(self):
        # The common evaluator may be repaired later; this preserves the exact
        # historical arithmetic counterexample without requiring a live defect.
        self.assertFalse(abs(1.02-1.)<=.02)
        self.assertEqual(ulp_event_counts([1.],[1.02],.02)['true_positives'],1)
        self.assertEqual(ulp_event_counts([1.],[1.020001],.02)['true_positives'],0)

    def test_frozen_file_presence_and_bytes_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input';p.write_text('frozen');record=file_record(p)
            verify_files([record]);p.write_text('changed')
            with self.assertRaises(ValueError):verify_files([record])
            missing=file_record(Path(directory)/'missing');Path(missing['path']).write_text('appeared')
            with self.assertRaises(ValueError):verify_files([missing])

    def test_invalid_native_channels_rejected(self):
        for values,fps in [(np.array([]),50.),(np.array([np.nan]),50.),(np.zeros((2,2)),50.),(np.zeros(10),0.)]:
            with self.subTest(values=values,fps=fps),self.assertRaises(ValueError):
                probe_channel(values,fps,[.5],source_duration=1.)


if __name__=='__main__':unittest.main()
