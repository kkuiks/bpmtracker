import unittest

import numpy as np

from decode_pulses import decode_pulses, retain_nearby_downbeats


class MeterFreePulseTests(unittest.TestCase):
    def test_regular_evidence_with_two_missing_peaks_keeps_pulse_continuity(self):
        logits = np.full(50*20,-9.)
        frames = np.arange(25,975,25)
        logits[frames] = 8.
        logits[frames[15:17]] = -3.
        result = decode_pulses(logits)
        interior = result[(result>=1)&(result<=18)]
        np.testing.assert_allclose(np.diff(interior),.5,atol=.021)
        self.assertTrue(np.any(abs(result-frames[15]/50)<.021))

    def test_downbeats_are_not_invented_by_the_one_pulse_cycle(self):
        beats=np.arange(0,8,.5)
        downbeats=retain_nearby_downbeats(beats,[.02,2.03,4.04,7.25])
        np.testing.assert_array_equal(downbeats,[0,2,4])
        self.assertLess(len(downbeats),len(beats))

    def test_empty_and_nonfinite_evidence(self):
        self.assertEqual(len(decode_pulses([])),0)
        with self.assertRaises(ValueError):decode_pulses([1,float('nan')])


if __name__=='__main__':unittest.main()
