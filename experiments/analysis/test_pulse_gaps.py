import unittest

import numpy as np

from fit_clock import fit_clock, grid_events
from pulse_gaps import infer_pulse_indices


class PulseGapTests(unittest.TestCase):
    def test_two_missing_pulses_do_not_become_a_tempo_change(self):
        truth = .17 + np.arange(160)*60/103
        observed = np.rint(np.delete(truth,[71,72])*50)/50
        indices,hypotheses = infer_pulse_indices(observed)
        self.assertEqual(len(hypotheses),1)
        self.assertEqual(hypotheses[0]['inferred_missing_pulses'],2)
        result = fit_clock(observed,pulse_indices=indices)
        self.assertEqual(len(result['segments']),1)
        self.assertAlmostEqual(result['segments'][0]['pulse_rate_per_minute'],103,delta=.02)
        self.assertEqual(len(grid_events(result)),len(truth))
        self.assertLess(np.max(abs(grid_events(result)-truth)),.005)
        self.assertFalse(hypotheses[0]['accepted'])
        self.assertIn('missing_pulse_hypotheses',result['status'])

    def test_sustained_half_tempo_is_not_filled_as_missing_pulses(self):
        beats = np.r_[np.arange(40)*.5,20+np.arange(40)*1.]
        indices,hypotheses = infer_pulse_indices(beats)
        self.assertFalse(hypotheses)
        np.testing.assert_array_equal(indices,np.arange(len(beats)))

    def test_gap_across_inconsistent_tempo_context_is_left_unresolved(self):
        beats = np.r_[np.arange(30)*.5,16+np.arange(30)*.6]
        _,hypotheses = infer_pulse_indices(beats)
        self.assertFalse(hypotheses)

    def test_missing_and_spurious_event_indices_are_rejected(self):
        beats = np.arange(20)*.5
        for indices in (np.arange(19),np.arange(20)+1,np.zeros(20),np.arange(20)*.5):
            with self.subTest(indices=indices),self.assertRaises(ValueError):
                fit_clock(beats,pulse_indices=indices)


if __name__=='__main__':unittest.main()
