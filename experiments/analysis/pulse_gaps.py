"""Propose explicit missing-pulse indices without imposing a bar length.

An isolated long gap can mean missed beats OR a brief tempo excursion. Keep the
original events and this alternative together; do not treat it as accepted truth.
"""

import numpy as np

from run_beat_this import validate_events


def infer_pulse_indices(beats, context=4, max_multiple=4, timing_tolerance=.06):
    beats = validate_events(beats)
    intervals = np.diff(beats)
    increments = np.ones(len(intervals), dtype=int)
    proposals = []
    for i, gap in enumerate(intervals):
        if i < context or i+context >= len(intervals):
            continue
        left = intervals[i-context:i]
        right = intervals[i+1:i+1+context]
        a,b = float(np.median(left)),float(np.median(right))
        period = (a+b)/2
        if abs(a-b)/period > .03:
            continue
        neighbors = np.r_[left,right]
        if np.max(abs(neighbors-period)) > min(.06, .12*period):
            continue
        multiple = round(gap/period)
        if not 2 <= multiple <= max_multiple or abs(gap-multiple*period) > timing_tolerance:
            continue
        increments[i] = multiple
        proposals.append({'after_input_event':i,'start_seconds':float(beats[i]),'end_seconds':float(beats[i+1]),
                          'inferred_missing_pulses':multiple-1,'surrounding_period_seconds':period,
                          'alternative_explanation':'brief slower tempo; requires review', 'accepted':False})
    return np.r_[0,np.cumsum(increments)].astype(float), proposals
