from copy import deepcopy
import unittest
import numpy as np
from joint_guide_controls import guided_candidate_selection,grouping_observation_contrast


def clock(name,rate,score=1.,segments=None):
    segments=segments or [(0.,10.,rate)]
    return {'id':name,'evidence_score_not_confidence':score,'quarter_unit':'hypothesis',
        'musical_index_origin':'candidate_relative_unanchored','meter':None,
        'clock':{'support_seconds':[segments[0][0],segments[-1][1]],'segments':[
            {'start_seconds':a,'end_seconds':b,'pulse_rate_per_minute':r} for a,b,r in segments]}}


def window(lo=1.,hi=3.):
    return {'status':'found','start_seconds':lo,'end_seconds':hi,'source_support_seconds':[lo,hi],
            'event_times_seconds':np.linspace(lo,hi,8).tolist(),'event_indices':[2,10],
            'stable_period_seconds':(hi-lo)/7,'trace':{'source_only':True}}


class JointGuideControlTests(unittest.TestCase):
    def test_half_and_full_native_rates_can_both_satisfy_scalar_without_quarter_claim(self):
        candidates=[clock('native85',85.,5.),clock('native170',170.,5.)];before=deepcopy(candidates)
        result=guided_candidate_selection(candidates,170.,window())
        self.assertEqual(result['selected_candidate_id'],result['legacy_best_candidate_id'])
        self.assertEqual(set(result['tied_selected_candidate_ids']),{'native85','native170'})
        rows=result['candidate_rows']
        self.assertEqual(rows[0]['tied_best_native_to_tap_ratios'],[{'numerator':2,'denominator':1}])
        self.assertEqual(rows[1]['tied_best_native_to_tap_ratios'],[{'numerator':1,'denominator':1}])
        self.assertEqual(rows[0]['guide_penalty'],0.)
        self.assertFalse(result['quarter_unit_assigned']);self.assertFalse(result['meter_inferred'])
        self.assertFalse(result['full_music_map_available']);self.assertEqual(candidates,before)

    def test_guide_only_applies_to_first_window_and_does_not_flatten_later_change(self):
        a=clock('constant',80.)
        b=clock('later_change',80.,segments=[(0.,5.,80.),(5.,10.,133.)])
        original=deepcopy(b)
        result=guided_candidate_selection([a,b],160.,window())
        self.assertEqual(len(result['tied_selected_candidate_ids']),2)
        self.assertTrue(all(r['guide_penalty']==0. for r in result['candidate_rows']))
        self.assertEqual(b,original)
        self.assertEqual(b['clock']['segments'][1]['pulse_rate_per_minute'],133.)

    def test_one_ratio_must_explain_entire_window_not_a_new_ratio_per_segment(self):
        changing=clock('changing',85.,segments=[(0.,2.,85.),(2.,4.,170.)])
        steady=clock('steady_mean',127.5,segments=[(0.,4.,127.5)])
        result=guided_candidate_selection([changing,steady],170.,window(0.,4.))
        self.assertEqual(result['candidate_rows'][0]['guide_window_time_weighted_native_rate'],127.5)
        self.assertLess(result['candidate_rows'][0]['guide_penalty'],0.)
        self.assertAlmostEqual(result['candidate_rows'][1]['guide_penalty'],0.)
        self.assertEqual(result['selected_candidate_id'],'steady_mean')

    def test_window_coverage_cannot_be_skipped_or_filled_across_a_gap(self):
        prefix=clock('short',100.,segments=[(0.,1.99,100.)])
        gap=clock('gap',100.,segments=[(0.,1.,100.),(1.001,4.,100.)])
        result=guided_candidate_selection([prefix,gap],100.,window(0.,2.))
        self.assertEqual(result['status'],'no_candidate_covers_guide_window')
        self.assertIsNone(result['selected_candidate_id'])
        self.assertTrue(all(r['status']=='guide_window_not_fully_supported' for r in result['candidate_rows']))

    def test_explicit_region_support_limits_a_longer_clock(self):
        a=clock('region',100.);a['source_support_seconds']=[2.,4.]
        result=guided_candidate_selection([a],100.,window(1.,3.))
        self.assertEqual(result['candidate_rows'][0]['status'],'guide_window_not_fully_supported')

    def test_missing_window_and_empty_pool_remain_explicit(self):
        result=guided_candidate_selection([clock('a',100.)],100.,{'status':'guide_window_unresolved'})
        self.assertEqual(result['status'],'guide_window_unresolved')
        self.assertIsNone(result['selected_candidate_id'])
        self.assertEqual(guided_candidate_selection([],100.,window())['status'],'empty_candidate_pool')

    def test_invalid_candidate_stays_in_report_without_blocking_valid_candidate(self):
        bad=clock('bad',0.);good=clock('good',100.)
        result=guided_candidate_selection([bad,good],100.,window())
        self.assertEqual(result['candidate_rows'][0]['status'],'invalid_candidate_declaration')
        self.assertEqual(result['selected_candidate_id'],'good')
        self.assertEqual(len(result['candidate_rows']),2)

    def test_guide_payload_is_only_a_positive_scalar(self):
        for value in [{'bpm':160,'unit':'eighth'},[160,6,8],True,float('nan'),float('inf'),0,-1]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                guided_candidate_selection([clock('a',80.)],value,window())
        with self.assertRaises(TypeError):guided_candidate_selection([clock('a',80.)],160,window(),meter=(6,8))

    def test_legacy_score_is_preserved_and_added_without_normalization(self):
        result=guided_candidate_selection([clock('a',80.,10.),clock('b',80.,12.)],160.,window())
        self.assertEqual(result['selected_candidate_id'],'b')
        self.assertEqual([r['total_score_not_confidence'] for r in result['candidate_rows']],[10.,12.])

    def test_fixed_primary_contrast_is_sensitive_to_actual_group_positions(self):
        beat=np.full(301,-6.);down=np.full(301,-6.)
        beat[0]=beat[100]=beat[200]=6.;down[0]=6.
        result=grouping_observation_contrast(beat,down,100.,[[0.,3.]])
        row=result['rows'][0]
        self.assertEqual(row['hypotheses']['3/4']['beat_score'],18.)
        self.assertEqual(row['hypotheses']['6/8']['beat_score'],0.)
        self.assertEqual(row['acoustic_score_difference_3_4_minus_6_8'],18.)
        self.assertFalse(result['all_acoustic_scores_tied'])

    def test_free_role_identical_masks_cannot_reveal_meter(self):
        beat=np.arange(301,dtype=float)/100-2.;down=np.cos(np.arange(301,dtype=float))
        result=grouping_observation_contrast(beat,down,100.,[[0.,3.]],shared_primary_phases=[0.,.5])
        self.assertTrue(result['all_acoustic_scores_tied'])
        self.assertEqual(result['rows'][0]['acoustic_score_difference_3_4_minus_6_8'],0.)
        self.assertFalse(result['reference_used']);self.assertFalse(result['guide_used'])

    def test_native_half_frame_ties_match_lattice_positive_half_up(self):
        beat=np.arange(50,dtype=float);down=np.zeros(50)
        # Rebuilding seconds naively gives14.499999..., although half of29
        # native frames is exactly14.5. Match the lattice integer geometry.
        result=grouping_observation_contrast(beat,down,50.,[[0.,29/50]],shared_primary_phases=[.5])
        self.assertEqual(result['rows'][0]['hypotheses']['3/4']['native_frame_indices'],[15])
        self.assertEqual(result['rows'][0]['hypotheses']['3/4']['beat_score'],15.)
        with self.assertRaises(ValueError):
            grouping_observation_contrast(beat,down,50.,[[.005,.585]],shared_primary_phases=[.5])

    def test_negative_initial_context_censors_samples_without_moving_bar(self):
        beat=np.arange(31,dtype=float);down=np.ones(31)
        result=grouping_observation_contrast(beat,down,10.,[[-.5,2.5]],shared_primary_phases=[0.,.5])
        row=result['rows'][0]
        self.assertEqual(row['inferred_bar_frames'],[-5,25])
        values=row['hypotheses']['6/8']
        self.assertEqual(values['native_frame_indices'],[10])
        self.assertEqual(values['censored_pre_source_primary_count'],1)
        self.assertTrue(values['downbeat_pre_source_censored'])
        self.assertEqual(values['total_score_not_confidence'],10.)
        self.assertTrue(result['all_acoustic_scores_tied'])

    def test_empty_geometry_is_unavailable_not_an_ambiguity_proof(self):
        result=grouping_observation_contrast(np.zeros(10),np.zeros(10),50.,[])
        self.assertEqual(result['status'],'no_inferred_bar_geometry')
        self.assertIsNone(result['all_acoustic_scores_tied'])


if __name__=='__main__':unittest.main()
