import unittest

import numpy as np

from decode_bar_structure import bar_path
from bar_metrics import score_bar_changes


class BarStructureTests(unittest.TestCase):
    def test_repeated_signature_declaration_is_not_a_meter_change(self):
        reference={'evaluation_support_seconds':[1,20], 'downbeats_seconds':[1,3,5],
                   'meter_events':[{'time_seconds':0,'numerator':4,'denominator':4},
                                   {'time_seconds':3,'numerator':4,'denominator':4},
                                   {'time_seconds':10,'numerator':3,'denominator':4}]}
        bars={'meter_events':[{'time_seconds':1,'pulses_per_bar':4},
                              {'time_seconds':3,'pulses_per_bar':4},
                              {'time_seconds':10,'pulses_per_bar':3}]}
        score=score_bar_changes(reference,bars)
        self.assertEqual(score['reference_change_count'],1)
        self.assertEqual(score['predicted_change_count'],1)
        self.assertEqual(score['matched_count'],1)

    def test_change_outside_support_does_not_inflate_misses(self):
        reference={'evaluation_support_seconds':[2,20], 'downbeats_seconds':[2,4],
                   'meter_events':[{'time_seconds':0,'numerator':3,'denominator':4},
                                   {'time_seconds':1,'numerator':4,'denominator':4}]}
        bars={'meter_events':[{'time_seconds':2,'pulses_per_bar':4}]}
        score=score_bar_changes(reference,bars)
        self.assertEqual(score['reference_change_count'],0)
        self.assertEqual(score['false_changes_on_constant_meter'],0)

    def test_late_phase_adjustment_does_not_count_as_correct_meter_change(self):
        reference={'evaluation_support_seconds':[0,30], 'downbeats_seconds':[0,2,4],
                   'meter_events':[{'time_seconds':0,'numerator':4,'denominator':4},
                                   {'time_seconds':10,'numerator':2,'denominator':4},
                                   {'time_seconds':11,'numerator':4,'denominator':4}]}
        bars={'meter_events':[{'time_seconds':0,'pulses_per_bar':4},
                              {'time_seconds':14,'pulses_per_bar':2},
                              {'time_seconds':15,'pulses_per_bar':4}]}
        self.assertEqual(score_bar_changes(reference,bars)['matched_count'],0)

    def test_one_short_bar_is_preserved_without_moving_tempo(self):
        grid=np.arange(40)*.5
        original=grid.copy()
        starts=[0,4,8,12,14,18,22,26,30,34,38]
        logits=np.full(1000,-8.)
        logits[np.rint(grid[starts]*50).astype(int)]=8.
        result=bar_path(grid,logits)
        self.assertEqual(result['bar_start_pulse_indices'],starts)
        self.assertEqual([(e['pulse_index'],e['pulses_per_bar']) for e in result['meter_events']],[(0,4),(12,2),(14,4)])
        np.testing.assert_array_equal(grid,original)
        self.assertFalse(result['pulse_times_changed'])
        self.assertIsNone(result['meter_events'][0]['quarter_note_denominator'])

    def test_constant_four_pulse_bars_do_not_gain_extra_meter_changes(self):
        grid=.13+np.arange(64)*.47
        logits=np.full(1600,-6.)
        logits[np.rint(grid[::4]*50).astype(int)]=7.
        result=bar_path(grid,logits)
        self.assertEqual(len(result['meter_events']),1)
        self.assertEqual(result['meter_events'][0]['pulses_per_bar'],4)

    def test_fixed_control_cannot_change_bar_length(self):
        grid=np.arange(40)*.5
        logits=np.full(1000,-8.)
        logits[np.array([0,4,8,12,14,18,22,26,30,34,38])*25]=8.
        result=bar_path(grid,logits,variable=False)
        self.assertEqual(len(result['meter_events']),1)


if __name__=='__main__':unittest.main()
