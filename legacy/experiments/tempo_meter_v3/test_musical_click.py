import unittest
from .musical_click import musical_events


class MusicalClickTests(unittest.TestCase):
    def raw(self,n,d,groups=None):
        return dict(schema_version=1,source=dict(sha256='a'*64,sample_rate=1000,sample_frames=4000),
                    clock_knots=[dict(pulse=0.,source_seconds=0.),dict(pulse=6.4,source_seconds=4.)],
                    quarters_per_pulse=dict(numerator=1,denominator=1),bar_anchor_pulse=0.,
                    meter_events=[dict(pulse=0.,numerator=n,denominator=d,grouping=groups,bar_action='continue')],
                    support_seconds=[[0.,4.]],analysis_condition='unhinted',shared_origin_id=None)

    def test_compound_pulse_and_last_partial_bar(self):
        result=musical_events(self.raw(6,8,[3,3]))
        self.assertEqual(result['meter_beats'],[0.,.9375,1.875,2.8125,3.75])
        self.assertEqual(result['meter_bars'],[0.,1.875,3.75])

    def test_six_four_does_not_get_reference_compound_correction(self):
        result=musical_events(self.raw(6,4))
        self.assertEqual(result['meter_beats'],[0.,.625,1.25,1.875,2.5,3.125,3.75])
        self.assertEqual(result['meter_bars'],[0.,3.75])

    def test_no_grid_tail_is_not_filled(self):
        raw=self.raw(6,8,[3,3]);raw['support_seconds']=[[0.,1.875]]
        result=musical_events(raw);self.assertEqual(result['meter_beats'],[0.,.9375]);self.assertEqual(result['meter_bars'],[0.])


if __name__=='__main__':unittest.main()
