"""Symmetric grid evidence without a meter-dependent PCM counting preference."""
import numpy as np
from .base_scoring import Score as BaseScore
from .common import CONFIG as BASE_CONFIG


class Score(BaseScore):
    def __init__(self, events):
        super().__init__(events, role_mixture=True)
        self.unit_hold = True

    def batch(self, bpm, phase, numerator, denominator, left, right,
              components=False):
        _, beat, _, _ = super().batch(
            bpm, phase, numerator, denominator, left, right, True)
        b, phi, n, d, a, z = np.broadcast_arrays(*[
            np.atleast_1d(np.asarray(v, float))
            for v in (bpm, phase, numerator, denominator, left, right)
        ])
        p = 60 / b
        # Predicted empty bar starts matter as well as explaining observed ones.
        # This retains the shared weighted F1 rather than adding 80% one-way recall.
        bar = self.audio.channel(1, p * n * 4 / d, phi, a, z,
                                 BASE_CONFIG['neural_sigma_seconds'])
        # Relabelling a physical bar 3/4 <-> 6/8 must not receive extra PCM credit
        # merely because the metronome emits more subdivision clicks.
        pcm = self.audio.channel(2, p, phi, a, z,
                                 BASE_CONFIG['pcm_sigma_seconds'])
        prior = np.array([BASE_CONFIG['meter_prior'][f'{int(x)}/{int(y)}']
                          for x, y in zip(n, d)])
        observed = np.searchsorted(self.t, z) - np.searchsorted(self.t, a)
        value = (BASE_CONFIG['beat_weight'] * beat
                 + BASE_CONFIG['bar_weight'] * bar
                 + BASE_CONFIG['pcm_weight'] * pcm - prior * (observed > 0))
        return (value, beat, bar, pcm) if components else value
