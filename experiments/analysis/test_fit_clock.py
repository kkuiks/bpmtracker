import unittest

import numpy as np

from evaluate_clock import synthetic_events
from fit_clock import clock_time, fit_clock, grid_events


class ClockFittingTests(unittest.TestCase):
    def test_continuous_selection_recovers_a_brief_excursion_hidden_as_a_phase_jump(self):
        truth, observed, changes = synthetic_events([205,210,205], [160,4,160], .1, 97,
                                                    jitter_seconds=0, quantization_hz=None)
        result = fit_clock(observed, min_events=3, split_penalty=.001, continuous_selection=True)
        self.assertEqual(len(result["segments"]), 3)
        self.assertEqual(len(result["initial_segmentation_indices"])-1, 2)
        self.assertLess(np.max(np.abs(grid_events(result)-truth)), .001)
        predicted = [s["start_seconds"] for s in result["segments"][1:]]
        self.assertLess(np.max(np.abs(predicted-changes)), .1)

    def test_constant_clock_has_no_spurious_changes_and_preserves_origin(self):
        truth, observed, _ = synthetic_events([137.3], [360], .173, 2026)
        result = fit_clock(observed)
        self.assertEqual(len(result["segments"]), 1)
        self.assertAlmostEqual(result["segments"][0]["pulse_rate_per_minute"], 137.3, delta=.02)
        self.assertLess(np.max(np.abs(grid_events(result) - truth)), .005)
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["meter"])

    def test_small_changes_recovered_without_octave_folding(self):
        truth, observed, changes = synthetic_events([205, 210, 205], [160, 80, 160], .23, 48)
        result = fit_clock(observed)
        self.assertEqual(len(result["segments"]), 3)
        for expected, segment in zip([205, 210, 205], result["segments"]):
            self.assertAlmostEqual(segment["pulse_rate_per_minute"], expected, delta=.15)
        predicted = [s["start_seconds"] for s in result["segments"][1:]]
        self.assertLess(np.max(np.abs(predicted-changes)), .6)
        self.assertLess(np.quantile(np.abs(grid_events(result)-truth), .95), .005)

    def test_missing_event_flags_indexing_risk(self):
        _, observed, _ = synthetic_events([120], [100], .1, 1, jitter_seconds=0)
        result = fit_clock(np.delete(observed, 48))
        self.assertEqual(result["status"], "event_indexing_or_fit_requires_review")
        self.assertTrue(result["diagnostics"]["suspicious_interval_indices"])

    def test_interpretations_share_one_clock_without_moving_original_pulses(self):
        _, observed, _ = synthetic_events([102.5, 105], [160, 80], .089, 2)
        result = fit_clock(observed)
        regular, doubled = grid_events(result), grid_events(result, 2)
        np.testing.assert_allclose(doubled[::2], regular, atol=1e-12)
        self.assertLess(result["segments"][0]["pulse_rate_per_minute"], 103)
        for knot in result["knot_pulse_indices"]:
            around = clock_time([knot-1e-8, knot+1e-8], result["knot_pulse_indices"], result["coefficients"])
            self.assertGreater(around[1], around[0])
            self.assertLess(around[1]-around[0], 1e-7)

    def test_invalid_sequence_and_fit_parameters(self):
        for events in ([], [0, .5], [0, 1, float("nan")], [0, .5, .4]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                fit_clock(events)
        for penalty in (-1, 0, float("nan")):
            with self.subTest(penalty=penalty), self.assertRaises(ValueError):
                fit_clock(np.arange(50)*.5, split_penalty=penalty)


if __name__ == "__main__":
    unittest.main()
