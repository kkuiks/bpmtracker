import unittest
import numpy as np

from qualify_observed_click import match_quarters


class ObservedClickTests(unittest.TestCase):
    def test_subdivision_identity_preserves_observed_timing(self):
        indices, differences = match_quarters([0., .505, 1.01], [.001, .251, .501, .751, 1.001])
        np.testing.assert_array_equal(indices, [0, 2, 4])
        np.testing.assert_allclose(differences, [.001, -.004, -.009])

    def test_missing_ambiguous_and_reused_clicks_are_rejected(self):
        for midi, clicks in [([0, 1], [0, .5]), ([.25, .75], [.2, .3, .7, .8]),
                             ([.01, .02], [0, 1]), ([0, float('nan')], [0, 1])]:
            with self.subTest(midi=midi), self.assertRaises(ValueError):
                match_quarters(midi, clicks)


if __name__ == '__main__':
    unittest.main()
