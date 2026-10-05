import unittest
import numpy as np

from clock_candidate_regions import RegionConfig, generate_region_candidates
from test_clock_candidates import evidence


class RegionCandidateTests(unittest.TestCase):
    def test_isolated_early_event_does_not_block_later_clock_and_source_is_unchanged(self):
        events = np.r_[1., np.arange(40., 71., .5)]
        beat, down = evidence(events, 75.)
        original = events.copy(); original_logits = beat.copy()
        result = generate_region_candidates(beat, down, 50., events)
        self.assertTrue(result['candidates'])
        self.assertFalse(result['reference_used_for_prediction'])
        self.assertEqual(result['source_origin_seconds'], 0)
        for c in result['candidates']:
            self.assertGreaterEqual(c['indexed_grid'][0]['source_seconds'], 39.999)
            self.assertFalse(c['full_song_map'])
        np.testing.assert_array_equal(events, original)
        np.testing.assert_array_equal(beat, original_logits)

    def test_unknown_gap_is_not_bridged_by_an_invented_quarter_count(self):
        events = np.r_[np.arange(1., 13., .5), np.arange(50., 66., .5)]
        beat, down = evidence(events, 70.)
        result = generate_region_candidates(beat, down, 50., events)
        self.assertEqual(len(result['regions']), 2)
        self.assertLessEqual(len(result['candidates']), 8)
        self.assertIsNone(result['unknown_bridges'][0]['quarter_count'])
        for candidate in result['candidates']:
            times = [e['source_seconds'] for e in candidate['indexed_grid']]
            self.assertTrue(max(times) < 13 or min(times) > 49)
            self.assertIn('no_cross_region', candidate['musical_index_origin'])

    def test_real_tempo_changes_survive_inside_recovered_region(self):
        intervals = np.r_[np.full(30, .5), np.full(30, 60 / 123), np.full(30, 60 / 126)]
        later = np.r_[40., 40 + np.cumsum(intervals)]
        events = np.r_[1., later]
        beat, down = evidence(events, later[-1] + 3)
        result = generate_region_candidates(beat, down, 50., events)
        rates = [[s['pulse_rate_per_minute'] for s in c['clock']['segments']] for c in result['candidates']]
        self.assertTrue(any(len(r) == 3 and np.max(abs(np.array(r) - [120, 123, 126])) < .15 for r in rates))


class RegionInvariantTests(unittest.TestCase):
    def test_global_cap_smaller_than_region_count_is_still_hard(self):
        events = np.r_[np.arange(1., 13., .5), np.arange(50., 66., .5)]
        beat, down = evidence(events, 70.)
        result = generate_region_candidates(beat, down, 50., events, config=RegionConfig(max_candidates=1))
        self.assertEqual(len(result['regions']), 2)
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(any(r['reason'] == 'global_candidate_budget' for r in result['rejected_regions']))

    def test_bad_evidence_cannot_escape_validation_via_empty_events(self):
        for beat, down, fps in [(np.array([np.nan]), np.zeros(1), 50.),
                                (np.zeros(10), np.zeros(5), 50.),
                                (np.zeros(10), np.zeros(10), 0.)]:
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                generate_region_candidates(beat, down, fps, [])

    def test_unvalidated_balanced_ranking_is_rejected_for_regions(self):
        events = np.arange(1., 10., .5)
        beat, down = evidence(events, 12.)
        with self.assertRaisesRegex(ValueError, 'limited to full-source candidates'):
            generate_region_candidates(beat, down, 50., events, ranking_policy='balanced_evidence')

    def test_invalid_region_budgets_rejected(self):
        for configuration in [RegionConfig(max_candidates=0), RegionConfig(max_regions=0),
                RegionConfig(max_candidates=1.5), RegionConfig(minimum_stable_events=1),
                RegionConfig(gap_floor_seconds=np.nan)]:
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                generate_region_candidates([], [], 50., [], config=configuration)


if __name__ == '__main__':
    unittest.main()
