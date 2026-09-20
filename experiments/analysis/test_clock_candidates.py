import unittest

import numpy as np

from clock_candidates import CandidateConfig, generate_clock_candidates


def evidence(events, duration, fps=50):
    logits = np.full(int(np.ceil(duration * fps)), -7., dtype=float)
    for event in events:
        center = round(event * fps)
        if 0 <= center < len(logits):
            logits[center] = 7.
    return logits, np.full_like(logits, -7.)


class CandidateTests(unittest.TestCase):
    def test_mixed_half_and_full_pulses_have_consistent_quarter_candidate(self):
        truth = np.arange(1., 61., .5)
        observed = np.r_[truth[:60:2], truth[60:]]
        beat, down = evidence(observed, 63.)
        result = generate_clock_candidates(beat, down, 50., observed)
        matches = [c for c in result['candidates'] if len(c['clock']['segments']) == 1 and
                   abs(c['clock']['segments'][0]['pulse_rate_per_minute'] - 120) < .01]
        self.assertTrue(matches)
        quarter = min(matches, key=lambda c: c['phase_offset_quarters'])
        grid = np.array([e['source_seconds'] for e in quarter['indexed_grid']])
        np.testing.assert_allclose(grid, truth, atol=1e-8)
        self.assertTrue(quarter['missing_pulse_hypotheses'])
        self.assertFalse(result['reference_used_for_prediction'])

    def test_genuine_small_tempo_changes_survive_mixed_input_level(self):
        intervals = np.r_[np.full(30, .5), np.full(30, 60 / 123), np.full(30, 60 / 126)]
        truth = np.r_[1., 1 + np.cumsum(intervals)]
        observed = np.r_[truth[:30:2], truth[30:]]
        beat, down = evidence(observed, truth[-1] + 2)
        result = generate_clock_candidates(beat, down, 50., observed)
        good = []
        for candidate in result['candidates']:
            rates = [s['pulse_rate_per_minute'] for s in candidate['clock']['segments']]
            if len(rates) == 3 and np.max(abs(np.array(rates) - [120, 123, 126])) < .15:
                good.append(candidate)
        self.assertTrue(good)

    def test_phase_alternatives_preserve_period_and_source_origin(self):
        events = np.arange(1.25, 32., .5)
        beat, down = evidence(events, 34.)
        result = generate_clock_candidates(beat, down, 50., events)
        pair = [c for c in result['candidates'] if c['id'].startswith('path0-')]
        self.assertEqual(len(pair), 2)
        self.assertAlmostEqual(pair[1]['indexed_grid'][0]['source_seconds'] -
                               pair[0]['indexed_grid'][0]['source_seconds'], .25, places=7)
        self.assertEqual(result['source_origin_seconds'], 0)
        self.assertEqual(pair[0]['musical_index_origin'], 'candidate_relative_unanchored')
        self.assertEqual(pair[0]['meter']['status'], 'unresolved')

    def test_locked_anchors_are_exact_and_inputs_unchanged(self):
        events = np.arange(1., 32., .5)
        beat, down = evidence(events, 35.)
        previous_events, previous_beat = events.copy(), beat.copy()
        anchors = [{'source_seconds': 5.01, 'quarter_position': 8, 'locked': True},
                   {'source_seconds': 13.02, 'quarter_position': 24, 'locked': True}]
        result = generate_clock_candidates(beat, down, 50., events, anchors)
        self.assertTrue(result['candidates'])
        for candidate in result['candidates']:
            for check in candidate['anchor_checks']:
                self.assertLess(check['absolute_error_seconds'], 1e-10)
            times = [p['source_seconds'] for p in candidate['indexed_grid']]
            self.assertTrue(np.all(np.diff(times) > 0))
            self.assertFalse(candidate['accepted'])
        np.testing.assert_array_equal(events, previous_events)
        np.testing.assert_array_equal(beat, previous_beat)

    def test_conflicting_locks_are_not_silently_relaxed(self):
        events = np.arange(1., 32., .5)
        beat, down = evidence(events, 35.)
        anchors = [{'source_seconds': 5., 'quarter_position': 8},
                   {'source_seconds': 6., 'quarter_position': 8}]
        result = generate_clock_candidates(beat, down, 50., events, anchors)
        self.assertFalse(result['candidates'])
        self.assertIsNone(result['selected_candidate_id'])
        self.assertEqual(result['selection_status'], 'no_candidate_satisfies_anchors_or_budgets')

    def test_budget_is_explicit_and_invalid_evidence_rejected(self):
        events = np.arange(1., 32., .5)
        beat, down = evidence(events, 35.)
        result = generate_clock_candidates(beat, down, 50., events, config=CandidateConfig(max_events=10))
        self.assertEqual(result['selection_status'], 'event_count_budget_or_insufficient_evidence')
        beat[0] = np.nan
        with self.assertRaises(ValueError):
            generate_clock_candidates(beat, down, 50., events)


if __name__ == '__main__':
    unittest.main()
