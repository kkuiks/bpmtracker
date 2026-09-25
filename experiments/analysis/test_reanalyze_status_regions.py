from copy import deepcopy
import unittest

from reanalyze_status_regions import score_regions


class RegionReanalysisScoringTests(unittest.TestCase):
    def test_local_perfection_does_not_hide_uncovered_song(self):
        reference = {'beats_seconds': [0., 1., 2., 3., 4., 5.], 'evaluation_support_seconds': [0., 5.],
            'tempo_events': [{'time_seconds': 0., 'bpm_quarter': 60.}], 'downbeats_seconds': None}
        candidate = {'id': 'partial', 'indexed_grid': [{'quarter_position': i, 'source_seconds': float(i + 2)} for i in range(3)],
            'tempo_events': [], 'source_support_seconds': [2., 4.]}
        generated = {'selected_candidate_id': 'partial', 'candidates': [candidate]}
        before = deepcopy(generated)
        result = score_regions(reference, generated)
        self.assertEqual(result['selected']['within_proposed_region_diagnostic']['event_20ms']['f1'], 1.)
        self.assertLess(result['selected']['whole_annotation_diagnostic']['event_20ms']['f1'], 1.)
        self.assertEqual(generated, before)
        self.assertFalse(result['selected']['full_song_map'])
        self.assertTrue(result['oracle_diagnostics']['diagnostic_only'])

    def test_empty_region_candidate_counts_all_missed_changes(self):
        reference = {'beats_seconds': [0., 1., 2., 3.], 'evaluation_support_seconds': [0., 3.],
            'tempo_events': [{'time_seconds': 0., 'bpm_quarter': 60.}, {'time_seconds': 2., 'bpm_quarter': 120.}]}
        result = score_regions(reference, {'selected_candidate_id': None, 'candidates': []})
        selected = result['selected']
        self.assertEqual(selected['whole_annotation_diagnostic']['tempo_changes_100ms']['full_change_scores']['false_negatives'], 1)
        self.assertIsNone(selected['within_proposed_region_diagnostic'])


if __name__ == '__main__':
    unittest.main()
