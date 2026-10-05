"""Checks for the selective BPM route's acceptance and abstention boundaries."""
from __future__ import annotations

import unittest

from experiments.tempo_meter_v2.plausible_bpm import _events, _rates, snap_prediction


def fixture(rates: list[float], spans: list[float]) -> dict:
    assert len(rates) == len(spans)
    knots = [{"pulse": 0.0, "source_seconds": 0.0}]
    for rate, seconds in zip(rates, spans):
        previous = knots[-1]
        knots.append({
            "pulse": previous["pulse"] + seconds * rate / 60,
            "source_seconds": previous["source_seconds"] + seconds,
        })
    duration = sum(spans)
    return {
        "status": "proposed_map",
        "map": {
            "schema_version": 1,
            "source": {
                "sha256": "0" * 64, "sample_rate": 48000,
                "sample_frames": round(duration * 48000),
            },
            "clock_knots": knots,
            "quarters_per_pulse": {"numerator": 1, "denominator": 1},
            "bar_anchor_pulse": 0.0,
            "meter_events": [{
                "pulse": 0.0, "numerator": 4, "denominator": 4,
                "grouping": [1, 1, 1, 1], "bar_action": "continue",
            }],
            "support_seconds": [[0.0, duration]],
            "analysis_condition": "unhinted",
            "shared_origin_id": None,
        },
        "diagnostics": {},
    }


class PlausibleBpmTests(unittest.TestCase):
    def test_near_integer_and_half_rates_change_real_click_grid(self):
        integer = fixture([139.999], [180.0])
        clean, decision = snap_prediction(integer)
        self.assertTrue(decision["accepted"])
        self.assertAlmostEqual(_rates(clean["map"])[0], 140.0)
        self.assertNotEqual(clean["beat_times_seconds"], _events(integer["map"])[0])
        self.assertEqual(integer["map"]["clock_knots"][0]["source_seconds"], 0.0)
        half = fixture([120.49], [120.0])
        clean, decision = snap_prediction(half)
        self.assertTrue(decision["accepted"])
        self.assertEqual(decision["segments"][0]["kind"], "half")
        self.assertAlmostEqual(_rates(clean["map"])[0], 120.5)

    def test_fractional_rate_and_long_song_drift_abstain(self):
        fractional = fixture([120.25], [300.0])
        same, decision = snap_prediction(fractional)
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["reason"], "already_clean_or_no_nearby_candidate")
        self.assertIs(same, fractional)
        drifting = fixture([120.08], [300.1])
        same, decision = snap_prediction(drifting)
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["reason"], "whole_song_drift_exceeds_budget")
        self.assertGreater(decision["observed_maximum_event_shift_seconds"], .035)
        self.assertIs(same, drifting)

    def test_selected_tempo_change_is_not_erased(self):
        step = fixture([120.02, 119.99], [20.0, 20.0])
        same, decision = snap_prediction(step)
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["reason"], "tempo_step_would_change")
        self.assertIs(same, step)


if __name__ == "__main__":
    unittest.main()
