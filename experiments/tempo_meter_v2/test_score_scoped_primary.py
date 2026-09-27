"""A scoped song must penalize both late clicks and premature click stopping."""
import copy
import unittest

from experiments.tempo_meter_v2.score_scoped_primary import reference_raw, score_scoped


class ScopedPrimaryScoringTests(unittest.TestCase):
    def setUp(self):
        self.source = {'sha256': 'a'*64, 'sample_rate': 1000, 'sample_frames': 171000}
        self.start, self.end = 1.0, 151.0  # eighty 6/8 bars at 96 quarter BPM
        self.accepted = {
            'support_seconds': [[self.start, self.end]],
            'tempo_events': [{'bpm_quarter': 96.0}],
            'beats_seconds': [self.start + i*.625 for i in range(240)],
            'downbeats_seconds': [self.start + i*1.875 for i in range(80)]}
        self.policy = {'free_time_seconds': [self.end, 171.0]}
        self.exact = reference_raw(self.accepted, self.source)
        self.exact['analysis_condition'] = 'unhinted'

    def score(self, map_value):
        return score_scoped(self.accepted, self.policy, {'map': map_value}, self.source)

    def test_exact_scoped_map_passes_with_no_tail_clicks(self):
        result = self.score(self.exact)
        self.assertTrue(result['all_gates_pass'])
        self.assertEqual(result['beat_counts']['false_positives'], 0)
        self.assertEqual(result['bar_counts']['false_positives'], 0)
        self.assertEqual(result['free_tail_false_positives']['declared_map_support_seconds'], 0.)

    def test_half_quarter_internal_pulses_keep_quarter_event_count(self):
        denser = copy.deepcopy(self.exact)
        denser['clock_knots'][-1]['pulse'] *= 2
        denser['quarters_per_pulse'] = {'numerator': 1, 'denominator': 2}
        result = self.score(denser)
        self.assertTrue(result['all_gates_pass'])
        self.assertEqual(result['beat_counts']['true_positives'], 240)
        self.assertEqual(result['beat_counts']['false_positives'], 0)

    def test_full_grid_fails_even_if_six_original_thresholds_pass(self):
        extended = copy.deepcopy(self.exact)
        extended['clock_knots'][-1] = {'pulse': (171.-self.start)*96/60, 'source_seconds': 171.}
        extended['support_seconds'] = [[self.start, 171.]]
        result = self.score(extended)
        self.assertTrue(all(value >= .9 for value in result['scores'].values()))
        self.assertFalse(result['gates']['no_grid_in_free_ending'])
        self.assertGreater(result['free_tail_false_positives']['quarter_beats'], 0)
        self.assertGreater(result['free_tail_false_positives']['bar_starts'], 0)
        self.assertFalse(result['all_gates_pass'])

    def test_wrong_audio_hash_cannot_be_scored(self):
        other = copy.deepcopy(self.exact)
        other['source']['sha256'] = 'b'*64
        result = self.score(other)
        self.assertEqual(result['status'], 'prediction_map_unavailable')
        self.assertFalse(result['all_gates_pass'])
        self.assertIn('source identity', result['prediction_error'])

    def test_small_false_tempo_step_fails_change_gate(self):
        wobble = copy.deepcopy(self.exact)
        wobble['clock_knots'] = [
            {'pulse': 0., 'source_seconds': self.start},
            {'pulse': 120., 'source_seconds': 76.01},
            {'pulse': 240., 'source_seconds': self.end}]
        result = self.score(wobble)
        self.assertGreater(result['scores']['quarter_beat_f1_70ms'], .9)
        self.assertFalse(result['gates']['tempo_change_no_false_positives'])
        self.assertFalse(result['all_gates_pass'])

    def test_early_stop_fails_boundary_even_with_good_f1(self):
        early = copy.deepcopy(self.exact)
        early['clock_knots'][-1] = {'pulse': (self.end-10-self.start)*96/60,
                                    'source_seconds': self.end-10}
        early['support_seconds'] = [[self.start, self.end-10]]
        result = self.score(early)
        self.assertGreater(result['scores']['quarter_beat_f1_70ms'], .9)
        self.assertTrue(result['gates']['no_grid_in_free_ending'])
        self.assertFalse(result['gates']['grid_end_within_500ms'])
        self.assertFalse(result['all_gates_pass'])


if __name__ == '__main__':
    unittest.main()
