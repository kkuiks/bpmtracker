"""Counterfactual source-boundary policy must still penalize extra guesses."""
import unittest

from experiments.tempo_meter_v2.score_observational_equivalence_probe import (
    revised_meter_metric)
from experiments.tempo_meter_v2.score_primary11 import change_gate


class ObservationalEquivalenceProbeTests(unittest.TestCase):
    event = {"source_seconds": .6, "numerator": 4, "denominator": 4}
    optional = {**event, "preceding_bar_start_seconds": -.08,
                "in_source_bar_count": 158,
                "maximum_bar_difference_seconds": 0.}

    def test_unobservable_missing_change_is_optional(self):
        counts,neutral = revised_meter_metric([self.event], [], [self.optional])
        self.assertEqual((counts["true_positives"],counts["false_positives"],
                          counts["false_negatives"]),(0,0,0))
        self.assertEqual(neutral,[])
        self.assertEqual(change_gate(counts),1.)

    def test_one_exact_optional_prediction_is_neutral_but_extra_is_false(self):
        guessed=[self.event,{**self.event,"source_seconds":.7}]
        counts,neutral = revised_meter_metric([self.event],guessed,[self.optional])
        self.assertEqual(len(neutral),1)
        self.assertEqual((counts["true_positives"],counts["false_positives"],
                          counts["false_negatives"]),(0,1,0))
        self.assertEqual(change_gate(counts),0.)

    def test_constant_reference_still_fails_on_any_false_change(self):
        counts,_ = revised_meter_metric([], [self.event], [])
        self.assertEqual(counts["false_positives"],1)
        self.assertEqual(change_gate(counts),0.)


if __name__ == "__main__":unittest.main()
