"""Decode variable bar lengths over a source-only constant quarter grid."""
from __future__ import annotations

from copy import deepcopy
import numpy as np

from .constant_grid import BAR_SIZES, _probability


def decode_bar_sequence(base, downbeat_logits, fps, observed_downbeats,
                        *, boundary_floor=.4, boundary_weight=2.0,
                        observation_weight=.25, meter_change_cost=.35,
                        unusual_bar_cost=.04):
    """Viterbi bar path; each edge is 2, 3, 4, 5, 6, or 8 quarters.

    The score rewards downbeat evidence at selected boundaries and charges for
    unmotivated signatures and transitions. All inputs are model observations.
    """
    if base["status"] != "proposed_map" or not base["diagnostics"].get("constant_grid_only"):
        raise ValueError("a source-only constant quarter grid is required")
    grid = np.asarray(base["beat_times_seconds"], dtype=float)
    down = _probability(downbeat_logits)
    observed = np.sort(np.asarray(observed_downbeats, dtype=float))
    if len(grid) < 10 or not np.isfinite(grid).all() or not np.isfinite(observed).all():
        raise ValueError("finite full-source grid and observations required")
    indices = np.clip(np.rint(grid * fps).astype(int), 0, len(down)-1)
    radius = np.stack((np.clip(indices-1, 0, len(down)-1), indices,
                       np.clip(indices+1, 0, len(down)-1)))
    activation = np.max(down[radius], axis=0)
    positions = np.searchsorted(observed, grid)
    if len(observed):
        nearest = np.minimum(abs(observed[np.clip(positions, 0, len(observed)-1)] - grid),
                             abs(observed[np.clip(positions-1, 0, len(observed)-1)] - grid))
        observed_here = nearest <= .07
    else:
        observed_here = np.zeros(len(grid), dtype=bool)
    evidence = (boundary_weight * (activation - boundary_floor) +
                observation_weight * observed_here)
    # A path state means a selected boundary at i and the size of its last bar.
    # The starting state has no previous bar; predecessor links retain the path.
    states = {}
    for first in range(min(4, len(grid))):
        states[(first, 0)] = (float(evidence[first] - .04 * first), None, 0)
    for i in range(len(grid)):
        for last in (0, *BAR_SIZES):
            key = (i, last)
            if key not in states:
                continue
            score, _, changes = states[key]
            for size in BAR_SIZES:
                end = i + size
                if end >= len(grid):
                    continue
                transition = meter_change_cost if last and last != size else 0.0
                value = (score + float(evidence[end]) - transition -
                         unusual_bar_cost * abs(size-4))
                next_key = (end, size)
                candidate_changes = changes + int(bool(last) and last != size)
                previous = states.get(next_key)
                if previous is None or (value, -candidate_changes) > (previous[0], -previous[2]):
                    states[next_key] = (value, key, candidate_changes)
    terminals = [(score - .06 * (len(grid)-1-i), -changes, key)
                 for key, (score, _, changes) in states.items()
                 for i, size in [key] if size and len(grid)-1-i < 8]
    if not terminals:
        raise ValueError("no full-source variable-bar path")
    _, _, key = max(terminals)
    selected = []
    while key is not None:
        selected.append(key)
        key = states[key][1]
    selected.reverse()
    starts = [selected[0][0]]
    sizes = []
    for before, after in zip(selected, selected[1:]):
        size = after[0] - before[0]
        if size != after[1]:
            raise AssertionError("bar path edge mismatch")
        sizes.append(size)
        starts.append(after[0])
    if not sizes:
        raise ValueError("variable-bar path lacks a full bar")
    result = deepcopy(base)
    result["diagnostics"]["constant_grid_only"] = False
    result["diagnostics"]["bar_sequence"] = {
        "source_only": True, "boundary_floor": boundary_floor,
        "boundary_weight": boundary_weight, "observation_weight": observation_weight,
        "meter_change_cost": meter_change_cost, "unusual_bar_cost": unusual_bar_cost,
        "selected_boundaries": len(starts),
        "selected_meter_changes": sum(a != b for a, b in zip(sizes, sizes[1:])),
        "viterbi_score": float(states[selected[-1]][0]),
        "constant_bar_hypothesis_score": base["diagnostics"]["top_bar_hypotheses"][0]["score"]}
    result["bar_starts_seconds"] = grid[starts].tolist()
    def event(pulse, size):
        return {"pulse": float(pulse), "numerator": int(size), "denominator": 4,
                "grouping": [1]*int(size), "bar_action": "continue"}
    events = [event(0, sizes[0])]
    for j in range(1, len(sizes)):
        if sizes[j] != sizes[j-1]:
            events.append(event(starts[j], sizes[j]))
    result["map"]["bar_anchor_pulse"] = float(starts[0])
    result["map"]["meter_events"] = events
    return result
