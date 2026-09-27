import unittest

import numpy as np

from analyze_onsets import nearby_attacks, periodicity_candidates, rank_periodic_levels, spectral_flux
from synthetic_groove import event_metrics, generate
from audio_support import nonzero_support, supported_prediction


class EvidenceTests(unittest.TestCase):
    def test_support_filter_preserves_internal_rests_and_absolute_time(self):
        audio = np.zeros((600,2))
        audio[100,0], audio[499,1] = .1, 1e-12
        support = nonzero_support(audio, 100)
        self.assertEqual(support, [100,500])
        prediction = {"beats_seconds": [.1,1.,2.,3.,4.,5.5], "downbeats_seconds": [1.,4.],
                      "beat_numbers": [4,1,2,3,1,2]}
        filtered = supported_prediction(prediction, support, 100)
        self.assertEqual(filtered["beats_seconds"], [1.,2.,3.,4.])
        self.assertEqual(filtered["downbeats_seconds"], [1.,4.])
        self.assertEqual(prediction["beats_seconds"][0], .1)
        self.assertEqual(filtered["audio_support_filter"]["source_shift_seconds"], 0)
        silent = nonzero_support(np.zeros(100), 100)
        self.assertIsNone(silent)
        self.assertEqual(supported_prediction(prediction, silent, 100)["beats_seconds"], [])

    def test_silent_audio_does_not_invent_a_preferred_period_or_move_events(self):
        times, features = spectral_flux(np.zeros(22050*30), 22050)
        windows = periodicity_candidates(times, features)
        clock = {"segments": [{"start_seconds": 0, "end_seconds": 30, "pulse_rate_per_minute": 100}]}
        self.assertIsNone(rank_periodic_levels(windows, clock)["preferred_periodicity_factor"])
        grid = np.array([.14, .74, 1.34])
        refined, strength = nearby_attacks(times, features, grid)
        np.testing.assert_array_equal(refined, grid)
        self.assertTrue(np.all(strength == 0))

    def test_centered_features_preserve_an_impulse_neighborhood(self):
        audio = np.zeros(22050*2)
        audio[22050] = 1
        times, features = spectral_flux(audio, 22050)
        peak = times[np.argmax(features.sum(axis=1))]
        self.assertLess(abs(peak-1), .025)

    def test_one_prediction_cannot_match_two_reference_events(self):
        result = event_metrics([1, 1.1], [1.05], .07)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["precision"], 1)
        self.assertEqual(result["recall"], .5)

    def test_half_tempo_is_penalized_not_silently_forgiven(self):
        result = event_metrics(np.arange(20)*.3, np.arange(10)*.6, .07)
        self.assertEqual(result["precision"], 1)
        self.assertEqual(result["recall"], .5)

    def test_changed_subdivisions_preserve_the_same_quarter_note_labels(self):
        audio_a, a = generate("eighths")
        audio_b, b = generate("sixteenths")
        self.assertEqual(a["beats_seconds"], b["beats_seconds"])
        self.assertEqual(a["downbeats_seconds"], b["downbeats_seconds"])
        self.assertEqual([e["numerator"] for e in a["meter_events"]], [4,3,4])
        self.assertEqual(len(audio_a), len(audio_b))
        self.assertTrue(np.all(audio_a[:a["first_event_sample"]] == 0))
        self.assertTrue(np.max(np.abs(audio_a)) <= .951)


if __name__ == "__main__":
    unittest.main()
