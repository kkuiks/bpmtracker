"""Source-only rational-BPM / constant-meter / global-offset fitting.

Beat This logits are the sensor. A candidate's quarter and bar lattices are
jointly scored across the entire input. No reference or dataset membership is
accepted by this module, and no per-track switches exist.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from scipy.fft import next_fast_len, rfft, rfftfreq
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from scipy.special import expit

from .grid import rational_pool, timestamps


def make_evidence(beat_logits, downbeat_logits, duration: float, config: dict) -> dict:
    channels = {}
    for name, logits in (("beat", beat_logits), ("downbeat", downbeat_logits)):
        logits = np.asarray(logits, dtype=np.float64)
        if logits.ndim != 1 or not np.isfinite(logits).all():
            raise ValueError(f"Nonfinite or non-vector {name} sensor output")
        probability = expit(logits)
        positions, _ = find_peaks(
            probability, height=config["peak_probability"],
            distance=config["peak_min_distance_frames"],
        )
        channels[name] = {
            "probability": probability,
            "smooth": gaussian_filter1d(probability, config["activation_smoothing_frames"]),
            "events": positions.astype(np.float64) / config["fps"],
            "weights": probability[positions],
        }
    return {"channels": channels, "duration": float(duration), "fps": config["fps"]}


def broad_candidates(evidence: dict, config: dict) -> tuple[list[Fraction], dict]:
    pool = rational_pool(config["bpm_min"], config["bpm_max"], config["denominator_max"])
    bpms = np.array([float(value) for value in pool])
    powers = {}
    for name, channel in evidence["channels"].items():
        p = channel["probability"]
        centered = p - np.mean(p)
        size = next_fast_len(max(2, len(p) * config["spectral_padding"]))
        frequency = rfftfreq(size, d=1 / evidence["fps"])
        spectrum = np.abs(rfft(centered * np.hanning(len(p)), n=size))
        powers[name] = (frequency, spectrum)
    bfreq, bpower = powers["beat"]
    dfreq, dpower = powers["downbeat"]
    beat = np.interp(bpms / 60, bfreq, bpower)
    bar = np.maximum.reduce([
        np.interp(bpms / (60 * meter), dfreq, dpower) for meter in config["meters"]
    ])
    beat /= max(float(beat.max()), 1e-12)
    bar /= max(float(bar.max()), 1e-12)
    ranks = (beat, bar, 0.7 * beat + 0.3 * bar)
    seed_indices = set()
    for rank in ranks:
        seed_indices.update(np.argsort(rank)[-config["spectral_seeds"]:].tolist())
    selected = set()
    radius = max(0.25, 120 / max(evidence["duration"], 1))
    for index in seed_indices:
        for scale in (0.5, 1, 2):
            center = bpms[index] * scale
            selected.update(np.flatnonzero(np.abs(bpms - center) <= radius).tolist())
    return [pool[index] for index in sorted(selected)], {
        "rational_pool_count": len(pool), "spectral_seed_count": len(seed_indices),
        "candidate_bpm_count": len(selected), "neighbor_radius_bpm": radius,
    }


def phase_seeds(evidence: dict, period: float, config: dict) -> list[float]:
    bins = max(16, int(np.ceil(period / config["coarse_phase_bin_seconds"])))
    channel = evidence["channels"]["beat"]
    times = np.arange(len(channel["probability"])) / evidence["fps"]
    indices = np.floor(np.remainder(times, period) / period * bins).astype(int) % bins
    weights = np.maximum(channel["probability"] - np.median(channel["probability"]), 0)
    folded = np.bincount(indices, weights=weights, minlength=bins)
    exposure = np.bincount(indices, minlength=bins)
    folded = folded / np.maximum(exposure, 1)
    folded = gaussian_filter1d(
        folded, max(0.5, config["residual_sigma_seconds"] * bins / period), mode="wrap"
    )
    candidates = []
    ranked = np.argsort(folded)[::-1]
    for index in ranked:
        phase = (index + 0.5) * period / bins
        if all(abs((phase - old + period / 2) % period - period / 2) > 0.04 for old in candidates):
            candidates.append(float(phase))
            if len(candidates) == config["phase_seeds"]:
                break
    return candidates or [0.0]


def channel_fit(channel: dict, period: float, offset: float, duration: float,
                config: dict) -> dict:
    grid = timestamps(period, offset, duration)
    events, weights = channel["events"], channel["weights"]
    precision = recall = f1 = 0.0
    residuals = np.empty(0)
    matched_times = np.empty(0)
    if len(grid) and len(events):
        index = np.rint((events - grid[0]) / period).astype(int)
        residual = events - (grid[0] + index * period)
        tolerance = min(config["matching_window_seconds"], period * config["matching_period_fraction"])
        keep = (index >= 0) & (index < len(grid)) & (np.abs(residual) <= tolerance)
        index, residual, w, times = index[keep], residual[keep], weights[keep], events[keep]
        reward = w * np.exp(-0.5 * (residual / config["residual_sigma_seconds"]) ** 2)
        # Capacity one: a source event supports its nearest grid point only, and
        # competing source events cannot all reward the same click.
        order = np.lexsort((np.abs(residual), -reward, index))
        if len(order):
            sorted_index = index[order]
            chosen = order[np.r_[True, sorted_index[1:] != sorted_index[:-1]]]
            total = float(reward[chosen].sum())
            precision = total / len(grid)
            recall = total / max(float(weights.sum()), 1e-12)
            f1 = 2 * precision * recall / max(precision + recall, 1e-12)
            residuals, matched_times = residual[chosen], times[chosen]
    abs_residual = np.abs(residuals)
    median = float(np.median(abs_residual)) if len(residuals) else None
    p95 = float(np.quantile(abs_residual, 0.95)) if len(residuals) else None
    slope = None
    if len(residuals) >= 3 and np.ptp(matched_times) > 0:
        centered = matched_times - np.mean(matched_times)
        slope = float(np.dot(centered, residuals - np.mean(residuals)) / np.dot(centered, centered))
    activation = 0.0
    if len(grid):
        activation = float(np.mean(np.interp(
            grid * config["fps"], np.arange(len(channel["smooth"])), channel["smooth"]
        )))
    return {
        "grid_count": len(grid), "source_peak_count": len(events),
        "matched_count": len(residuals), "grid_supported_fraction": precision,
        "evidence_explained_fraction": recall, "weighted_smooth_f1": f1,
        "median_absolute_residual_seconds": median, "p95_absolute_residual_seconds": p95,
        "mean_signed_residual_seconds": float(np.mean(residuals)) if len(residuals) else None,
        "residual_slope_seconds_per_second": slope, "mean_grid_activation": activation,
    }


def score_candidate(evidence: dict, bpm: Fraction | float, meter: int,
                    offset: float, config: dict) -> dict:
    value = float(bpm)
    period = 60 / value
    offset = float(offset % (meter * period))
    beat = channel_fit(evidence["channels"]["beat"], period, offset, evidence["duration"], config)
    downbeat = channel_fit(evidence["channels"]["downbeat"], meter * period, offset, evidence["duration"], config)
    residual = beat["median_absolute_residual_seconds"]
    drift = beat["residual_slope_seconds_per_second"]
    residual_penalty = min((residual or 0) / config["residual_sigma_seconds"], 1)
    drift_penalty = min(abs(drift or 0) * evidence["duration"] / config["residual_sigma_seconds"], 1)
    # A separately frozen diagnostic can remove only the reverse-coverage
    # term. The original experiment retains the default symmetric objective.
    objective = "grid_supported_fraction" if config.get("score_mode") == "grid_only" else "weighted_smooth_f1"
    score = (
        config["beat_weight"] * beat[objective]
        + config["downbeat_weight"] * downbeat[objective]
        + config["activation_weight"] * beat["mean_grid_activation"]
        - config["residual_penalty_weight"] * residual_penalty
        - config["drift_penalty_weight"] * drift_penalty
    )
    fraction = bpm if isinstance(bpm, Fraction) else Fraction(value).limit_denominator(config["denominator_max"])
    return {
        "quarter_bpm": value, "bpm_fraction": {"numerator": fraction.numerator, "denominator": fraction.denominator},
        "period_seconds": period, "time_signature": {"numerator": meter, "denominator": 4},
        "offset_seconds": offset, "offset_convention": "time of a canonical downbeat, modulo one bar, relative to unchanged audio zero",
        "score": float(score), "beat_evidence": beat, "downbeat_evidence": downbeat,
    }


def optimize(evidence: dict, config: dict, *, fixed_bpm: float | None = None) -> dict:
    if fixed_bpm is None:
        bpms, search = broad_candidates(evidence, config)
    else:
        # Used solely by the explicitly labeled oracle diagnostic, never by
        # the source-only inference runner.
        bpms, search = [float(fixed_bpm)], {"oracle_bpm": True, "candidate_bpm_count": 1}
    coarse = []
    for bpm in bpms:
        period = 60 / float(bpm)
        for phase in phase_seeds(evidence, period, config):
            for meter in config["meters"]:
                for beat_index in range(meter):
                    coarse.append(score_candidate(evidence, bpm, meter, phase + beat_index * period, config))
    coarse.sort(key=lambda row: row["score"], reverse=True)
    if not coarse:
        raise ValueError("No permitted tempo candidates")
    starts = []
    keys = set()
    for row in coarse:
        key = (row["quarter_bpm"], row["time_signature"]["numerator"],
               round(row["offset_seconds"] / row["period_seconds"]))
        if key not in keys:
            starts.append(row)
            keys.add(key)
            if len(starts) >= config["refine_candidates"]:
                break
    refined = []
    shifts = np.arange(-config["refine_radius_seconds"],
                       config["refine_radius_seconds"] + config["refine_step_seconds"] / 2,
                       config["refine_step_seconds"])
    for row in starts:
        bpm = float(row["quarter_bpm"]) if fixed_bpm is not None else Fraction(
            row["bpm_fraction"]["numerator"], row["bpm_fraction"]["denominator"]
        )
        choices = [score_candidate(evidence, bpm, row["time_signature"]["numerator"],
                                  row["offset_seconds"] + shift, config) for shift in shifts]
        refined.append(max(choices, key=lambda item: item["score"]))
    ranked = sorted(refined + coarse, key=lambda row: row["score"], reverse=True)
    octave_cache = {}
    def octave_leader(value):
        fraction = Fraction(value).limit_denominator(config["denominator_max"])
        if not (config["bpm_min"] <= value <= config["bpm_max"]) or abs(float(fraction) - value) > 1e-9:
            return None
        if value in octave_cache:
            return octave_cache[value]
        choices = []
        period = 60 / value
        for phase in phase_seeds(evidence, period, config):
            for meter in config["meters"]:
                for index in range(meter):
                    choices.append(score_candidate(evidence, fraction, meter, phase + index * period, config))
        leader = max(choices, key=lambda item: item["score"])
        leader = max([
            score_candidate(evidence, fraction, leader["time_signature"]["numerator"],
                            leader["offset_seconds"] + shift, config) for shift in shifts
        ], key=lambda item: item["score"])
        octave_cache[value] = leader
        return leader
    # Octave comparisons are actual competitors, not merely diagnostics. Do
    # not return a candidate whose explicitly tested octave scores better.
    if fixed_bpm is None:
        for _ in range(8):
            best = ranked[0]
            leaders = [octave_leader(best["quarter_bpm"] * scale) for scale in (0.5, 2)]
            ranked.extend(row for row in leaders if row is not None)
            ranked.sort(key=lambda row: row["score"], reverse=True)
            if ranked[0]["quarter_bpm"] == best["quarter_bpm"]:
                break
    best = ranked[0]
    octave = {}
    for name, scale in (("half", 0.5), ("double", 2)):
        value = best["quarter_bpm"] * scale
        leader = octave_leader(value)
        octave[name] = ({"available": True, "candidate": leader,
                         "best_minus_alternative_score": best["score"] - leader["score"]}
                        if leader is not None else
                        {"available": False, "bpm": value, "reason": "outside_frozen_candidate_domain"})
    alternatives = []
    seen = set()
    for row in ranked:
        key = (row["quarter_bpm"], row["time_signature"]["numerator"],
               round(row["offset_seconds"] / row["period_seconds"]) % row["time_signature"]["numerator"])
        if key not in seen:
            alternatives.append(row)
            seen.add(key)
            if len(alternatives) >= 20:
                break
    flags = []
    meaningful = [row for row in alternatives if row["quarter_bpm"] != best["quarter_bpm"]
                  or row["time_signature"] != best["time_signature"]
                  or abs((row["offset_seconds"] - best["offset_seconds"]
                          + best["time_signature"]["numerator"] * best["period_seconds"] / 2)
                         % (best["time_signature"]["numerator"] * best["period_seconds"])
                         - best["time_signature"]["numerator"] * best["period_seconds"] / 2)
                  > 0.5 * best["period_seconds"]]
    margin = best["score"] - meaningful[0]["score"] if meaningful else None
    if margin is not None and margin < config["ambiguity_score_margin"]:
        flags.append("close_competing_clock")
    for channel in ("beat", "downbeat"):
        if best[channel + "_evidence"]["weighted_smooth_f1"] < config["weak_evidence_f1"]:
            flags.append("weak_" + channel + "_agreement")
    if len(evidence["channels"]["beat"]["events"]) < 4:
        flags.append("insufficient_beat_events")
    return {
        **best, "status": "uncertain_fixed_map_proposal" if flags else "fixed_map_proposal",
        "input_duration_seconds": evidence["duration"], "confidence_flags": flags,
        "competing_clock_score_margin": margin, "candidate_search": search,
        "top_candidates": alternatives, "octave_alternatives": octave,
    }
