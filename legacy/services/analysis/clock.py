"""Piecewise affine quarter clock, independent of meter and rhythm grammar."""
from __future__ import annotations

import numpy as np


def _line(q, t):
    design = np.column_stack([np.ones(len(q)), q])
    intercept, slope = np.linalg.lstsq(design, t, rcond=None)[0]
    return float(intercept), float(slope)


def fit_clock(times, coarse_bpm, *, strengths=None, timing_sigma=.020, minimum_points=4):
    """Assign missing quarters, then segment timing with a BIC-style penalty.

    Coarse rate chooses only a discrete half/normal/double event interpretation.
    All final clock rates/intercepts fit event times, never notation or a guide.
    No musical meter candidates are searched. Complexity is quadratic in event
    count, with vectorized segment costs and linear-sized working memory.
    """
    t = np.asarray(times, float)
    rates = np.asarray(coarse_bpm, float)
    if len(t) < minimum_points or rates.shape != t.shape:
        raise ValueError('insufficient quarter observations')
    if not np.isfinite(t).all() or not np.isfinite(rates).all() or np.any(np.diff(t) <= 0) or np.any(rates <= 0):
        raise ValueError('invalid timing observations')
    gaps = np.diff(t)
    steps = []
    for i, gap in enumerate(gaps):
        period = float(np.median(gaps[max(0, i-3):min(len(gaps), i+4)]))
        expected = 60 / float(np.median(rates[max(0, i-2):min(len(rates), i+4)]))
        family = min((.25, 1/3, .5, 2/3, 1., 1.5, 2.),
                     key=lambda f: abs(np.log(period*f/expected)))
        # A dense event stream can contain eighths despite the quarter score.
        # Preserve half-quarter coordinates instead of forcing every peak to
        # advance an entire quarter (which would silently double the BPM).
        unit = .5 if family in (2., 2/3) else 1/3 if family == 1.5 else 1.
        steps.append(max(unit, round(gap/(period*family)/unit)*unit))
    q = np.r_[0., np.cumsum(steps)].astype(float)
    if strengths is not None and np.any(abs(q-np.round(q)) > 1e-7):
        weights = np.asarray(strengths, float)
        if weights.shape != q.shape:raise ValueError('event strength shape differs')
        phases=np.unique(np.mod(np.round(np.mod(q,1.),6),1.))
        phase = max(phases, key=lambda p:float(weights[abs(q-p-np.round(q-p)) < 1e-5].sum()))
        q -= phase
    n = len(q)
    # Centering time improves cancellation behavior for long recordings.
    y = t-t[0]
    sums = [np.r_[0., np.cumsum(v)] for v in (q, y, q*q, q*y, y*y)]
    penalty = 3 * np.log(max(n, 2)) * timing_sigma**2
    best = np.full(n+1, np.inf); previous = np.full(n+1, -1, int)
    best[0] = -penalty
    for stop in range(minimum_points, n+1):
        starts = np.arange(stop-minimum_points+1)
        count = stop-starts
        sx, sy, sxx, sxy, syy = [s[stop]-s[starts] for s in sums]
        vx = np.maximum(sxx-sx*sx/count, 1e-12)
        cov = sxy-sx*sy/count
        slope = cov/vx
        rss = np.maximum(0., syy-sy*sy/count-cov*cov/vx)
        costs = best[starts]+rss+penalty
        costs[slope <= 0] = np.inf
        winner = int(np.argmin(costs))
        best[stop] = costs[winner]; previous[stop] = int(starts[winner])
    if previous[n] < 0:
        raise ValueError('no positive quarter clock')
    parts = []; stop = n
    while stop:
        start = int(previous[stop]); parts.append((start, stop)); stop = start
    parts.reverse()
    lines = [_line(q[a:b], t[a:b]) for a, b in parts]
    breaks = []
    for i in range(len(parts)-1):
        _, left_stop = parts[i]; right_start, _ = parts[i+1]
        lo, hi = q[left_stop-1], q[right_start]
        a, b = lines[i]; c, d = lines[i+1]
        crossing = (c-a)/(b-d) if abs(b-d) > 1e-12 else (lo+hi)/2
        breaks.append(float(np.clip(crossing, lo, hi)))
    # Continuous shared fit: discontinuous segment regressions are proposals.
    design = np.column_stack([np.ones(n), q, *[np.maximum(0., q-b) for b in breaks]])
    weights = np.ones(n)
    for _ in range(4):
        coefficients = np.linalg.lstsq(design*np.sqrt(weights[:, None]), t*np.sqrt(weights), rcond=None)[0]
        residual = t-design@coefficients
        weights = np.minimum(1., 2*timing_sigma/np.maximum(abs(residual), 1e-12))
    coordinates = np.asarray([q[0], *breaks, q[-1]])
    basis = np.column_stack([np.ones(len(coordinates)), coordinates,
                             *[np.maximum(0., coordinates-b) for b in breaks]])
    seconds = basis@coefficients
    if np.any(np.diff(seconds) <= 0):
        raise ValueError('nonmonotonic continuous clock')
    return dict(knots=[dict(quarter=float(a), seconds=float(b)) for a, b in zip(coordinates, seconds)],
                event_quarters=q.tolist(), observed_times=t.tolist(),
                p95_residual_seconds=float(np.quantile(abs(residual), .95)),
                segment_count=len(parts), meter_used=False, numerical_guide_used=False)


def seconds_at(knots, quarter):
    q = np.asarray([k['quarter'] for k in knots]); t = np.asarray([k['seconds'] for k in knots])
    value = np.asarray(quarter, float); index = np.clip(np.searchsorted(q, value, side='right')-1, 0, len(q)-2)
    return t[index]+(value-q[index])*(t[index+1]-t[index])/(q[index+1]-q[index])


def quarters_at(knots, seconds):
    q = np.asarray([k['quarter'] for k in knots]); t = np.asarray([k['seconds'] for k in knots])
    value = np.asarray(seconds, float); index = np.clip(np.searchsorted(t, value, side='right')-1, 0, len(t)-2)
    return q[index]+(value-t[index])*(q[index+1]-q[index])/(t[index+1]-t[index])
