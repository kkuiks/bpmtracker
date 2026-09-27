"""Constructed phrase-period check for beat-synchronous spectral observations."""
import unittest

import numpy as np

from phrase_recurrence import phrase_scores


class PhraseRecurrenceTests(unittest.TestCase):
    def test_repeated_fifteen_quarter_phrase_has_distinct_local_period(self):
        rng = np.random.default_rng(20260927)
        phrase = rng.normal(size=(15, 48)).astype("float32")
        phrase /= np.linalg.norm(phrase, axis=1, keepdims=True)
        observations = np.concatenate((phrase, phrase, phrase))
        scores = phrase_scores(observations, lags=(14, 15, 16))
        self.assertGreater(scores[15][0], .99)
        self.assertGreater(scores[15][0]-max(scores[14][0], scores[16][0]), .7)


if __name__ == "__main__":
    unittest.main()
