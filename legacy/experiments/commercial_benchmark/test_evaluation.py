from copy import deepcopy
import unittest

from .evaluate import physical_score


def clock(rate, *, jitter=False, meter=True):
    source=dict(sha256='0'*64,sample_rate=48000,sample_frames=144000)
    knots=[dict(pulse=0.,source_seconds=0.),dict(pulse=2.,source_seconds=1.)]
    knots.append(dict(pulse=2+(3-1)*(rate+(0.001 if jitter else 0))/60,source_seconds=3.))
    return dict(schema_version=1,source=source,clock_knots=knots,
                quarters_per_pulse=dict(numerator=1,denominator=1),
                bar_anchor_pulse=0. if meter else None,
                meter_events=[dict(pulse=0.,numerator=4,denominator=4,grouping=None,bar_action='continue')] if meter else None,
                support_seconds=[[0.,3.]],analysis_condition='constructed_fixture',shared_origin_id=None)


class PhysicalScoringTests(unittest.TestCase):
    def test_correct_clock_cannot_pass_full_task_without_meter(self):
        result=physical_score(clock(120),clock(120,meter=False),{})
        self.assertTrue(result['clock_gates_pass'])
        self.assertFalse(result['all_gates_pass'])
        self.assertEqual(len(result['unavailable_required_gates']),3)
        self.assertTrue(all(result['scores'][k] is None for k in result['unavailable_required_gates']))

    def test_constant_reference_penalizes_even_small_false_tempo_change(self):
        result=physical_score(clock(120),clock(120,jitter=True,meter=False),{})
        self.assertEqual(result['scores']['quarter_bpm_time_within_1'],1.)
        self.assertEqual(result['tempo_change_counts']['false_positives'],1)
        self.assertEqual(result['scores']['tempo_change_f1_or_no_false_positives_500ms'],0.)

    def test_free_tail_grid_is_not_hidden_by_reference_scope(self):
        ref=clock(120);ref['support_seconds']=[[0.,2.]]
        result=physical_score(ref,clock(120,meter=False),{'free_time_seconds':[2.,3.]})
        self.assertEqual(result['free_tail_false_positives']['quarter_beats'],2)
        self.assertFalse(result['gates']['no_grid_in_free_ending'])
        self.assertFalse(result['gates']['grid_end_within_500ms'])


if __name__=='__main__':unittest.main()
