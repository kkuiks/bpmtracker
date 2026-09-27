"""Conservative 4/4 phase-switch interpretation from independent source cues.

This experiment proposes short bars only when three stable downbeat phases,
independent acoustic models, and a localized drum attack agree. It does not
read written meter or a reference map. Ambiguous phase/split evidence abstains.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

from .constant_grid import _probability
from .tempo_segments import _sample

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import prepare_map, render_bars


PHASE_SWITCH_PENALTIES = (5., 8., 12.)
MIN_STABLE_PULSES = 64
DRUM_SPLIT_RATIO = 3.
DRUM_BAND_HZ = (30., 160.)


def phase_runs(probability, switch_penalty):
    """Viterbi on complete groups of four quarters, paying for every switch."""
    p = np.asarray(probability, dtype=float)
    if p.ndim != 1 or len(p) < 4 * 16 or not np.isfinite(p).all():
        raise ValueError("finite full-source quarter probabilities required")
    n = len(p) // 4
    evidence = p[:4*n].reshape(n, 4)
    accumulated = np.empty((n, 4), dtype=float)
    predecessor = np.zeros((n, 4), dtype=np.int8)
    accumulated[0] = evidence[0]
    for block in range(1, n):
        for phase in range(4):
            scores = accumulated[block-1] - switch_penalty * (np.arange(4) != phase)
            previous = int(np.argmax(scores))
            predecessor[block, phase] = previous
            accumulated[block, phase] = scores[previous] + evidence[block, phase]
    phase = int(np.argmax(accumulated[-1]))
    decoded = np.empty(n, dtype=np.int8)
    for block in range(n-1, -1, -1):
        decoded[block] = phase
        phase = int(predecessor[block, phase])
    runs = []
    for block, phase in enumerate(decoded):
        if not runs or runs[-1][2] != int(phase):
            runs.append([4*block, 4*(block+1), int(phase)])
        else:
            runs[-1][1] = 4*(block+1)
    return runs


def stable_phase_switches(probability):
    trials = {str(penalty): phase_runs(probability, penalty)
              for penalty in PHASE_SWITCH_PENALTIES}
    first = next(iter(trials.values()))
    stable = all(runs == first for runs in trials.values())
    accepted = (stable and len(first) == 3 and
                all(end-start >= MIN_STABLE_PULSES for start, end, _ in first) and
                first[0][2] == 0 and len({row[2] for row in first}) == 3)
    return first if accepted else None, {"penalty_runs": trials,
        "same_at_all_penalties": stable, "accepted": bool(accepted),
        "minimum_stable_pulses": MIN_STABLE_PULSES}


def model_phase_support(runs, models):
    evidence = {}
    accepted = True
    for name, signal in models.items():
        p = np.asarray(signal, dtype=float)
        if p.ndim != 1 or len(p) < runs[-1][1] or not np.isfinite(p).all():
            raise ValueError("complete finite independent downbeat view required")
        rows = []
        for start, end, chosen in runs:
            index = np.arange(start, end)
            scores = [float(p[index[index % 4 == phase]].mean()) for phase in range(4)]
            ranking = np.argsort(-np.asarray(scores))
            margin = scores[chosen] - scores[int(ranking[1])]
            passed = int(ranking[0]) == chosen and margin >= (.025 if name == "allinone" else .05)
            accepted &= passed
            rows.append({"pulse_range": [start, end], "chosen_phase": chosen,
                         "phase_means": scores, "margin_to_runner_up": float(margin),
                         "accepted": bool(passed)})
        evidence[name] = rows
    return bool(accepted), evidence


def transition_gaps(runs):
    gaps = []
    for before, after in zip(runs, runs[1:]):
        switch = after[0]
        old_phase, new_phase = before[2], after[2]
        start = switch-1 - ((switch-1-old_phase) % 4)
        end = switch + ((new_phase-switch) % 4)
        if not 5 <= end-start <= 7:
            return None
        gaps.append((int(start), int(end)))
    return gaps


def local_drum_attacks(audio_path, times, *, low=30., high=160., radius=.05):
    """Read only a short source-clock window around proposed internal barlines."""
    times = np.asarray(times, dtype=float)
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all():
        raise ValueError("finite nonempty source times required")
    with sf.SoundFile(audio_path) as source:
        if not source.format.startswith("WAV"):
            raise ValueError("canonical WAV stem required")
        rate = source.samplerate
        first = max(0, int(np.floor((times.min()-.2)*rate)))
        last = min(source.frames, int(np.ceil((times.max()+.2)*rate)))
        source.seek(first)
        audio = source.read(last-first, dtype="float32", always_2d=True).mean(axis=1)
        geometry = {"sample_rate": rate, "sample_frames": source.frames}
    size, hop = 2048, 240
    frames = np.lib.stride_tricks.sliding_window_view(
        np.pad(audio, (size//2, size//2)), size)[::hop]
    frequencies = np.fft.rfftfreq(size, 1/rate)
    band = (frequencies >= low) & (frequencies <= high)
    if not band.any():
        raise ValueError("no drum attack bins in requested band")
    spectrum = np.abs(np.fft.rfft(frames*np.hanning(size), axis=1))
    power = np.log1p(spectrum[:, band]).mean(axis=1)
    flux = np.maximum(np.diff(power, prepend=power[0]), 0)
    frame_times = first/rate + np.arange(len(flux))*hop/rate
    attack = []
    for time in times:
        lo, hi = np.searchsorted(frame_times, (time-radius, time+radius))
        attack.append(float(np.max(flux[lo:hi])) if hi > lo else 0.)
    return np.asarray(attack), {**geometry, "fft_size": size, "hop_samples": hop,
        "band_hz": [low, high], "radius_seconds": radius,
        "window_seconds": [first/rate, last/rate]}


def choose_internal_bar(start, end, drums, model0, model1):
    """Two adjacent bars must each have at least two quarters."""
    indices = list(range(start+2, end-1))
    if len(indices) < 2:
        return None, {"reason": "too_few_legal_splits"}
    strength = np.asarray([drums[q] for q in indices])
    rank = np.argsort(-strength)
    best, runner_up = indices[int(rank[0])], indices[int(rank[1])]
    ratio = float(strength[rank[0]] / max(strength[rank[1]], 1e-12))
    neural_best = [indices[int(np.argmax([model[q] for q in indices]))]
                   for model in (model0, model1)]
    neural_strength = max(float(model0[best]), float(model1[best]))
    accepted = (ratio >= DRUM_SPLIT_RATIO and best in neural_best and
                neural_strength >= .15)
    details = {"candidate_pulses": indices,
               "drum_attacks": strength.tolist(), "strongest_pulse": best,
               "runner_up_pulse": runner_up, "strongest_to_runner_up_ratio": ratio,
               "model_best_pulses": neural_best,
               "strongest_model_probability": neural_strength,
               "accepted": bool(accepted)}
    return (best if accepted else None), details


def propose_phase_switch_meter(base, final0, fps0, final1, fps1,
                               allinone, drums_path):
    """Return (source-only meter map or None, audit evidence)."""
    grid = np.asarray(base["beat_times_seconds"], dtype=float)
    p0 = _sample(_probability(final0), fps0, grid)
    p1 = _sample(_probability(final1), fps1, grid)
    pa = _sample(np.asarray(allinone, dtype=float), 100., grid)
    runs, phase_evidence = stable_phase_switches(p1)
    evidence = {"source_only": True, "reference_read": False,
        "phase_policy": phase_evidence, "accepted": False,
        "drum_split_ratio_minimum": DRUM_SPLIT_RATIO}
    if runs is None:
        evidence["reason"] = "unstable_or_unsupported_phase_sequence"
        return None, evidence
    supported, model_evidence = model_phase_support(runs,
        {"beatthis0": p0, "beatthis1": p1, "allinone": pa})
    evidence["model_phase_support"] = model_evidence
    if not supported:
        evidence["reason"] = "independent_models_disagree_on_phase"
        return None, evidence
    gaps = transition_gaps(runs)
    evidence["transition_gaps"] = gaps
    if gaps is None:
        evidence["reason"] = "phase_switch_has_no_short_bar_grammar"
        return None, evidence
    geometry = base["map"]["source"]
    with sf.SoundFile(drums_path) as stem:
        if (stem.samplerate, stem.frames) != (geometry["sample_rate"],
                                               geometry["sample_frames"]):
            raise ValueError("drum stem does not share finished mix source clock")
    split_events = []
    for start, end in gaps:
        if min(p0[start], p1[start]) < .35 or min(p0[end], p1[end]) < .35:
            evidence["reason"] = "weak_transition_endpoint_barline"
            return None, evidence
        legal = list(range(start+2, end-1))
        attack, details = local_drum_attacks(drums_path, grid[legal])
        strength = dict(zip(legal, attack))
        split, decision = choose_internal_bar(start, end, strength, p0, p1)
        split_events.append({"start_pulse": start, "end_pulse": end,
                             "attack_geometry": details, "split_decision": decision})
        if split is None:
            evidence["transition_decisions"] = split_events
            evidence["reason"] = "ambiguous_internal_barline"
            return None, evidence
        split_events[-1]["split_pulse"] = split
    evidence["transition_decisions"] = split_events
    result = deepcopy(base)
    def event(pulse, numerator):
        return {"pulse": float(pulse), "numerator": numerator,
                "denominator": 4, "grouping": [1]*numerator,
                "bar_action": "continue"}
    events = [event(0, 4)]
    for row in split_events:
        start, split, end = (row[key] for key in
                             ("start_pulse", "split_pulse", "end_pulse"))
        events.extend((event(start, split-start), event(split, end-split),
                       event(end, 4)))
    result["map"]["bar_anchor_pulse"] = 0.
    result["map"]["meter_events"] = events
    bars = render_bars(prepare_map(result["map"]))
    if bars["status"] != "rendered":
        raise ValueError("source-only phase switch map cannot render")
    result["bar_starts_seconds"] = bars["bar_events_seconds"]
    result["diagnostics"]["constant_grid_only"] = False
    evidence["accepted"] = True
    evidence["reason"] = "stable_multimodel_phase_with_drum_split"
    result["diagnostics"]["phase_switch_meter"] = evidence
    return result, evidence
