"""Regression checks for independent timing and notation."""
import unittest
import numpy as np

from .clock import fit_clock, quarters_at, seconds_at
from .timeline import event_peaks, interpret_bars
from .legacy_export import export_map
from .prediction import analyse


class PhysicalTimingTests(unittest.TestCase):
    def test_unresolved_notation_preserves_timeline_without_a_fallback(self):
        frames=np.arange(500)/50
        quarter=np.max(np.exp(-.5*((frames[:,None]-np.arange(0.,10.,.5))/.03)**2),axis=1)
        denominator=np.zeros((len(frames),5));denominator[:,1]=1.
        fields=dict(quarter=quarter,bar=np.zeros(len(frames)),grid=np.ones(len(frames)),
                    quarter_bpm=np.full(len(frames),120.),denominator=denominator)
        result=analyse(fields,dict(sha256='a'*64,sample_rate=44100,sample_frames=441000))
        self.assertEqual(result['status'],'decode_failed')
        self.assertEqual(result['stage'],'notation')
        self.assertIsNone(result['map'])
        self.assertFalse(result['fallback_used'])
        self.assertEqual(result['physical_timeline']['clock']['segment_count'],1)
        self.assertGreater(len(result['physical_timeline']['quarter_events']),10)

    def test_missing_clock_reports_failure_without_inventing_timing(self):
        result=analyse(dict(quarter=np.zeros(100),quarter_bpm=np.full(100,120.)),
                       dict(sha256='a'*64,sample_rate=50,sample_frames=100))
        self.assertEqual(result['status'],'decode_failed')
        self.assertEqual(result['stage'],'clock')
        self.assertIsNone(result['physical_timeline'])
        self.assertIsNone(result['map'])
        self.assertFalse(result['fallback_used'])

    def test_constant_clock_has_no_false_change(self):
        q = np.arange(100.)
        t = .123+q*.5
        clock = fit_clock(t, np.full(len(q), 120.))
        self.assertEqual(clock['segment_count'], 1)
        np.testing.assert_allclose(seconds_at(clock['knots'], q), t, atol=1e-10)
        np.testing.assert_allclose(quarters_at(clock['knots'], t), q, atol=1e-10)

    def test_missing_quarter_preserves_count(self):
        t = np.delete(np.arange(30.)*.5, [5, 11, 12])
        clock = fit_clock(t, np.full(len(t), 120.))
        self.assertEqual(clock['event_quarters'][-1], 29.)
        self.assertEqual(clock['segment_count'], 1)

    def test_dense_eighth_events_do_not_double_quarter_rate(self):
        t = np.arange(60.)*.25
        clock = fit_clock(t, np.full(len(t), 120.))
        self.assertEqual(clock['event_quarters'][-1], 29.5)
        self.assertEqual(clock['segment_count'], 1)
        self.assertAlmostEqual(float(seconds_at(clock['knots'], 10.)), 5.)

    def test_dotted_pulse_observations_keep_quarter_unit(self):
        t=np.arange(40.)*.75
        clock=fit_clock(t,np.full(len(t),120.))
        self.assertEqual(clock['event_quarters'][-1],58.5)
        self.assertAlmostEqual(float(seconds_at(clock['knots'],10.)),5.)

    def test_bar_only_observations_can_interpolate_missing_quarters(self):
        t=np.arange(20.)*2
        clock=fit_clock(t,np.full(len(t),120.))
        self.assertEqual(clock['event_quarters'][-1],76.)
        self.assertAlmostEqual(float(seconds_at(clock['knots'],10.)),5.)

    def test_quarter_score_selects_half_quarter_phase(self):
        t = .25+np.arange(60.)*.25
        strengths = np.where(np.arange(60)%2, .95, .6)
        clock = fit_clock(t, np.full(len(t), 120.), strengths=strengths)
        self.assertEqual(clock['event_quarters'][0], -.5)
        self.assertAlmostEqual(float(seconds_at(clock['knots'], 0.)), .5)

    def test_within_bar_tempo_change_is_continuous(self):
        q = np.arange(60.)
        t = q*.5+np.maximum(q-17., 0.)*.1
        rates = np.where(q < 17., 120., 100.)
        clock = fit_clock(t, rates)
        self.assertEqual(clock['segment_count'], 2)
        np.testing.assert_allclose(seconds_at(clock['knots'], q), t, atol=1e-8)
        self.assertAlmostEqual(clock['knots'][1]['quarter'], 17., places=6)

    def test_one_peak_per_broad_lobe(self):
        times = np.arange(200)/50
        y = np.exp(-.5*((times-1)/.12)**2)
        peaks, _ = event_peaks(y)
        self.assertEqual(len(peaks), 1)
        self.assertAlmostEqual(peaks[0], 1.)

    def test_meter_hypotheses_cannot_move_physical_timing(self):
        clock = fit_clock(np.arange(30.)*.5, np.full(30, 120.))
        starts = np.array([0., 1.5, 3., 4.5])
        first = np.zeros((300, 5)); first[:, 1] = 1.
        second = np.zeros((300, 5)); second[:, 2] = 1.
        a = interpret_bars(clock, starts, first)
        b = interpret_bars(clock, starts, second)
        self.assertEqual(a[0]['signature']['numerator'], 3)
        self.assertEqual(a[0]['signature']['denominator'], 4)
        self.assertEqual(b[0]['signature']['numerator'], 6)
        self.assertEqual(b[0]['signature']['denominator'], 8)
        self.assertEqual([r['seconds'] for r in a], [r['seconds'] for r in b])
        self.assertEqual([r['quarter'] for r in a], [r['quarter'] for r in b])
        self.assertFalse(clock['meter_used'])

    def test_export_has_exact_source_endpoints(self):
        clock = fit_clock(.123+np.arange(30.)*.5, np.full(30,120.))
        probabilities = np.zeros((800,5));probabilities[:,1]=1.
        bars = interpret_bars(clock,np.array([.123,2.123,4.123]),probabilities)
        timeline=dict(source=dict(sha256='a'*64,sample_rate=44100,sample_frames=44100*16),clock=clock,bar_events=bars,grid_support_seconds=[[0.,16.]])
        m,_=export_map(timeline)
        self.assertEqual(m['clock_knots'][0]['source_seconds'],0.)
        self.assertEqual(m['clock_knots'][-1]['source_seconds'],16.)
        self.assertLessEqual(m['meter_events'][0]['pulse'],m['clock_knots'][0]['pulse'])
        self.assertAlmostEqual(m['bar_anchor_pulse'],bars[0]['quarter'])


if __name__ == '__main__':unittest.main()
