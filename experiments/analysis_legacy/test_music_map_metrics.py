"""Independent closed-form and adversarial examples for component diagnostics."""
from copy import deepcopy
from fractions import Fraction
import math
import unittest

from music_map_metrics import evaluate_music_maps

QUALIFIED = {'bar_timing': True, 'clock_timing': True, 'meter': True, 'grouping': True}


def constant_map(n=4, d=4, *, bpm=120, unit=Fraction(1), grouping=None, duration=8., shift=0.):
    """Input constructor only; expected test values are independently derived."""
    quarters = Fraction(n * 4, d); pulse_bar = quarters / unit
    positions = (-pulse_bar, pulse_bar * 1000)
    frames = round(duration * 48000); duration = frames / 48000
    return {'schema_version': 1,
        'source': {'sha256': '0'*64, 'sample_rate': 48000, 'sample_frames': frames},
        'clock_knots': [{'pulse': float(p), 'source_seconds': float(p * unit * 60 / bpm) + shift} for p in positions],
        'quarters_per_pulse': {'numerator': unit.numerator, 'denominator': unit.denominator},
        'meter_events': [{'pulse': float(positions[0]), 'numerator': n, 'denominator': d,
                          'grouping': grouping, 'bar_action': 'continue'}],
        'bar_anchor_pulse': 0., 'shared_origin_id': None,
        'support_seconds': [[0., duration]], 'analysis_condition': 'constructed_fixture'}


def compare(ref, pred, **kwargs):
    return evaluate_music_maps(ref, pred, reference_qualification=kwargs.pop('qualification', QUALIFIED), **kwargs)


def profile(result, tolerance=.02):
    return next(p for p in result['timing_profiles'] if p['tolerance_seconds'] == tolerance)


