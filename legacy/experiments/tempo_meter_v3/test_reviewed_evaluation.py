"""Scope regressions for the expanded-corpus scorer, not analyzer accuracy."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'analysis_legacy'))
from .evaluate_reviewed import adapt_extra, score_extra


class ReferenceScopeTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(sha256='a'*64, sample_rate=1000, sample_frames=20000)
        self.accepted = dict(quarter_bpm=120., first_beat_source_seconds=2.,
                             support_seconds=[2.,10.], meter=dict(numerator=4,denominator=4))
        self.reference, _, _ = adapt_extra(self.accepted, self.source)
        self.extended = deepcopy(self.reference)
        self.extended['clock_knots'] = [dict(pulse=-4.,source_seconds=0.),dict(pulse=36.,source_seconds=20.)]
        self.extended['support_seconds'] = [[0.,20.]]
        self.extended['meter_events'][0]['pulse'] = -4.

    def test_unknown_margin_does_not_become_false_no_grid(self):
        score = score_extra(self.reference, {'map':self.extended}, None, True)
        self.assertTrue(score['all_gates_pass'])
        self.assertTrue(score['unknown_outside_reference_support_excluded'])

    def test_known_no_grid_tail_penalizes_extra_clicks_and_support(self):
        score = score_extra(self.reference, {'map':self.extended}, [10.,20.], False)
        self.assertFalse(score['all_gates_pass'])
        self.assertFalse(score['gates']['no_grid_in_free_ending'])
        self.assertEqual(score['free_tail_false_positives']['quarter_beats'],20)
        self.assertEqual(score['free_tail_false_positives']['declared_map_support_seconds'],10.)

    def test_missing_known_grid_is_not_hidden_by_scope_clipping(self):
        partial = deepcopy(self.reference); partial['support_seconds'] = [[2.,6.]]
        score = score_extra(self.reference, {'map':partial}, None, True)
        self.assertFalse(score['all_gates_pass'])
        self.assertAlmostEqual(score['scores']['quarter_bpm_time_within_1'],.5)


if __name__=='__main__': unittest.main()
