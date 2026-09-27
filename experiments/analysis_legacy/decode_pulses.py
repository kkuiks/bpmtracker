"""Decode pulse continuity independently of meter on saved beat logits.

Uses the frozen comparison HMM with a one-pulse cycle and the beat observation
in its cycle-start slot. That slot is not a musical downbeat in this decoder.
The historical tempo bounds/transition costs are retained for a controlled test.
"""

import numpy as np

from legacy_dbn import DBNDownBeatTrackingProcessorPy
from run_beat_this import validate_events


def decode_pulses(beat_logits, fps=50.):
    logits = np.asarray(beat_logits, dtype=float)
    if logits.ndim != 1 or not np.isfinite(logits).all() or not np.isfinite(fps) or fps <= 0:
        raise ValueError('finite one-dimensional logits and positive frame rate required')
    if len(logits) == 0:return np.array([],dtype=float)
    probability = np.minimum(1/(1+np.exp(-np.clip(logits,-60,60))),.999)
    activations = np.column_stack([np.zeros_like(probability),probability])
    processor = DBNDownBeatTrackingProcessorPy(beats_per_bar=[1],fps=fps)
    decoded = processor.process(activations)
    return validate_events(decoded[:,0])


def retain_nearby_downbeats(beats, downbeats, max_distance=.07):
    beats, downbeats = validate_events(beats), validate_events(downbeats)
    if not len(beats):return np.array([],dtype=float)
    matched = []
    for event in downbeats:
        index = int(np.argmin(abs(beats-event)))
        if abs(beats[index]-event) <= max_distance:
            matched.append(beats[index])
    return np.unique(matched)
