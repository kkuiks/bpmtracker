"""Physical events and notation are separate in the product-facing result."""
from __future__ import annotations

import numpy as np

from .clock import fit_clock, quarters_at, seconds_at

DENOMINATORS = (2, 4, 8, 16, 32)


def event_peaks(values, *, threshold=.5, fps=50):
    """One event per connected positive lobe; no duplicate boundary reward."""
    values = np.asarray(values, float)
    positive = values >= threshold
    edges = np.diff(np.r_[False, positive, False].astype(int))
    starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    indices = np.asarray([a+int(np.argmax(values[a:b])) for a, b in zip(starts, stops)], int)
    times = []
    for i in indices:
        delta = 0.
        if 0 < i < len(values)-1:
            left, mid, right = np.log(np.maximum(values[i-1:i+2], 1e-8))
            curvature = left-2*mid+right
            if curvature < 0:delta = float(np.clip(.5*(left-right)/curvature, -.5, .5))
        times.append((i+delta)/fps)
    return np.asarray(times), indices


def interpret_bars(clock, starts, denominator_probabilities, fps=50):
    """Notation cannot move clock knots or detected physical bar boundaries.

    Quarter length comes from adjacent physical bar starts; the learned note
    unit chooses a compatible numerator. Alternative declarations are retained
    as hypotheses; these scores are not calibrated confidence.
    """
    coordinates = quarters_at(clock['knots'], starts)
    bars = []
    for i, time in enumerate(starts):
        length = float(coordinates[i+1]-coordinates[i]) if i+1 < len(starts) else None
        candidates = []
        if length is not None:
            for j, denominator in enumerate(DENOMINATORS):
                numerator = int(round(length*denominator/4))
                if 1 <= numerator <= 32 and abs(4*numerator/denominator-length) <= .20:
                    frame = min(len(denominator_probabilities)-1, max(0, int(round(time*fps))))
                    stop = min(len(denominator_probabilities), max(frame+1, int(round(starts[i+1]*fps))))
                    candidates.append(dict(numerator=numerator, denominator=denominator,
                                           model_score=float(denominator_probabilities[frame:stop, j].mean())))
        candidates.sort(key=lambda c: c['model_score'], reverse=True)
        bars.append(dict(seconds=float(time), quarter=float(coordinates[i]), quarter_length=length,
                         signature=candidates[0] if candidates else None, alternatives=candidates,
                         notation_status='proposed' if candidates else 'unresolved'))
    return bars


def decode(fields, source, *, fps=50):
    quarter_times, indices = event_peaks(fields['quarter'], fps=fps)
    duration = source['sample_frames']/source['sample_rate']
    inside = quarter_times < duration
    quarter_times, indices = quarter_times[inside], indices[inside]
    clock = fit_clock(quarter_times, fields['quarter_bpm'][indices], strengths=fields['quarter'][indices])
    starts, _ = event_peaks(fields['bar'], fps=fps); starts = starts[starts < duration]
    bars = interpret_bars(clock, starts, fields['denominator'], fps)
    active = np.asarray(fields['grid']) >= .5
    boundaries = np.diff(np.r_[False, active, False].astype(int))
    spans = [[float(a/fps), min(duration, float(b/fps))]
             for a, b in zip(np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1))]
    quarters = np.arange(np.ceil(quarters_at(clock['knots'], 0)),
                         np.ceil(quarters_at(clock['knots'], duration)))
    times = seconds_at(clock['knots'], quarters)
    keep = [(float(q), float(t)) for q, t in zip(quarters, times)
            if 0 <= t < duration and any(a <= t < b for a, b in spans)]
    return dict(schema_version=2, source=source, clock=clock,
                quarter_events=[dict(quarter=q, seconds=t) for q, t in keep],
                bar_events=bars, grid_support_seconds=spans,
                experimental=True, automatic_accuracy_validated=False,
                confidence_calibrated=False, source_only=True,
                architecture='direct physical-event prediction, independent numeric clock, separate note-unit interpretation')
