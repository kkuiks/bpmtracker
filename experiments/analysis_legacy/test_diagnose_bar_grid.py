import unittest
import numpy as np
from diagnose_bar_grid import representability, compare_grids


class BarGridDiagnosticTests(unittest.TestCase):
    def test_five_eighth_bar_is_not_representable_by_integer_quarters(self):
        result = representability([{'numerator': 5, 'denominator': 8}])
        self.assertFalse(result['supported'])
        self.assertEqual(result['unsupported_quarter_lengths'], ['5/2'])

    def test_six_eighth_boundary_length_is_representable_but_signature_is_not_inferred(self):
        result = representability([{'numerator': 6, 'denominator': 8}])
        self.assertTrue(result['supported'])
        self.assertFalse(result['meter_signature_inferred'])

    def test_changing_grid_does_not_move_logits_and_missing_boundaries_remain_failures(self):
        evidence = np.full(1000, -8.)
        truth = [0., 2., 4., 6., 8.]
        for t in truth:
            evidence[round(t*50)] = 8.
        original = evidence.copy()
        result = compare_grids(np.arange(.25, 8.5, .5), np.arange(0, 8.5, .5), truth, evidence, 50., [0., 8.])
        np.testing.assert_array_equal(evidence, original)
        self.assertEqual(result['arms']['oracle_quarter_grid']['decoders']['fixed']['scores_to_supplied_bar_events']['0.02']['f1'], 1.)
        self.assertEqual(result['arms']['saved_grid']['decoders']['fixed']['scores_to_supplied_bar_events']['0.02']['f1'], 0.)
        self.assertFalse(result['reference_used_to_align_saved_grid'])


if __name__ == '__main__':
    unittest.main()
