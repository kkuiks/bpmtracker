import unittest
import numpy as np

from clock_candidate_regions import generate_region_candidates
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


if __name__ == '__main__':
    unittest.main()
