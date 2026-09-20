import unittest

import numpy as np

from run_beat_this import render_clicks, span_pulse_rate, validate_events


class BaselineOutputTests(unittest.TestCase):
    def test_invalid_events_are_rejected(self):
        for events in [[-0.1], [0.2, 0.1], [0.1, 0.1], [float("nan")]]:
            with self.subTest(events=events), self.assertRaises(ValueError):
                validate_events(events)

    def test_clicks_use_absolute_samples_and_do_not_wrap_at_end(self):
        clicks, skipped = render_clicks([0.1, 0.4, 1.0], [0.4], 8000, 8000)
        self.assertEqual(len(clicks), 8000)
        self.assertEqual(skipped, 1)
        self.assertEqual(np.flatnonzero(clicks)[0], 800)
        self.assertAlmostEqual(float(clicks[800]), 0.18, places=6)
        self.assertAlmostEqual(float(clicks[3200]), 0.30, places=6)
        self.assertTrue(np.all(clicks[:800] == 0))

    def test_empty_predictions_make_a_silent_click_track(self):
        clicks, skipped = render_clicks([], [], 8000, 8000)
        self.assertEqual(skipped, 0)
        self.assertTrue(np.all(clicks == 0))

    def test_diagnostic_span_rate_preserves_half_tempo_interpretation(self):
        times, rates = span_pulse_rate(np.arange(40) * 0.6)
        self.assertEqual(len(times), 24)
        np.testing.assert_allclose(rates, 100)
        short_times, short_rates = span_pulse_rate([0, 0.6])
        self.assertEqual(len(short_times), 0)
        self.assertEqual(len(short_rates), 0)


if __name__ == "__main__":
    unittest.main()
