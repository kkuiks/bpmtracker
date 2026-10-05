"""Restrict machine proposals to source support without trimming source audio.

Only exact exterior digital silence is used. Internal rests are preserved, and
quiet/dithered/faded audio is not declared silent by an amplitude heuristic.
"""

import numpy as np


def nonzero_support(audio, sample_rate):
    audio = np.asarray(audio)
    if audio.ndim not in (1,2) or not len(audio) or not np.isfinite(audio).all() or sample_rate <= 0:
        raise ValueError("expected nonempty finite mono/multichannel audio and positive sample rate")
    active = np.flatnonzero(np.any(audio != 0, axis=1) if audio.ndim == 2 else audio != 0)
    return None if len(active) == 0 else [int(active[0]), int(active[-1])+1]


def supported_prediction(prediction, support_frames, sample_rate, margin_seconds=.05):
    if not np.isfinite(margin_seconds) or margin_seconds < 0:
        raise ValueError("margin must be nonnegative and finite")
    result = dict(prediction)
    original = np.asarray(prediction["beats_seconds"])
    if support_frames is None:
        keep = np.zeros(len(original), dtype=bool)
    else:
        start, end = np.asarray(support_frames)/sample_rate
        keep = (original >= start-margin_seconds) & (original <= end+margin_seconds)
    beats = original[keep]
    result["beats_seconds"] = beats.tolist()
    result["downbeats_seconds"] = np.intersect1d(prediction["downbeats_seconds"], beats).tolist()
    if "beat_numbers" in prediction:
        result["beat_numbers"] = np.asarray(prediction["beat_numbers"])[keep].tolist()
    result["audio_support_filter"] = {"nonzero_source_sample_span": support_frames,
                                       "sample_rate": sample_rate, "margin_seconds": margin_seconds,
                                       "excluded_beat_count": int(np.sum(~keep)),
                                       "source_shift_seconds": 0, "internal_silence_filtered": False,
                                       "scope": "new machine proposal only; not accepted user beats or count-in"}
    return result
