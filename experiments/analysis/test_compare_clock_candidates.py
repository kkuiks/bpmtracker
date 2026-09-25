"""Evaluation contracts for failed map output, unsupported paths and references."""
import unittest

from compare_clock_candidates import evaluate_tempo_map, evaluate_times


class TempoMapEvaluationTests(unittest.TestCase):
    def reference(self, events):
        return {'evaluation_support_seconds': [0., 4.], 'beats_seconds': [.5, 1.5, 2.5],
                'tempo_events': events}

    def test_capable_missing_map_counts_every_qualified_missed_change(self):
        reference = self.reference([{'time_seconds': 0., 'bpm_quarter': 120.},
                                    {'time_seconds': 1., 'bpm_quarter': 140.},
                                    {'time_seconds': 3., 'bpm_quarter': 120.}])
        result = evaluate_times(reference, [.5, 1.5, 2.5], tempo_map_supported=True)
        self.assertEqual(result['event_20ms']['f1'], 1.)
        self.assertEqual(result['tempo_map_status'], 'failed_no_tempo_map')
        for label in ('100ms', '500ms'):
            value = result['tempo_changes_' + label]
            self.assertEqual(value['status'], 'failed_no_tempo_map')
            self.assertEqual(value['full_change_scores']['false_negatives'], 2)
            self.assertEqual(value['full_change_scores']['f1'], 0.)

    def test_unsupported_path_is_not_a_failed_map(self):
        result = evaluate_tempo_map(self.reference([{'time_seconds': 0., 'bpm_quarter': 120.},
            {'time_seconds': 1., 'bpm_quarter': 140.}]), tempo_map_supported=False)
        self.assertEqual(result['tempo_changes_100ms'], {'status': 'unsupported_tempo_map'})

    def test_missing_reference_is_unscored_even_when_prediction_fails(self):
        result = evaluate_tempo_map(self.reference(None), tempo_map_supported=True)
        self.assertEqual(result['tempo_map_status'], 'failed_no_tempo_map')
        self.assertEqual(result['tempo_changes_100ms']['status'], 'unscored_missing_reference')
        self.assertNotIn('full_change_scores', result['tempo_changes_100ms'])

    def test_constant_reference_does_not_make_missing_map_successful(self):
        reference = self.reference([{'time_seconds': 0., 'bpm_quarter': 120.}])
        failed = evaluate_tempo_map(reference, tempo_map_supported=True)
        score = failed['tempo_changes_100ms']['full_change_scores']
        self.assertEqual(score['false_negatives'], 0)
        self.assertIsNone(score['f1'])
        self.assertEqual(failed['tempo_map_status'], 'failed_no_tempo_map')
        produced = evaluate_tempo_map(reference, [], tempo_map_supported=True)
        self.assertEqual(produced['tempo_map_status'], 'tempo_map_produced')
        self.assertEqual(produced['tempo_changes_100ms']['full_change_scores']['f1'], 1.)

    def test_existing_unspecified_capability_preserves_no_map_status(self):
        result = evaluate_tempo_map(self.reference(None))
        self.assertEqual(result['tempo_changes_100ms'], {'status': 'no_tempo_map'})

    def test_supported_map_keeps_rate_and_span_rules(self):
        reference = self.reference([{'time_seconds': 0., 'bpm_quarter': 120.},
            {'time_seconds': 2., 'bpm_quarter': 140.}])
        changes = [{'source_seconds': 2.01, 'bpm_before': 120., 'bpm_after': 140., 'type': 'step'},
                   {'source_seconds': 5., 'bpm_before': 140., 'bpm_after': 120., 'type': 'step'}]
        result = evaluate_tempo_map(reference, changes, tempo_map_supported=True)
        self.assertEqual(result['tempo_changes_100ms']['full_change_scores']['true_positives'], 1)
        self.assertEqual(result['tempo_change_evaluation_support']['outside_prediction_count'], 1)
        self.assertEqual(len(changes), 2)


if __name__ == '__main__': unittest.main()
