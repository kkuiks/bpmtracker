import unittest
from unittest.mock import patch
from copy import deepcopy

import numpy as np

from clock_candidates import (CandidateConfig, generate_clock_candidates, rank_candidate_evidence)
from fit_clock import fit_clock


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


class CandidateInvariantTests(unittest.TestCase):
    def test_invalid_configuration_rejected_before_empty_evidence(self):
        configurations = [CandidateConfig(window_seconds=-1), CandidateConfig(phases=(np.nan,)),
            CandidateConfig(phases=(0., 0.)), CandidateConfig(phases=(1.,)),
            CandidateConfig(min_period_seconds=1., max_period_seconds=.2),
            CandidateConfig(max_gap_pulses=.5), CandidateConfig(max_events=4),
            CandidateConfig(max_segments=0), CandidateConfig(seed_band_ratio=.9)]
        for configuration in configurations:
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                generate_clock_candidates([], [], 50., [], config=configuration)

    def test_input_events_are_inside_actual_source_even_if_logits_are_padded(self):
        beat = np.zeros(500)
        with self.assertRaisesRegex(ValueError, 'physical source'):
            generate_clock_candidates(beat, beat, 50., np.arange(1., 9., .5), source_duration_seconds=8.)
        with self.assertRaisesRegex(ValueError, 'cover'):
            generate_clock_candidates(beat, beat, 50., [], source_duration_seconds=11.)

    def test_fitted_overshoot_is_clipped_before_ranking_without_shifting_clock(self):
        events = np.arange(1., 9., .5)
        beat, downbeat = evidence(events, 10.)
        baseline = fit_clock(events)
        baseline['coefficients'] = [1., .51]
        baseline['knot_pulse_indices'] = []
        saved = deepcopy(baseline)
        with patch('clock_candidates.fit_clock', return_value=baseline):
            result = generate_clock_candidates(beat, downbeat, 50., events, source_duration_seconds=8.6)
        overshoots = [c for c in result['candidates'] if c['fitted_clock_support_seconds'][1] >= 8.6]
        self.assertTrue(overshoots)
        for candidate in result['candidates']:
            times = [g['source_seconds'] for g in candidate['indexed_grid']]
            self.assertTrue(all(0 <= t < 8.6 for t in times))
            self.assertTrue(np.all(np.diff(times) > 0))
            value, _ = rank_candidate_evidence(candidate['indexed_grid'], beat, 50., events, candidate['clock'])
            self.assertAlmostEqual(candidate['evidence_score_not_confidence'], value)
            self.assertFalse(candidate['clock_curve_clipped_or_shifted'])
        self.assertEqual(baseline, saved)

    def test_outside_audio_locked_anchor_cannot_be_hidden_by_clipping(self):
        events = np.arange(1., 9., .5)
        beat, downbeat = evidence(events, 10.)
        result = generate_clock_candidates(beat, downbeat, 50., events,
            anchors=[{'quarter_position': 6, 'source_seconds': 9., 'locked': True}],
            source_duration_seconds=8.6)
        self.assertFalse(result['candidates'])
        self.assertEqual(result['selection_status'], 'no_candidate_satisfies_anchors_or_budgets')
        self.assertTrue(any('physical source' in c['reason'] for c in result['rejected_candidates']))

    def test_balanced_rank_penalizes_missing_evidence_and_extra_grid_points(self):
        events = np.array([1., 2., 3.]); beat, _ = evidence(events, 5.)
        proposal = {'segments': [{'start_seconds': 0., 'end_seconds': 5., 'pulse_rate_per_minute': 60.}]}
        def rank(times):
            grid = [{'quarter_position': i, 'source_seconds': t} for i, t in enumerate(times)]
            return rank_candidate_evidence(grid, beat, 50., events, proposal, ranking_policy='balanced_evidence')[0]
        self.assertGreater(rank([1., 2., 3.]), rank([1., 3.]))
        self.assertGreater(rank([1., 2., 3.]), rank([1., 2., 3., 4.]))

    def test_balanced_rank_credits_each_acoustic_peak_once(self):
        events = np.array([1.]); beat, _ = evidence(events, 3.)
        proposal = {'segments': [{'start_seconds': 0., 'end_seconds': 3., 'pulse_rate_per_minute': 60.}]}
        grid = [{'quarter_position': i, 'source_seconds': t} for i, t in enumerate([.98, 1.02])]
        value, components = rank_candidate_evidence(grid, beat, 50., events, proposal,
                                                    ranking_policy='balanced_evidence')
        self.assertEqual(components['matched_event_count'], 1)
        self.assertLess(components['soft_precision'], .51)
        self.assertLess(value, .67)

    def test_legacy_is_default_and_optional_policy_preserves_candidates(self):
        events = np.arange(1., 15., .5); beat, down = evidence(events, 16.)
        original = generate_clock_candidates(beat, down, 50., events)
        alternate = generate_clock_candidates(beat, down, 50., events, ranking_policy='balanced_evidence')
        self.assertEqual(original['ranking_policy'], 'legacy')
        self.assertEqual([c['indexed_grid'] for c in original['candidates']],
                         [c['indexed_grid'] for c in alternate['candidates']])
        self.assertTrue(all('legacy_score_not_confidence' in c['ranking_components'] for c in alternate['candidates']))


if __name__ == '__main__':
    unittest.main()
