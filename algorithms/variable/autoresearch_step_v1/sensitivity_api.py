"""Evaluation-only tolerance sensitivity without modifying shared globals."""
from __future__ import annotations

import numpy as np

from experiments.multiple_rhythm_continuity_v1.references import arrays, coordinate, templates
from experiments.multiple_rhythm_continuity_v1.common import PRIMARY_READINGS


def with_tolerances(api, phase_seconds, relative_rate):
    def validity(fields, times, reference):
        alternatives = templates(reference, PRIMARY_READINGS)
        bpm = fields["bpm"] * fields["denominator"] / 4
        _, region, support = arrays(times, reference)
        period = 60 / np.where(np.isfinite(bpm), bpm, 120.0)
        ticks = fields["phase"] + np.rint((times - fields["phase"]) / period) * period
        quarters = coordinate(np.nan_to_num(ticks, nan=0.0), reference)
        pulse = np.zeros((len(alternatives), len(times)), dtype=bool)
        for index, alternative in enumerate(alternatives):
            for state_index, state in enumerate(alternative["states"]):
                use = support & (region == state_index) & np.isfinite(bpm) & np.isfinite(fields["phase"])
                value = quarters[use] * state["factor"] - state["offset"]
                error = abs(value - np.rint(value)) * 60 / state["pulse_bpm"]
                pulse[index, use] = (abs(bpm[use] / state["pulse_bpm"] - 1) <= relative_rate + 1e-12) & (error <= phase_seconds + 1e-12)
        bars = np.zeros(len(times), dtype=bool)
        exact_meter, canonical_rate = bars.copy(), bars.copy()
        for index, state in enumerate(reference["states"]):
            use = support & (region == index) & np.isfinite(fields["bpm"])
            if not use.any():
                continue
            predicted_period = 60 / fields["bpm"][use] * fields["numerator"][use] * 4 / fields["denominator"][use]
            target_period = 60 / state["bpm"] * state["numerator"] * 4 / state["denominator"]
            available = np.asarray(reference["bars"])
            anchors = available[(available >= state["start"] - 1e-7) & (available < state["end"] - 1e-7)]
            anchor = float(anchors[0]) if len(anchors) else float(available[np.argmin(abs(available - state["start"]))]) if len(available) else state["start"]
            tick = fields["phase"][use] + np.rint((times[use] - fields["phase"][use]) / predicted_period) * predicted_period
            error = abs((tick - anchor + target_period / 2) % target_period - target_period / 2)
            bars[use] = (abs(predicted_period / target_period - 1) <= relative_rate + 1e-12) & (error <= phase_seconds + 1e-12)
            exact_meter[use] = (fields["numerator"][use] == state["numerator"]) & (fields["denominator"][use] == state["denominator"])
            canonical_rate[use] = abs(fields["bpm"][use] / state["bpm"] - 1) <= relative_rate + 1e-12
        return pulse, bars, exact_meter, canonical_rate, support

    return {**api, "validity": validity}
