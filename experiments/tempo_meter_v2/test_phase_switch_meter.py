"""Check that variable-meter proposals require sustained changes and clear attacks."""
import unittest

import numpy as np

from experiments.tempo_meter_v2.phase_switch_meter import (
    choose_internal_bar, model_phase_support, stable_phase_switches,
    transition_gaps)


class PhaseSwitchMeterTests(unittest.TestCase):
    @staticmethod
    def signal(segments):
        size = segments[-1][1]
        p = np.full(size, .05)
        for start, end, phase in segments:
            for q in range(start, end):
                if q % 4 == phase:
                    p[q] = .95
        return p

    def test_sustained_three_phase_changes_have_two_transition_gaps(self):
        p = self.signal([(0, 96, 0), (96, 224, 2), (224, 352, 3)])
        runs, evidence = stable_phase_switches(p)
        self.assertTrue(evidence["accepted"])
        self.assertEqual(runs, [[0, 96, 0], [96, 224, 2], [224, 352, 3]])
        self.assertEqual(transition_gaps(runs), [(92, 98), (222, 227)])
        supported, _ = model_phase_support(runs,
            {"beatthis0": p, "beatthis1": p, "allinone": p})
        self.assertTrue(supported)

    def test_short_wrong_phase_burst_does_not_create_false_changes(self):
        p = self.signal([(0, 160, 0), (160, 176, 2), (176, 352, 0)])
        runs, evidence = stable_phase_switches(p)
        self.assertIsNone(runs)
        self.assertFalse(evidence["accepted"])

    def test_split_requires_drum_and_model_consensus(self):
        # A six-quarter gap may be 3+3, 2+4, 4+2 or one 6/4 bar.
        model0 = np.zeros(20)
        model1 = np.zeros(20)
        model0[7] = .22
        model1[7] = .64
        split, details = choose_internal_bar(4, 10,
            {6: .02, 7: 1.2, 8: .20}, model0, model1)
        self.assertEqual(split, 7)
        self.assertTrue(details["accepted"])
        # An almost equally plausible attack must abstain to avoid extra bars.
        split, details = choose_internal_bar(4, 10,
            {6: .02, 7: 1.2, 8: 1.1}, model0, model1)
        self.assertIsNone(split)
        self.assertFalse(details["accepted"])


if __name__ == "__main__":
    unittest.main()
