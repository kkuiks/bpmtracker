from copy import deepcopy
import unittest

from compare_clock_candidates import evaluate_times


class CandidateScoringTests(unittest.TestCase):
    def test_declared_support_excludes_unverified_outro_without_hiding_real_false_change(self):
        reference = {'beats_seconds': [1., 2., 3., 4., 5., 8.],
                     'evaluation_support_seconds': [1., 5.],
                     'tempo_events': [{'time_seconds': 0., 'bpm_quarter': 120.},
                                      {'time_seconds': 2., 'bpm_quarter': 121.},
                                      {'time_seconds': 8., 'bpm_quarter': 122.}]}
        changes = [{'source_seconds': 1., 'bpm_before': 119., 'bpm_after': 120., 'type': 'step'},
                   {'source_seconds': 2., 'bpm_before': 120., 'bpm_after': 121., 'type': 'step'},
                   {'source_seconds': 3., 'bpm_before': 121., 'bpm_after': 123., 'type': 'step'},
                   {'source_seconds': 5., 'bpm_before': 123., 'bpm_after': 121., 'type': 'step'},
                   {'source_seconds': 8., 'bpm_before': 121., 'bpm_after': 122., 'type': 'step'}]
        original = deepcopy(changes)
        scores = evaluate_times(reference, [1., 2., 3., 4., 5., 8.], changes)
        for metric in ('tempo_changes_100ms', 'tempo_changes_500ms'):
            result = scores[metric]['full_change_scores']
            self.assertEqual((result['true_positives'], result['false_positives'], result['false_negatives']), (1, 1, 0))
        diagnostic = scores['tempo_change_evaluation_support']
        self.assertEqual(diagnostic['outside_prediction_count'], 3)
        self.assertEqual([e['source_seconds'] for e in diagnostic['outside_prediction_events']], [1., 5., 8.])
        self.assertEqual(changes, original)
        self.assertFalse(diagnostic['full_prediction_map_modified'])


if __name__ == '__main__':
    unittest.main()
