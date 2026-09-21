import unittest

import numpy as np

from audit_source_alignment import audit


class SourceAlignmentTests(unittest.TestCase):
    def test_known_trim_survives_unrelated_mix_component(self):
        rng = np.random.default_rng(43)
        stem = rng.normal(size=70_000)
        mix = .6*stem[375:] + .4*rng.normal(size=len(stem)-375)
        result = audit(mix, stem, 1000)
        self.assertTrue(result['qualified_constant_offset'])
        self.assertEqual(result['stem_minus_mix_frames'], 375)
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
