"""Behavioral controls for source-only variable tempo, pulse unit and ending."""
import unittest

import numpy as np

from experiments.tempo_meter_v2.barwise_tempo import propose_barwise_tempo
from experiments.tempo_meter_v2.compound_meter import propose_compound_6_8
from experiments.tempo_meter_v2.tail_support import propose_tail_stop
from music_map_contract import prepare_map, render_bars


SOURCE = {'sha256': 'a' * 64, 'sample_rate': 1000, 'sample_frames': 300000}


def base_map(bpm=108., meter=4, duration=300., phase=.1, anchor=0.):
    duration = int(np.ceil(duration * 1000)) / 1000
    source = {**SOURCE, 'sample_frames': int(round(duration * 1000))}
    value = {'schema_version': 1, 'source': source,
             'clock_knots': [{'pulse': 0., 'source_seconds': phase},
                             {'pulse': (duration-phase)*bpm/60, 'source_seconds': duration}],
             'quarters_per_pulse': {'numerator': 1, 'denominator': 1},
             'bar_anchor_pulse': anchor,
             'meter_events': [{'pulse': 0., 'numerator': meter, 'denominator': 4,
                               'grouping': [1]*meter, 'bar_action': 'continue'}],
             'support_seconds': [[phase, duration]], 'analysis_condition': 'unhinted',
             'shared_origin_id': None}
    return {'schema_version': 1, 'status': 'proposed_map', 'map': value,
            'diagnostics': {'constant_grid_only': True}}


class GenericMapTests(unittest.TestCase):
    def test_four_tempo_changes_survive_missing_and_extra_events(self):
        # Five stable 4/4 sections with 32, 20, 24, 36, 16 bars.
        periods = [240/102, 240/110, 240/102, 240/110, 240/102]
        lengths = [32, 20, 24, 36, 16]
        bars = [.9]
        for period, count in zip(periods, lengths):
            for _ in range(count):
                bars.append(bars[-1]+period)
        bars = np.asarray(bars)
        # Small observation jitter, one missing true bar, one false half-bar.
        jitter = .012*np.sin(np.arange(len(bars))*1.7)
        observations = np.delete(bars+jitter, 9)
        observations = np.sort(np.r_[observations, bars[14]+.6])
        beats=[]
        for a,b in zip(bars,bars[1:]):
            beats.extend(a+(b-a)*np.arange(4)/4)
        prediction, decision = propose_barwise_tempo(
            base_map(106.,duration=bars[-1]+.3,phase=.1), beats, observations)
        self.assertTrue(decision['accepted'], decision)
        self.assertEqual(decision['change_count'], 4)
        times=[k['source_seconds'] for k in prediction['map']['clock_knots'][2:-1]]
        expected=[bars[32],bars[52],bars[76],bars[112]]
        self.assertEqual(len(times),4)
        self.assertTrue(all(abs(a-b)<.1 for a,b in zip(times,expected)))

    def test_stable_song_does_not_invent_tempo_changes(self):
        bars=.9+np.arange(121)*2.4
        noisy=bars+.012*np.sin(np.arange(len(bars))*1.7)
        beats=np.array([.9+i*.6 for i in range(481)])
        base=base_map(100.,duration=290.,phase=.3)
        result,decision=propose_barwise_tempo(base,beats,noisy)
        self.assertFalse(decision['accepted'])
        self.assertEqual(result,base)

    def test_compound_pulse_requires_three_fine_intervals(self):
        base=base_map(192.,meter=6,duration=120.,phase=.01,anchor=2.)
        dotted=np.arange(.94,115.,.9375)
        result,decision=propose_compound_6_8(base,dotted.tolist())
        self.assertTrue(decision['accepted'])
        self.assertEqual((result['map']['meter_events'][0]['numerator'],
                          result['map']['meter_events'][0]['denominator']),(6,8))
        period=((result['map']['clock_knots'][-1]['source_seconds']-
                 result['map']['clock_knots'][0]['source_seconds'])/
                (result['map']['clock_knots'][-1]['pulse']-
                 result['map']['clock_knots'][0]['pulse']))
        self.assertAlmostEqual(60/period,96.,places=3)
        unchanged,other=propose_compound_6_8(base,np.arange(.32,115.,.3125).tolist())
        self.assertFalse(other['accepted'])
        self.assertEqual(unchanged,base)

    def test_tail_requires_beat_and_downbeat_disruption(self):
        base=base_map(192.,meter=6,duration=120.,phase=.01,anchor=2.)
        grid=render_bars(prepare_map(base['map']))['bar_events_seconds']
        stop=min(grid,key=lambda t:abs(t-94.4))
        regular=np.arange(.01,stop+4.,.3125)
        chaos=np.arange(stop+4.,120.,.13)
        raw_beats=np.sort(np.r_[regular,chaos])
        kept_bars=[t for t in grid if t<stop+4]
        result,decision=propose_tail_stop(base,base,raw_beats.tolist(),kept_bars)
        self.assertTrue(decision['accepted'],decision)
        self.assertLess(abs(result['map']['support_seconds'][0][1]-stop),.5)
        # Dense short beat events alone cannot authorize a grid stop.
        unchanged,control=propose_tail_stop(base,base,raw_beats.tolist(),grid)
        self.assertFalse(control['accepted'])
        self.assertEqual(unchanged,base)


if __name__=='__main__':
    unittest.main()
