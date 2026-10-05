from copy import deepcopy
import unittest
import numpy as np

from diagnose_indexed_clock import (prepare_ideal_input, continuous_clock_metrics,
                                    run_case, score_ideal_clock)
from test_music_map_reference_adapters import fixture


def exact_reference(*, origin=0., support=None):
    reference, track = fixture(origin=origin, support=support)
    lo, hi = reference['evaluation_support_seconds']
    quarters = np.arange(0, 15, dtype=float)
    times = origin + quarters / 2
    keep = (times >= lo) & (times <= hi)
    reference['beats_seconds'] = times[keep].tolist()
    return reference, track


def linear_proposal(*, first=0., last=1., intercept=0., slope=1.):
    return {'pulse_index_span': [first, last], 'knot_pulse_indices': [],
            'coefficients': [intercept, slope],
            'segments': [{'start_pulse': first, 'end_pulse': last,
                'start_seconds': intercept + slope * first,
                'end_seconds': intercept + slope * last,
                'pulse_rate_per_minute': 60 / slope}]}


def metric_input(knots, *, support=None, origin=0., duration=10.):
    support = [knots[0]['source_seconds'], knots[-1]['source_seconds']] if support is None else support
    return {'reference_clock_map': {'clock_knots': knots},
        'original_reference_support_seconds': support, 'absolute_quarter_origin': origin,
        'source_duration_seconds': duration}


class IndexedClockDiagnosticTests(unittest.TestCase):
    def test_missing_identity_arrays_use_authored_coordinates_not_reenumeration(self):
        reference, track = exact_reference(support=[2., 7.])
        result = prepare_ideal_input(reference, track, retained_for_primary_scores=True)
        ideal = result['input']
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(ideal['absolute_quarter_origin'], 4.)
        self.assertEqual(ideal['absolute_quarter_indices'][0], 4.)
        self.assertEqual(ideal['relative_quarter_indices'][0], 0.)
        self.assertEqual(ideal['times_seconds'][0], 2.)
        self.assertFalse(ideal['source_time_shift_applied'])

    def test_known_missing_quarters_remain_index_gaps(self):
        reference, track = exact_reference()
        reference['beats_seconds'].pop(3)
        result = prepare_ideal_input(reference, track, retained_for_primary_scores=True)
        self.assertEqual(result['input']['relative_quarter_indices'][:5], [0., 1., 2., 4., 5.])

    def test_wrong_supplied_identities_are_rejected_not_aligned(self):
        reference, track = exact_reference()
        reference['quarter_indices'] = (np.arange(len(reference['beats_seconds'])) + 1).tolist()
        with self.assertRaises(ValueError):
            prepare_ideal_input(reference, track, retained_for_primary_scores=True)

    def test_click_only_and_rejected_references_are_unavailable(self):
        reference, track = exact_reference()
        result = prepare_ideal_input(reference, track, retained_for_primary_scores=False)
        self.assertEqual(result['status'], 'unavailable')
        reference['kind'] = 'creator_click_wav_with_audited_source_mapping'
        result = prepare_ideal_input(reference, track, retained_for_primary_scores=True)
        self.assertEqual(result['status'], 'unavailable')

    def test_bar_renderer_limitation_does_not_block_clock_only_control(self):
        reference, track = exact_reference()
        reference['meter_events'].append({'tick': 192, 'time_seconds': 1., 'numerator': 4, 'denominator': 4})
        result = prepare_ideal_input(reference, track, retained_for_primary_scores=True)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['reference_view_status'], 'unsupported')
        self.assertFalse(result['input']['bar_interpretation_used'])

    def test_continuous_metric_detects_error_hidden_between_identical_pulses(self):
        knots = [{'pulse': 0., 'source_seconds': 0.},
                 {'pulse': .5, 'source_seconds': .4},
                 {'pulse': 1., 'source_seconds': 1.}]
        result = continuous_clock_metrics(metric_input(knots, duration=1.), linear_proposal())
        self.assertAlmostEqual(result['maximum_absolute_error_seconds'], .1)
        self.assertAlmostEqual(result['reference_time_weighted_mae_seconds'], .05)
        self.assertAlmostEqual(result['within_time_error_fraction']['0.02'], .2)
        self.assertAlmostEqual(result['reference_time_weighted_mae_bpm'], 12.)
        self.assertEqual(result['knot_union_count'], 3)

    def test_predicted_interior_knot_is_also_in_exact_union(self):
        knots = [{'pulse': 0., 'source_seconds': 0.}, {'pulse': 1., 'source_seconds': 1.}]
        proposal = linear_proposal()
        proposal['knot_pulse_indices'] = [.5]
        proposal['coefficients'] = [0., .8, .4]
        result = continuous_clock_metrics(metric_input(knots, duration=1.), proposal)
        self.assertAlmostEqual(result['maximum_absolute_error_seconds'], .1)
        self.assertEqual(result['knot_union_count'], 3)

    def test_known_absolute_origin_and_partial_coverage_are_preserved(self):
        knots = [{'pulse': 0., 'source_seconds': 0.}, {'pulse': 20., 'source_seconds': 10.}]
        ideal = metric_input(knots, support=[1., 7.], origin=4., duration=10.)
        result = continuous_clock_metrics(ideal, linear_proposal(last=8., intercept=2., slope=.5))
        self.assertEqual(result['absolute_quarter_domain'], [4., 12.])
        self.assertAlmostEqual(result['maximum_absolute_error_seconds'], 0.)
        self.assertAlmostEqual(result['reference_support_coverage_fraction'], 4/6)
        self.assertAlmostEqual(result['uncovered_reference_duration_seconds'], 2.)
        self.assertAlmostEqual(result['covered_reference_fraction_of_audio'], .4)

    def test_no_clock_does_not_turn_reference_fallback_into_success(self):
        reference, track = exact_reference()
        ideal = prepare_ideal_input(reference, track, retained_for_primary_scores=True)['input']
        metrics = score_ideal_clock(reference, ideal, None)
        self.assertEqual(metrics['continuous_clock']['status'], 'no_clock_output')
        self.assertEqual(metrics['continuous_clock']['reference_support_coverage_fraction'], 0.)
        self.assertIsNone(metrics['tempo_changes_original_reference_support']['tempo_changes_100ms']['full_change_scores']['f1'])
        self.assertFalse(metrics['automatic_accuracy_claim'])

    def test_current_event_budget_is_preserved_without_subsampling(self):
        ideal = {'times_seconds': (np.arange(2001) * .5).tolist(),
                 'relative_quarter_indices': np.arange(2001).tolist()}
        original = deepcopy(ideal)
        result = run_case({}, ideal)
        self.assertEqual(result['status'], 'no_clock_output')
        self.assertEqual(result['fitter_status'], 'fallback_event_count_budget')
        self.assertTrue(result['fallback_copies_reference_input'])
        self.assertEqual(ideal, original)
        self.assertIsNone(result['proposal'])


if __name__ == '__main__':
    unittest.main()
