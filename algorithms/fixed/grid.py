"""Physical quarter grids and chronological, one-to-one event matching."""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np


def rational_pool(low: float, high: float, denominator_max: int) -> list[Fraction]:
    return sorted({
        Fraction(n, d)
        for d in range(1, denominator_max + 1)
        for n in range(math.ceil(low * d), math.floor(high * d) + 1)
    })


def timestamps(period: float, offset: float, duration: float) -> np.ndarray:
    if period <= 0 or duration <= 0:
        return np.empty(0, dtype=np.float64)
    start = float(offset % period)
    if start >= duration:
        return np.empty(0, dtype=np.float64)
    times = start + np.arange(max(0, math.ceil((duration - start) / period))) * period
    return times[(times >= 0) & (times < duration)]


def match_events(predicted: np.ndarray, reference: np.ndarray, tolerance: float):
    """Maximum-cardinality monotone matching; each event is used at most once."""
    i = j = 0
    pi, ri = [], []
    while i < len(predicted) and j < len(reference):
        delta = predicted[i] - reference[j]
        if delta < -tolerance - 1e-12:
            i += 1
        elif delta > tolerance + 1e-12:
            j += 1
        else:
            pi.append(i)
            ri.append(j)
            i += 1
            j += 1
    return np.asarray(pi, dtype=int), np.asarray(ri, dtype=int)


def restrict(times: np.ndarray, support: list[list[float]]) -> np.ndarray:
    mask = np.zeros(len(times), dtype=bool)
    for start, end in support:
        mask |= (times >= start - 1e-9) & (times <= end + 1e-9)
    return np.asarray(times[mask], dtype=np.float64)

