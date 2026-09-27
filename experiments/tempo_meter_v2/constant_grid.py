"""Source-only constant-grid control from frozen Beat This acoustic observations.

A whole-source periodic beat component proposes the quarter rate and phase.
Official downbeat events and raw downbeat probabilities select one constant
bar size and phase. This control deliberately cannot describe real changes.
"""
from __future__ import annotations

import math
import numpy as np

BAR_SIZES = (2, 3, 4, 5, 6, 8)


def _probability(logits):
    values = np.asarray(logits, dtype=np.float64)
    if values.ndim != 1 or len(values) < 100 or not np.isfinite(values).all():
        raise ValueError("finite full-source logits required")
    return 1.0 / (1.0 + np.exp(-np.clip(values, -40, 40)))


def beat_period(beat_logits, fps):
    """Return a stable full-song period and phase with no reference tempo."""
    beat = _probability(beat_logits)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("positive logit frame rate required")
    centered = beat - beat.mean()
    nfft = 1 << (8 * len(beat) - 1).bit_length()
    spectrum = np.fft.rfft(centered, n=nfft)
    strength = np.abs(spectrum)
    frequencies = np.fft.rfftfreq(nfft, 1 / fps)
    peaks = np.flatnonzero((strength > np.r_[0, strength[:-1]]) &
                           (strength >= np.r_[strength[1:], 0]) &
                           (frequencies >= 35 / 60) &
                           (frequencies <= 320 / 60))
    if not len(peaks):
        raise ValueError("no stable beat-period candidate")
    selected = int(peaks[np.argmax(strength[peaks])])
    dominant = selected
    # If a strong doubled pulse is detected, prefer its octave-supported
    # slower quarter. The ratio and threshold are fixed for this control.
    if frequencies[selected] * 60 > 210:
        half = np.argmin(abs(frequencies[peaks] - frequencies[selected] / 2))
        half_index = int(peaks[half])
        if (abs(frequencies[half_index] - frequencies[selected] / 2) < .015 and
                strength[half_index] >= .55 * strength[selected]):
            selected = half_index
    if selected <= 0 or selected >= len(strength) - 1:
        raise ValueError("invalid beat-period peak")
    left, middle, right = np.log(np.maximum(strength[selected-1:selected+2], 1e-30))
    denominator = left - 2 * middle + right
    fractional = .5 * (left - right) / denominator if denominator < 0 else 0.0
    frequency = (selected + float(np.clip(fractional, -.5, .5))) * fps / nfft
    times = np.arange(len(beat), dtype=np.float64) / fps
    coefficient = np.dot(centered, np.exp(-2j * np.pi * frequency * times))
    period = 1 / frequency
    phase = float((-np.angle(coefficient) / (2 * np.pi * frequency)) % period)
    return {"quarter_bpm": float(60 * frequency), "period_seconds": float(period),
            "phase_seconds": phase, "dominant_bpm": float(60 * frequencies[dominant]),
            "selected_peak_to_dominant_ratio": float(strength[selected] / strength[dominant]),
            "periodic_strength": float(strength[selected] / max(np.sum(beat), 1e-12))}


def _nearest_matches(reference_events, proposed_events, tolerance):
    if not len(reference_events) or not len(proposed_events):
        return 0
    locations = np.searchsorted(reference_events, proposed_events)
    right = np.clip(locations, 0, len(reference_events) - 1)
    left = np.clip(locations - 1, 0, len(reference_events) - 1)
    distances = np.minimum(abs(reference_events[right] - proposed_events),
                           abs(reference_events[left] - proposed_events))
    return int(np.count_nonzero(distances <= tolerance))


def select_bar_grid(beat_grid, downbeat_logits, fps, observed_downbeats):
    """Rank complete constant bar patterns using only acoustic observations."""
    down = _probability(downbeat_logits)
    observed = np.sort(np.asarray(observed_downbeats, dtype=np.float64))
    if observed.ndim != 1 or not np.isfinite(observed).all():
        raise ValueError("finite downbeat observations required")
    candidates = []
    for size in BAR_SIZES:
        for offset in range(size):
            bars = beat_grid[offset::size]
            if len(bars) < 4:
                continue
            indices = np.clip(np.rint(bars * fps).astype(int), 0, len(down)-1)
            neighbours = np.stack((np.clip(indices-1, 0, len(down)-1), indices,
                                   np.clip(indices+1, 0, len(down)-1)))
            activation = float(np.mean(np.max(down[neighbours], axis=0)))
            matched = _nearest_matches(observed, bars, .07)
            event_f1 = 2 * matched / (len(observed) + len(bars)) if len(observed) else 0.0
            score = event_f1 + .1 * activation
            candidates.append({"beats_per_bar": size, "first_bar_beat_index": offset,
                               "score": float(score), "observed_downbeat_f1": float(event_f1),
                               "mean_downbeat_probability": activation,
                               "predicted_bars": len(bars), "matched_observations": matched})
    if not candidates:
        raise ValueError("no complete constant bar pattern")
    candidates.sort(key=lambda x: (-x["score"], abs(x["beats_per_bar"]-4),
                                   x["first_bar_beat_index"]))
    return candidates


def infer_constant_map(beat_logits, downbeat_logits, fps, observed_downbeats, source):
    """Propose one constant quarter BPM/meter map from source-only evidence."""
    if set(source) != {"sha256", "sample_rate", "sample_frames"}:
        raise ValueError("source must contain only physical identity and geometry")
    duration = source["sample_frames"] / source["sample_rate"]
    beat = _probability(beat_logits)
    down = _probability(downbeat_logits)
    if len(beat) != len(down) or len(beat)/fps < duration - .03:
        raise ValueError("logits do not cover the full source")
    period = beat_period(beat_logits, fps)
    step = period["period_seconds"]
    phase = period["phase_seconds"]
    grid = phase + np.arange(math.ceil((duration - phase) / step) + 1) * step
    grid = grid[grid <= duration]
    bars = select_bar_grid(grid, downbeat_logits, fps, observed_downbeats)
    best = bars[0]
    bar_times = grid[best["first_bar_beat_index"]::best["beats_per_bar"]]
    count = best["beats_per_bar"]
    end_quarter = (duration - phase) / step
    result_map = {"schema_version": 1, "source": source,
                  "clock_knots": [{"pulse": 0.0, "source_seconds": phase},
                                  {"pulse": float(end_quarter), "source_seconds": duration}],
                  "quarters_per_pulse": {"numerator": 1, "denominator": 1},
                  "bar_anchor_pulse": float(best["first_bar_beat_index"]),
                  "meter_events": [{"pulse": 0.0, "numerator": count,
                                    "denominator": 4, "grouping": [1] * count,
                                    "bar_action": "continue"}],
                  "support_seconds": [[phase, duration]],
                  "analysis_condition": "unhinted", "shared_origin_id": None}
    return {"schema_version": 1, "status": "proposed_map", "map": result_map,
            "beat_times_seconds": grid.tolist(), "bar_starts_seconds": bar_times.tolist(),
            "diagnostics": {"constant_grid_only": True, "reference_used_for_prediction": False,
                            "period": period, "top_bar_hypotheses": bars[:8]},
            "resources": {"bar_hypotheses": len(bars)},
            "evidence_provenance": {"source_sha256": source["sha256"], "fps": float(fps)}}
