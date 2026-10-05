"""Constructed false-positive and coherent-short-bar checks."""
import unittest
from unittest.mock import patch

import numpy as np

from experiments.tempo_meter_v2.phrase_meter import (
    phrase15_trigger, propose_repeated_short_bars)


class PhraseMeterTests(unittest.TestCase):
    def setUp(self):
        self.sample_rate = 48000
        self.duration = 20.
        self.phase = .05
        self.period = 60/190
        self.grid = self.phase + np.arange(63)*self.period
        source = {"sha256":"0"*64,"sample_rate":self.sample_rate,
                  "sample_frames":int(self.duration*self.sample_rate)}
        self.base = {"status":"proposed_map",
            "map":{"schema_version":1,"source":source,
                "clock_knots":[{"pulse":0.,"source_seconds":self.phase},
                               {"pulse":(self.duration-self.phase)/self.period,
                                "source_seconds":self.duration}],
                "quarters_per_pulse":{"numerator":1,"denominator":1},
                "bar_anchor_pulse":0.,
                "meter_events":[{"pulse":0.,"numerator":4,"denominator":4,
                                 "grouping":[1,1,1,1],"bar_action":"continue"}],
                "support_seconds":[[self.phase,self.duration]],
                "analysis_condition":"unhinted","shared_origin_id":None},
            "beat_times_seconds":self.grid.tolist(),"bar_starts_seconds":[],
            "diagnostics":{"constant_grid_only":True}}
        self.phrase={"lag14":np.array([.7]),"lag15":np.array([.96]),
                     "lag16":np.array([.72])}
        self.downbeat=np.full(1000,-6.,dtype=float)
        for beat in (0,4,8):
            self.downbeat[round(self.grid[beat]*50)]=6.
        self.paths={name:name for name in ("mix","drums","bass","other")}
        self.geometry={"sample_rate":self.sample_rate,
                       "sample_frames":int(self.duration*self.sample_rate)}

    def test_nondistinct_phrase_abstains_before_reading_stems(self):
        active,_=phrase15_trigger({"lag14":np.array([.95]),
                                   "lag15":np.array([.96]),
                                   "lag16":np.array([.94])})
        self.assertFalse(active)
        with patch("experiments.tempo_meter_v2.phrase_meter.low_frequency_attacks") as attack:
            proposal,diag=propose_repeated_short_bars(
                self.base,self.downbeat,50.,
                {"lag14":np.array([.95]),"lag15":np.array([.96]),
                 "lag16":np.array([.94])},self.paths)
            self.assertIsNone(proposal)
            self.assertFalse(diag["accepted"])
            attack.assert_not_called()

    def test_strong_phrase_without_bar_cue_abstains(self):
        with patch("experiments.tempo_meter_v2.phrase_meter.low_frequency_attacks",
                   return_value=(np.zeros(44),self.geometry)):
            proposal,diag=propose_repeated_short_bars(
                self.base,self.downbeat,50.,self.phrase,self.paths)
        self.assertIsNone(proposal)
        self.assertEqual(diag["reason"],"weak_multiview_short_bar_consensus")
        self.assertEqual(diag["view_count"],36)

    def test_coherent_derived_attacks_render_two_short_bars(self):
        strength=np.zeros(44)
        strength[[0,4,8,12,16,19,23,27,31,34,38,42]]=1.
        with patch("experiments.tempo_meter_v2.phrase_meter.low_frequency_attacks",
                   return_value=(strength,self.geometry)):
            proposal,diag=propose_repeated_short_bars(
                self.base,self.downbeat,50.,self.phrase,self.paths)
        self.assertTrue(diag["accepted"])
        self.assertEqual(diag["view_win_count"],36)
        self.assertEqual([e["pulse"] for e in proposal["map"]["meter_events"]],
                         [0.,16.,19.,31.,34.])
        self.assertEqual([e["numerator"] for e in proposal["map"]["meter_events"]],
                         [4,3,4,3,4])
        self.assertGreater(len(proposal["bar_starts_seconds"]),15)


if __name__ == "__main__":
    unittest.main()