class MusicMapMetricTests(unittest.TestCase):
    def test_identity_with_unknown_grouping_preserves_assessable_components(self):
        ref = constant_map(); before = deepcopy(ref)
        result = compare(ref, deepcopy(ref)); p = profile(result)
        self.assertEqual(p['bar_boundaries']['scores']['f1'], 1)
        self.assertEqual(p['paired_bars']['count'], 4)
        self.assertEqual(p['paired_bars']['continuous_timing_summary']['absolute_max_seconds'], 0)
        self.assertEqual(result['coverage']['prediction_source_fraction'], 1)
        self.assertFalse(result['declared_notation_comparison']['known_notation_disagreement'])
        self.assertIn('unassessable_missing_grouping', result['declared_notation_comparison']['grouping_relation_counts'])
        self.assertIsNone(result['overall_product_pass'])
        self.assertEqual(ref, before)

    def test_reviewed_a_allows_density_difference_without_grouping_requirement(self):
        ref = constant_map(bpm=85); pred = constant_map(8, 4, bpm=170)
        result = compare(ref, pred); p = profile(result)
        self.assertEqual(p['bar_boundaries']['scores']['f1'], 1)
        self.assertAlmostEqual(p['paired_bars']['continuous_timing_summary']['absolute_max_seconds'], 0)
        relations = [row['notation_relation'] for row in p['paired_bars']['comparisons']]
        self.assertTrue(relations)
        self.assertEqual(set(relations), {'reviewed_4_4_8_4_allowance_requires_bar_correspondence'})
        self.assertEqual(result['canonical_quarter_metric'], 'separate_existing_diagnostic_not_replaced')

    def test_reviewed_a_reports_grouping_difference_without_vetoing_allowance(self):
        ref = constant_map(bpm=85, grouping=[1,1,1,1]); pred = constant_map(8,4,bpm=170,grouping=[3,3,2])
        result = compare(ref, pred); row = profile(result)['paired_bars']['comparisons'][0]
        self.assertEqual(row['grouping_relation'], 'different_declared_grouping')
        self.assertEqual(row['notation_relation'], 'reviewed_4_4_8_4_allowance_requires_bar_correspondence')
        self.assertFalse(result['declared_notation_comparison']['known_notation_disagreement'])

    def test_reviewed_b_remains_distinct_with_equal_bar_times(self):
        result = compare(constant_map(3,4,grouping=[1,1,1]), constant_map(6,8,grouping=[3,3]))
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'], 1)
        self.assertTrue(result['declared_notation_comparison']['known_notation_disagreement'])
        self.assertIn('different_declared_grouping', result['declared_notation_comparison']['grouping_relation_counts'])

    def test_other_cross_signature_is_unresolved_even_if_time_and_groups_match(self):
        result = compare(constant_map(grouping=[1,1,1,1]), constant_map(4,8,bpm=60,grouping=[1,1,1,1]))
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'], 1)
        self.assertTrue(result['declared_notation_comparison']['unknown_cross_notation_present'])
        self.assertFalse(result['declared_notation_comparison']['known_notation_disagreement'])

    def test_explicit_dotted_quarter_pulse_unit_is_normalized_without_reference_fitting(self):
        result = compare(constant_map(6,8,grouping=[3,3]),
                         constant_map(6,8,unit=Fraction(3,2),grouping=[3,3]))
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'], 1)
        self.assertAlmostEqual(profile(result)['paired_bars']['continuous_timing_summary']['absolute_max_seconds'], 0)
        self.assertFalse(result['alignment_applied'])

    def test_half_rate_same_meter_does_not_get_free_octave_correction(self):
        result = compare(constant_map(), constant_map(bpm=60))
        self.assertLess(profile(result)['bar_boundaries']['scores']['recall'], 1)
        self.assertEqual(profile(result)['paired_bars']['count'], 0)
        self.assertTrue(profile(result)['paired_bars']['unmatched_reference_bar_indices'])

    def test_same_phase_error_is_retained_at_each_tolerance_without_origin_fit(self):
        result = compare(constant_map(), constant_map(shift=.15), tolerances_seconds=(.1,.2))
        self.assertEqual(profile(result,.1)['paired_bars']['count'], 0)
        paired = profile(result,.2)['paired_bars']
        self.assertGreater(paired['count'],0)
        self.assertAlmostEqual(paired['continuous_timing_summary']['absolute_max_seconds'], .15)
        self.assertTrue(all(abs(row['start_boundary_error_seconds']-.15)<1e-10 for row in paired['comparisons']))
        self.assertEqual(result['indexed_drift']['status'], 'unanchored')

    def test_negative_nineteen_ms_boundary_is_not_lost_or_turned_into_one_bar_error(self):
        result = compare(constant_map(), constant_map(shift=-.019))
        p = profile(result)
        self.assertEqual(p['bar_boundaries']['scores']['f1'],1)
        self.assertEqual(p['bar_boundaries']['matched_context_event_count'],1)
        self.assertAlmostEqual(p['paired_bars']['continuous_timing_summary']['absolute_max_seconds'],.019)
        self.assertEqual(profile(result,.01)['bar_boundaries']['scores']['true_positives'],0)

    def test_exact_tolerance_edge_is_inclusive_with_only_roundoff_slack(self):
        for shift in (.02,-.02):
            result=compare(constant_map(),constant_map(shift=shift))
            with self.subTest(shift=shift):
                self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)
                self.assertAlmostEqual(profile(result)['paired_bars']['continuous_timing_summary']['absolute_max_seconds'],.02)
        beyond=compare(constant_map(),constant_map(shift=.020001))
        self.assertEqual(profile(beyond)['bar_boundaries']['scores']['true_positives'],0)

    def test_ulp_rendered_boundary_at_reference_support_start_is_included(self):
        ref=constant_map();pred=deepcopy(ref)
        ref['support_seconds']=pred['support_seconds']=[[4.,8.]]
        ref['clock_knots'].insert(1,{'pulse':8.,'source_seconds':math.nextafter(4.,-math.inf)})
        result=compare(ref,pred)
        self.assertEqual(profile(result)['reference_bar_event_count'],3)
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)
        self.assertEqual(len(result['reference_expected_geometry']['fully_supported_bar_indices']),2)

    def test_prediction_boundary_in_interior_support_hole_is_not_rescued_by_tolerance(self):
        ref=constant_map();pred=constant_map(shift=-.019)
        pred['support_seconds']=[[0.,3.],[4.,8.]]
        result=compare(ref,pred)
        boundaries=profile(result)['bar_boundaries']
        self.assertIn(4.,boundaries['unmatched_reference_seconds'])
        self.assertFalse(any(abs(row['prediction_seconds']-3.981)<1e-10 for row in boundaries['matched_events']))
        self.assertEqual(result['coverage']['uncovered_reference_intervals'],[[3.,4.]])

    def test_large_source_origin_does_not_create_a_large_relative_tolerance(self):
        ref=constant_map(duration=1000010.);pred=deepcopy(ref)
        ref['clock_knots']=[{'pulse':2000000.,'source_seconds':1000000.},
                            {'pulse':2000020.,'source_seconds':1000010.}]
        pred['clock_knots']=[{'pulse':2000000.,'source_seconds':1000000.01},
                             {'pulse':2000020.,'source_seconds':1000010.01}]
        ref['support_seconds']=pred['support_seconds']=[[1000000.02,1000009.98]]
        result=compare(ref,pred,tolerances_seconds=(.005,.02))
        self.assertEqual(profile(result,.005)['bar_boundaries']['scores']['true_positives'],0)
        self.assertAlmostEqual(profile(result)['paired_bars']['continuous_timing_summary']['absolute_max_seconds'],.01,places=8)

    def test_equal_bar_endpoints_do_not_hide_interior_clock_error(self):
        ref = constant_map(); pred = deepcopy(ref)
        pred['clock_knots'] = [{'pulse':-4.,'source_seconds':-2.}, {'pulse':0.,'source_seconds':0.},
            {'pulse':2.,'source_seconds':.5},{'pulse':4.,'source_seconds':2.},{'pulse':20.,'source_seconds':10.}]
        p = profile(compare(ref,pred))
        self.assertEqual(p['bar_boundaries']['scores']['f1'],1)
        first = next(row for row in p['paired_bars']['comparisons'] if row['continuous_timing']['absolute_max_seconds']>.4)
        self.assertAlmostEqual(first['continuous_timing']['absolute_max_seconds'],.5)
        self.assertAlmostEqual(first['continuous_timing']['absolute_mean_seconds'],.25)

    def test_drift_that_recovers_at_song_end_is_detected_analytically(self):
        ref = constant_map(duration=20.); pred=deepcopy(ref)
        ref['clock_knots']=[{'pulse':0.,'source_seconds':0.},{'pulse':40.,'source_seconds':20.}]
        pred['clock_knots']=[{'pulse':0.,'source_seconds':0.},{'pulse':20.,'source_seconds':9.9},
                             {'pulse':40.,'source_seconds':20.}]
        result=compare(ref,pred,tolerances_seconds=(.11,)); summary=profile(result,.11)['paired_bars']['continuous_timing_summary']
        self.assertEqual(summary['scored_bar_count'],10)
        self.assertAlmostEqual(summary['absolute_max_seconds'],.1)
        self.assertAlmostEqual(summary['absolute_mean_seconds'],.05)

    def test_absolute_integral_splits_at_error_zero_crossing(self):
        ref=constant_map(duration=2.); pred=deepcopy(ref)
        ref['clock_knots']=[{'pulse':0.,'source_seconds':0.},{'pulse':4.,'source_seconds':2.}]
        pred['clock_knots']=[{'pulse':0.,'source_seconds':0.},{'pulse':1.,'source_seconds':.6},
            {'pulse':3.,'source_seconds':1.4},{'pulse':4.,'source_seconds':2.}]
        row=profile(compare(ref,pred))['paired_bars']['comparisons'][0]['continuous_timing']
        self.assertAlmostEqual(row['absolute_max_seconds'],.1)
        self.assertAlmostEqual(row['absolute_mean_seconds'],.05)
        self.assertAlmostEqual(row['signed_mean_seconds'],0)

    def test_narrow_interior_excursion_cannot_hide_between_fixed_samples(self):
        ref=constant_map(duration=2.); pred=deepcopy(ref)
        pred['clock_knots']=[{'pulse':0.,'source_seconds':0.},{'pulse':1.998,'source_seconds':.999},
            {'pulse':2.,'source_seconds':1.0004},{'pulse':2.002,'source_seconds':1.001},
            {'pulse':4.,'source_seconds':2.}]
        summary=profile(compare(ref,pred))['paired_bars']['continuous_timing_summary']
        self.assertAlmostEqual(summary['absolute_max_seconds'],.0004)
        self.assertGreater(summary['absolute_mean_seconds'],0)

    def test_redundant_clock_and_meter_declarations_do_not_change_scores(self):
        ref=constant_map(); pred=deepcopy(ref)
        pred['clock_knots'].insert(1,{'pulse':2.,'source_seconds':1.})
        pred['meter_events'].append({'pulse':1.,'numerator':4,'denominator':4,'grouping':None,'bar_action':'continue'})
        result=compare(ref,pred)
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)
        self.assertAlmostEqual(profile(result)['paired_bars']['continuous_timing_summary']['absolute_max_seconds'],0)

    def test_bar_anchor_integer_relabeling_does_not_shift_physical_geometry(self):
        ref=constant_map(); pred=deepcopy(ref);pred['bar_anchor_pulse']=400.
        result=compare(ref,pred)
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)
        self.assertAlmostEqual(profile(result)['paired_bars']['continuous_timing_summary']['absolute_max_seconds'],0)
        self.assertEqual(result['indexed_drift']['status'],'unanchored')

    def test_pickup_phase_is_preserved_and_false_source_zero_downbeat_disagrees(self):
        ref=constant_map();ref['bar_anchor_pulse']=-1.
        pred=constant_map()
        result=compare(ref,pred)
        self.assertEqual(profile(result)['bar_boundaries']['scores']['true_positives'],0)
        self.assertEqual(profile(result)['paired_bars']['count'],0)
        self.assertTrue(result['reference_expected_geometry']['partly_supported_bar_indices'])

    def test_five_eighth_bars_can_end_between_quarters(self):
        result=compare(constant_map(5,8,grouping=[2,3]),constant_map(5,8,grouping=[2,3]))
        matches=profile(result)['bar_boundaries']['matched_events']
        self.assertIn(1.25,[m['reference_seconds'] for m in matches])
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)

    def test_delayed_meter_transition_changes_ordered_physical_bar_sequence(self):
        ref=constant_map(); pred=constant_map()
        ref['meter_events'].append({'pulse':8.,'numerator':3,'denominator':4,'grouping':None,'bar_action':'continue'})
        pred['meter_events'].append({'pulse':12.,'numerator':3,'denominator':4,'grouping':None,'bar_action':'continue'})
        result=compare(ref,pred)
        self.assertTrue(profile(result)['paired_bars']['unmatched_reference_bar_indices'])
        self.assertLess(profile(result)['bar_boundaries']['scores']['recall'],1)

    def test_coverage_hole_remains_visible_with_perfect_supported_matches(self):
        ref=constant_map(); pred=deepcopy(ref);pred['support_seconds']=[[0.,3.],[4.,8.]]
        result=compare(ref,pred)
        self.assertEqual(result['coverage']['prediction_source_fraction'],.875)
        self.assertEqual(result['coverage']['uncovered_reference_intervals'],[[3.,4.]])
        self.assertTrue(result['prediction_available_geometry']['partly_supported_bar_indices'])
        self.assertIsNone(result['overall_product_pass'])

    def test_very_small_real_support_gap_is_not_healed(self):
        ref=constant_map();pred=deepcopy(ref);pred['support_seconds']=[[0,3],[3.000001,8]]
        result=compare(ref,pred)
        self.assertEqual(result['coverage']['uncovered_reference_intervals'],[[3.,3.000001]])
        self.assertLess(result['coverage']['prediction_source_fraction'],1)

    def test_reference_scope_does_not_become_full_source_coverage(self):
        ref=constant_map();pred=deepcopy(ref)
        ref['support_seconds']=pred['support_seconds']=[[2.,6.]]
        result=compare(ref,pred)
        self.assertEqual(result['coverage']['reference_coverage_fraction'],1)
        self.assertEqual(result['coverage']['prediction_source_fraction'],.5)

    def test_absent_invalid_and_unsupported_predictions_remain_distinct_records(self):
        ref=constant_map()
        absent=compare(ref,None)
        self.assertEqual(absent['status'],'absent_prediction')
        self.assertEqual(profile(absent)['unavailable_reference_bar_event_count'],5)
        bad=deepcopy(ref);bad['clock_knots'][1]['source_seconds']=-10
        invalid=compare(ref,bad)
        self.assertEqual(invalid['status'],'invalid_prediction')
        self.assertEqual(profile(invalid)['unavailable_reference_bar_event_count'],5)
        unsupported=deepcopy(ref);unsupported['meter_events']=None
        result=compare(ref,unsupported)
        self.assertEqual(profile(result)['status'],'unsupported_prediction_bar_geometry')
        self.assertIsNone(profile(result)['bar_boundaries'])
        self.assertEqual(result['coverage']['prediction_source_fraction'],1)

    def test_empty_clock_output_is_not_a_vacuous_perfect_comparison(self):
        ref=constant_map();pred=deepcopy(ref);pred['clock_knots']=[];pred['support_seconds']=[]
        result=compare(ref,pred)
        self.assertEqual(profile(result)['reason'],'missing_clock')
        self.assertEqual(result['coverage']['prediction_source_fraction'],0)
        self.assertIsNone(profile(result)['bar_boundaries'])

    def test_unqualified_reference_is_not_promoted_by_valid_geometry(self):
        result=compare(constant_map(),constant_map(),qualification={})
        self.assertEqual(profile(result)['status'],'unscored_unverified_reference_bar_timing')
        self.assertFalse(result['reference']['capability']['reference_qualified_by_constructor'])
        self.assertIsNone(result['overall_product_pass'])

    def test_verified_bar_boundaries_do_not_qualify_interior_clock(self):
        flags={**QUALIFIED,'clock_timing':False}
        result=compare(constant_map(),constant_map(),qualification=flags)
        self.assertEqual(profile(result)['bar_boundaries']['scores']['f1'],1)
        summary=profile(result)['paired_bars']['continuous_timing_summary']
        self.assertEqual(summary['status'],'unscored_unverified_reference_clock_timing')
        self.assertIsNone(summary['absolute_max_seconds'])

    def test_known_mismatch_and_unknown_grouping_are_both_retained(self):
        result=compare(constant_map(3,4),constant_map(6,8),qualification={**QUALIFIED,'grouping':False})
        declared=result['declared_notation_comparison']
        self.assertTrue(declared['known_notation_disagreement'])
        self.assertIn('unscored_unverified_reference',declared['grouping_relation_counts'])

    def test_matching_origin_metadata_does_not_falsely_claim_indexed_drift_implemented(self):
        ref=constant_map();pred=deepcopy(ref)
        ref['shared_origin_id']=pred['shared_origin_id']='known-musical-landmark'
        result=compare(ref,pred)
        self.assertEqual(result['indexed_drift']['status'],'not_implemented')
        self.assertFalse(result['alignment_applied'])

    def test_source_identity_and_native_geometry_mismatch_block_scores(self):
        for field,value in [('sha256','1'*64),('sample_rate',96000),('sample_frames',768000)]:
            ref=constant_map();pred=deepcopy(ref);pred['source'][field]=value
            if field=='sample_rate':pred['support_seconds']=[[0.,4.]]
            result=compare(ref,pred)
            with self.subTest(field=field):
                self.assertEqual(result['status'],'blocked_source_identity_or_sample_clock_mismatch')
                self.assertEqual(result['timing_profiles'],[])
                self.assertIsNone(result['coverage'])

    def test_evaluator_options_reject_nonfinite_boolean_or_ambiguous_values(self):
        ref=constant_map()
        for value in [(),(0,),(-1,),(.01,.01),(float('nan'),),(float('inf'),),(True,)]:
            with self.subTest(value=value), self.assertRaises(ValueError):compare(ref,ref,tolerances_seconds=value)
        for flags in [{'bar_timing':1},{'bar_timng':True},None]:
            with self.subTest(flags=flags),self.assertRaises(ValueError):compare(ref,ref,qualification=flags)

    def test_analysis_conditions_remain_distinct_metadata(self):
        ref=constant_map();pred=deepcopy(ref)
        ref['analysis_condition']='reference';pred['analysis_condition']='user_bpm_guided'
        result=compare(ref,pred)
        self.assertEqual(result['reference']['analysis_condition'],'reference')
        self.assertEqual(result['prediction']['analysis_condition'],'user_bpm_guided')


if __name__=='__main__':
    unittest.main()
