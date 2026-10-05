import unittest

import numpy as np

from audit_source_alignment import AlignmentConfig, audit, correlations


class SourceAlignmentTests(unittest.TestCase):
    def test_silent_search_windows_cannot_become_correlation_peaks(self):
        rng=np.random.default_rng(91);target=rng.normal(size=127)
        source=np.r_[rng.normal(size=500),np.zeros(2000),target,np.zeros(1000)]
        scores=correlations(source,target)
        self.assertTrue(np.isfinite(scores).all())
        self.assertLessEqual(float(np.max(np.abs(scores))),1)
        np.testing.assert_array_equal(scores[500:2500-len(target)+1],0)
        self.assertEqual(int(np.argmax(scores)),2500)
        self.assertAlmostEqual(float(scores[2500]),1,places=9)
        np.testing.assert_array_equal(correlations(source,np.zeros(127)),0)
        np.testing.assert_array_equal(correlations(np.zeros(500),target),0)
        quiet=correlations(source*1e-8,target*1e-8)
        self.assertEqual(int(np.argmax(quiet)),2500)
        self.assertAlmostEqual(float(quiet[2500]),1,places=9)

    def test_known_trim_survives_unrelated_mix_component(self):
        rng = np.random.default_rng(43)
        stem = rng.normal(size=70_000)
        mix = .6*stem[375:] + .4*rng.normal(size=len(stem)-375)
        result = audit(mix, stem, 1000)
        self.assertTrue(result['qualified_constant_offset'])
        self.assertEqual(result['stem_minus_mix_frames'], 375)
        self.assertEqual(result['eligible_frame_spread'], 0)

    def test_nondivisible_search_margin_retains_first_window_and_true_offset(self):
        rate = 44_100
        margin = round(.012*rate)
        hop = round(rate/1000)
        self.assertNotEqual(margin % hop, 0)
        rng = np.random.default_rng(44)
        mix = rng.normal(size=rate).astype('float32')
        stem = np.r_[np.zeros(88, dtype='float32'), mix]
        result = audit(mix, stem, rate, AlignmentConfig(
            windows=3, window_seconds=.02, maximum_offset_seconds=.012,
            minimum_correlation=.9, minimum_agreeing_windows=3,
            maximum_frame_spread=0))
        self.assertEqual(len(result['windows']), 3)
        self.assertGreaterEqual(result['windows'][0]['mix_start_frame'], margin)
        self.assertTrue(result['qualified_constant_offset'])
        self.assertEqual(result['stem_minus_mix_frames'], 88)
        self.assertEqual(result['eligible_frame_spread'], 0)

    def test_nonconstant_time_mapping_is_not_admitted(self):
        rng = np.random.default_rng(23)
        stem = rng.normal(size=70_000)
        positions = np.arange(68_000, dtype=float)*1.0002+375
        mix = np.interp(positions, np.arange(len(stem)), stem)
        result = audit(mix, stem, 1000)
        self.assertFalse(result['qualified_constant_offset'])
        self.assertGreater(result['eligible_frame_spread'], 2)

    def test_unrelated_recordings_are_not_admitted(self):
        rng = np.random.default_rng(29)
        result = audit(rng.normal(size=70_000), rng.normal(size=70_000), 1000)
        self.assertFalse(result['qualified_constant_offset'])
        self.assertIsNone(result['stem_minus_mix_frames'])


if __name__ == '__main__':
    unittest.main()
