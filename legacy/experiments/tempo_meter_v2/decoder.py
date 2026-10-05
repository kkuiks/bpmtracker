"""Sparse, source-only joint tempo and meter proposal for finished audio.

This is an experiment, not a calibrated meter recognizer. It combines native
Beat This frame evidence with an independently computed spectral-flux envelope.
The search never reads a reference, a selected legacy clock, or a meter hint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import soxr


@dataclass(frozen=True)
class Config:
    min_quarter_bpm: float = 35.0
    max_quarter_bpm: float = 320.0
    onset_rate: int = 100
    analysis_sample_rate: int = 22050
    fft_size: int = 1024
    tempo_window_seconds: float = 12.0
    tempo_hop_seconds: float = 4.0
    tempo_options: int = 4
    boundary_hop_seconds: float = 0.1
    boundary_tolerance_seconds: float = 0.15
    start_search_seconds: float = 4.0
    beam_per_boundary: int = 3
    max_transitions: int = 3_000_000
    max_cpu_seconds: float = 180.0
    min_coverage_fraction: float = 0.95


# A fixed, general initial vocabulary. It is never populated from test labels.
# Groupings express the scoring template and remain hypotheses in the output.
METER_TEMPLATES = (
    (2, 4, (1, 1)), (3, 4, (1, 1, 1)), (4, 4, (1, 1, 1, 1)),
    (5, 4, (1, 1, 1, 1, 1)), (6, 4, (1, 1, 1, 1, 1, 1)),
    (7, 4, (1, 1, 1, 1, 1, 1, 1)), (8, 4, (1,) * 8),
    (2, 2, (1, 1)), (4, 2, (1, 1, 1, 1)),
    (5, 8, (2, 3)), (6, 8, (3, 3)), (7, 8, (2, 2, 3)),
    (9, 8, (3, 3, 3)), (12, 8, (3, 3, 3, 3)),
)


def _validate(config: Config, beat: np.ndarray, down: np.ndarray, fps: float) -> None:
    if not isinstance(config, Config):
        raise TypeError("config must be Config")
    if beat.ndim != 1 or down.shape != beat.shape or not np.isfinite(beat).all() or not np.isfinite(down).all():
        raise ValueError("beat and downbeat logits must be finite equal-length vectors")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("positive logit frame rate required")
    for name in ("onset_rate", "analysis_sample_rate", "fft_size", "tempo_options", "beam_per_boundary", "max_transitions"):
        value = getattr(config, name)
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    for name in ("min_quarter_bpm", "max_quarter_bpm", "tempo_window_seconds", "tempo_hop_seconds",
                 "boundary_hop_seconds", "boundary_tolerance_seconds", "start_search_seconds",
                 "max_cpu_seconds", "min_coverage_fraction"):
        value = getattr(config, name)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if config.min_quarter_bpm >= config.max_quarter_bpm or config.min_coverage_fraction > 1:
        raise ValueError("empty BPM range or invalid coverage bound")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def spectral_flux_from_audio(path: Path, config: Config) -> tuple[np.ndarray, np.ndarray, dict]:
    """Three-band positive spectral change from the canonical decoded WAV."""
    info = sf.info(path)
    if not info.format.startswith("WAV") or info.frames <= 0:
        raise ValueError("source must be a nonempty decoded WAV")
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        raise ValueError("source audio must be finite")
    mono = audio.mean(axis=1)
    if rate != config.analysis_sample_rate:
        mono = soxr.resample(mono, rate, config.analysis_sample_rate, quality="HQ")
    hop = round(config.analysis_sample_rate / config.onset_rate)
    fft_size = config.fft_size
    padded = np.pad(mono, (fft_size // 2, fft_size // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, fft_size)[::hop]
    frequency = np.fft.rfftfreq(fft_size, 1 / config.analysis_sample_rate)
    bands = tuple((frequency >= lo) & (frequency < hi) for lo, hi in ((30, 200), (200, 2000), (2000, 10000)))
    weights = np.hanning(fft_size)
    previous = np.zeros(fft_size // 2 + 1)
    chunks = []
    for start in range(0, len(frames), 1024):
        spectrum = np.log1p(10 * np.abs(np.fft.rfft(frames[start:start + 1024] * weights, axis=1)))
        change = np.maximum(0, np.diff(np.vstack((previous, spectrum)), axis=0))
        chunks.append(np.stack([change[:, mask].mean(axis=1) for mask in bands], axis=1))
        previous = spectrum[-1]
    features = np.concatenate(chunks)
    scale = np.maximum(np.quantile(features, 0.9, axis=0), 1e-8)
    strength = np.minimum(features / scale, 8).mean(axis=1)
    times = np.arange(len(strength)) * hop / config.analysis_sample_rate
    return times, strength, {"sample_rate": info.samplerate, "sample_frames": info.frames,
                             "onset_hop_samples": hop, "onset_analysis_sample_rate": config.analysis_sample_rate,
                             "onset_bands_hz": ((30, 200), (200, 2000), (2000, 10000))}


def _robust(values: np.ndarray) -> np.ndarray:
    median = float(np.median(values))
    scale = float(np.quantile(values, 0.9) - np.quantile(values, 0.1))
    return np.tanh((values - median) / max(scale, 1e-6) * 2)


def _autocorr(signal: np.ndarray, lags: np.ndarray) -> np.ndarray:
    signal = signal - signal.mean()
    denominator = float(np.dot(signal, signal))
    if denominator < 1e-8:
        return np.zeros(len(lags))
    # FFT convolution is bounded by the local 12-second window, not song length.
    size = 1 << (2 * len(signal) - 1).bit_length()
    spectrum = np.fft.rfft(signal, n=size)
    correlation = np.fft.irfft(spectrum * np.conj(spectrum), n=size)[:len(signal)]
    return correlation[lags] / denominator


def local_tempo_candidates(beat: np.ndarray, fps: float, onset_times: np.ndarray,
                           onset: np.ndarray, duration: float, config: Config) -> list[dict]:
    """Independent onset and logit autocorrelation; no selected beat events."""
    centers = np.arange(0, duration + config.tempo_hop_seconds, config.tempo_hop_seconds)
    results = []
    for center in centers:
        half = config.tempo_window_seconds / 2
        beat_part = _robust(beat[max(0, round((center-half)*fps)):min(len(beat), round((center+half)*fps))])
        onset_part = _robust(onset[max(0, np.searchsorted(onset_times, center-half)):min(len(onset), np.searchsorted(onset_times, center+half))])
        proposed = []
        for signal, frame_rate, source in ((beat_part, fps, "beat_logits"),
                                            (onset_part, 1/(onset_times[1]-onset_times[0]), "audio_onset")):
            lo = max(1, math.ceil(60 * frame_rate / config.max_quarter_bpm))
            hi = min(len(signal)-1, math.floor(60 * frame_rate / config.min_quarter_bpm))
            if hi <= lo:
                continue
            lags = np.arange(lo, hi + 1)
            values = _autocorr(signal, lags)
            peaks = np.flatnonzero((values >= np.r_[-np.inf, values[:-1]]) &
                                   (values >= np.r_[values[1:], -np.inf]))
            for index in sorted(peaks, key=lambda i: -values[i])[:config.tempo_options]:
                bpm = 60 * frame_rate / lags[index]
                if values[index] > 0:
                    proposed.append((bpm, float(values[index]), source))
        # Explicit half/double levels prevent a single dominant subdivision
        # from defining the musical quarter. These remain competing hypotheses.
        augmented = []
        for bpm, strength, source in proposed:
            for factor in (0.5, 1.0, 2.0):
                rate = bpm * factor
                if config.min_quarter_bpm <= rate <= config.max_quarter_bpm:
                    augmented.append((rate, strength * (1 if factor == 1 else 0.7), source))
        options = []
        for bpm, strength, source in sorted(augmented, key=lambda item: -item[1]):
            if all(abs(math.log(bpm / old["quarter_bpm"])) > 0.025 for old in options):
                options.append({"quarter_bpm": float(bpm), "strength": strength, "source": source})
            if len(options) >= config.tempo_options:
                break
        results.append({"center_seconds": float(center), "candidates": options})
    return results


def _sample(times: np.ndarray, values: np.ndarray, points: np.ndarray) -> np.ndarray:
    return np.interp(points, times, values, left=0.0, right=0.0)


def _boundaries(beat_times: np.ndarray, beat: np.ndarray, down: np.ndarray,
                onset_times: np.ndarray, onset: np.ndarray, duration: float, config: Config) -> np.ndarray:
    """One sharpened source-only boundary candidate per coarse time bucket."""
    coarse = np.arange(0, duration, config.boundary_hop_seconds)
    combined = .65 * down + .20 * beat + .15 * _sample(onset_times, onset, beat_times)
    candidates = [0.0]
    for target in coarse[1:]:
        lo = np.searchsorted(beat_times, target - config.boundary_hop_seconds / 2)
        hi = np.searchsorted(beat_times, target + config.boundary_hop_seconds / 2, side="right")
        if hi <= lo:
            candidates.append(float(target))
        else:
            index = lo + int(np.argmax(combined[lo:hi]))
            candidates.append(float(beat_times[index]))
    candidates.append(float(duration))
    return np.unique(np.clip(candidates, 0, duration))


def _template_positions(meter: tuple[int, int, tuple[int, ...]]) -> np.ndarray:
    groups = meter[2]
    return np.r_[0, np.cumsum(groups)[:-1]] / meter[0]


def _bar_evidence(start: float, end: float, meter: tuple[int, int, tuple[int, ...]],
                  beat_times: np.ndarray, beat: np.ndarray, down: np.ndarray,
                  onset_times: np.ndarray, onset: np.ndarray, beat_peak_times: np.ndarray,
                  down_peak_times: np.ndarray) -> tuple[float, tuple[float, float, float]]:
    length = end - start
    phases = _template_positions(meter)
    primary = start + length * phases
    offbeat = start + length * ((phases + np.r_[phases[1:], 1]) / 2)
    beat_score = float(np.mean(_sample(beat_times, beat, primary) - .5 * _sample(beat_times, beat, offbeat)))
    down_score = float(_sample(beat_times, down, np.array([start]))[0] -
                       .5 * _sample(beat_times, down, np.array([start + length / 2]))[0])
    audio_score = float(np.mean(_sample(onset_times, onset, primary) -
                                .5 * _sample(onset_times, onset, offbeat)))
    # Time weighting prevents short bars from winning merely by producing more
    # observations. Scores are uncalibrated and only rank source hypotheses.
    observed = beat_peak_times[np.searchsorted(beat_peak_times, start):np.searchsorted(beat_peak_times, end)]
    unexplained = int(np.count_nonzero(np.min(np.abs(observed[:, None] - primary[None, :]), axis=1) > .08)) if len(observed) else 0
    observed_down = down_peak_times[np.searchsorted(down_peak_times, start):np.searchsorted(down_peak_times, end)]
    unexplained_down = int(np.count_nonzero(np.abs(observed_down - start) > .08))
    total = length * (.65 * beat_score + .50 * down_score + .35 * audio_score) - .55 * unexplained - .7 * unexplained_down
    return total, (beat_score, down_score, audio_score)


@dataclass
class _State:
    end_index: int
    score: float
    previous: _State | None
    meter_index: int | None
    quarter_bpm: float | None
    bars: int
    start_seconds: float


def infer_from_evidence(beat_logits: np.ndarray, downbeat_logits: np.ndarray, fps: float,
                        onset_times: np.ndarray, onset_strength: np.ndarray, source: dict,
                        *, config: Config | None = None) -> dict:
    """Infer a source-time map from separate acoustic evidence vectors.

    This lower-level entrypoint is also used for constructed decoder probes.
    It accepts physical source identity only; no reference or selected clock.
    """
    config = config or Config()
    beat = np.asarray(beat_logits, dtype=float)
    down = np.asarray(downbeat_logits, dtype=float)
    onset_times = np.asarray(onset_times, dtype=float)
    onset_strength = np.asarray(onset_strength, dtype=float)
    _validate(config, beat, down, fps)
    if (onset_times.ndim != 1 or onset_strength.shape != onset_times.shape or len(onset_times) < 2 or
            not np.isfinite(onset_times).all() or not np.isfinite(onset_strength).all() or
            onset_times[0] < 0 or np.any(np.diff(onset_times) <= 0)):
        raise ValueError("onset evidence must have increasing finite source times")
    if set(source) != {"sha256", "sample_rate", "sample_frames"} or not isinstance(source["sha256"], str):
        raise ValueError("source must contain only physical hash and sample geometry")
    duration = source["sample_frames"] / source["sample_rate"]
    if duration <= 0 or len(beat) / fps < duration - 1 / fps or onset_times[-1] < duration - .03:
        raise ValueError("evidence does not cover the source")
    started = time.process_time()
    beat_times = np.arange(len(beat)) / fps
    beat = _robust(beat)
    down = _robust(down)
    onset = _robust(onset_strength)
    peak_indices = np.flatnonzero((beat > .5) & (beat >= np.r_[-np.inf, beat[:-1]]) &
                                   (beat > np.r_[beat[1:], -np.inf]))
    beat_peak_times = beat_times[peak_indices]
    down_peak_indices = np.flatnonzero((down > .5) & (down >= np.r_[-np.inf, down[:-1]]) &
                                        (down > np.r_[down[1:], -np.inf]))
    down_peak_times = beat_times[down_peak_indices]
    windows = local_tempo_candidates(beat, fps, onset_times, onset, duration, config)
    resources = {"transition_comparisons": 0, "cpu_seconds": None, "boundary_candidates": 0,
                 "tempo_windows": len(windows)}
    base = {"status": "unresolved", "map": None, "bar_starts_seconds": [], "beat_times_seconds": [],
            "diagnostics": {"reason": None, "full_source_contract_validated": False,
                            "calibrated_confidence": False, "reference_used_for_prediction": False},
            "resources": resources, "evidence_provenance": {
                "beat_logits_sha256": hashlib.sha256(np.asarray(beat_logits, dtype="<f8").tobytes()).hexdigest(),
                "downbeat_logits_sha256": hashlib.sha256(np.asarray(downbeat_logits, dtype="<f8").tobytes()).hexdigest(),
                "onset_strength_sha256": hashlib.sha256(np.asarray(onset_strength, dtype="<f8").tobytes()).hexdigest(),
                "source": source.copy(), "reference_used": False}, "configuration": asdict(config)}

    def finish(reason: str) -> dict:
        base["diagnostics"]["reason"] = reason
        resources["cpu_seconds"] = time.process_time() - started
        return base

    if not any(window["candidates"] for window in windows):
        return finish("no_local_periodicity")
    boundary = _boundaries(beat_times, beat, down, onset_times, onset, duration, config)
    resources["boundary_candidates"] = len(boundary)
    beams: list[list[_State]] = [[] for _ in boundary]
    emission_cache: dict[tuple[int, int, int], float] = {}
    for i, t in enumerate(boundary):
        if t > config.start_search_seconds:
            break
        beams[i].append(_State(i, -0.4 * t, None, None, None, 0, float(t)))

    for i, start in enumerate(boundary[:-1]):
        if not beams[i]:
            continue
        if time.process_time() - started > config.max_cpu_seconds:
            return finish("budget_exceeded_cpu")
        nearest_window = min(len(windows)-1, max(0, round(start/config.tempo_hop_seconds)))
        local = windows[nearest_window]["candidates"]
        for state in beams[i]:
            options = [x["quarter_bpm"] for x in local]
            if state.quarter_bpm is not None and all(abs(math.log(state.quarter_bpm / x)) > .01 for x in options):
                options.append(state.quarter_bpm)
            for meter_index, meter in enumerate(METER_TEMPLATES):
                quarters = 4 * meter[0] / meter[1]
                for proposed_bpm in options:
                    expected = start + 60 * quarters / proposed_bpm
                    left = np.searchsorted(boundary, expected - config.boundary_tolerance_seconds)
                    right = np.searchsorted(boundary, expected + config.boundary_tolerance_seconds, side="right")
                    for j in range(left, min(right, len(boundary))):
                        if j <= i or boundary[j] - start < .15:
                            continue
                        resources["transition_comparisons"] += 1
                        if resources["transition_comparisons"] > config.max_transitions:
                            return finish("budget_exceeded_transitions")
                        bpm = 60 * quarters / (boundary[j] - start)
                        if not config.min_quarter_bpm <= bpm <= config.max_quarter_bpm:
                            continue
                        cache_key = (i, j, meter_index)
                        emission = emission_cache.get(cache_key)
                        if emission is None:
                            emission, _ = _bar_evidence(start, boundary[j], meter, beat_times, beat, down,
                                                        onset_times, onset, beat_peak_times, down_peak_times)
                            emission_cache[cache_key] = emission
                        local_prior = -1.5 * abs(math.log(bpm / proposed_bpm))
                        tempo_change = (0 if state.quarter_bpm is None else
                                        -3.0 * abs(math.log(bpm / state.quarter_bpm)))
                        meter_change = (0 if state.meter_index is None or state.meter_index == meter_index else -1.0)
                        value = state.score + emission + local_prior + tempo_change + meter_change
                        candidate = _State(j, value, state, meter_index, bpm, state.bars+1, state.start_seconds)
                        target = beams[j]
                        target.append(candidate)
                        target.sort(key=lambda item: item.score, reverse=True)
                        if len(target) > config.beam_per_boundary:
                            target.pop()

    resources["distinct_bar_emissions"] = len(emission_cache)
    eligible = [state for i, states in enumerate(beams) for state in states if state.bars > 0 and
                (boundary[i] - state.start_seconds) / duration >= config.min_coverage_fraction]
    if not eligible:
        return finish("insufficient_coverage_or_supported_path")
    best = max(eligible, key=lambda state: state.score - .4 * (duration-boundary[state.end_index]))
    path = []
    state = best
    while state.previous is not None:
        parent = state.previous
        path.append((float(boundary[parent.end_index]), float(boundary[state.end_index]),
                     METER_TEMPLATES[state.meter_index], state.quarter_bpm))
        state = parent
    path.reverse()
    if not path:
        return finish("no_bars")

    knots = [{"pulse": 0.0, "source_seconds": path[0][0]}]
    meters = []
    position = 0.0
    for start, end, meter, bpm in path:
        signature = (meter[0], meter[1], list(meter[2]))
        if not meters or (meters[-1]["numerator"], meters[-1]["denominator"], meters[-1]["grouping"]) != signature:
            meters.append({"pulse": position, "numerator": meter[0], "denominator": meter[1],
                           "grouping": list(meter[2]), "bar_action": "continue"})
        position += 4 * meter[0] / meter[1]
        knots.append({"pulse": position, "source_seconds": end})
    support = [path[0][0], path[-1][1]]
    proposal = {"schema_version": 1, "source": source.copy(), "clock_knots": knots,
                "quarters_per_pulse": {"numerator": 1, "denominator": 1},
                "meter_events": meters, "bar_anchor_pulse": 0.0, "shared_origin_id": None,
                "support_seconds": [support], "analysis_condition": "unhinted",
                "accepted": False, "semantic_status": "source-only joint hypothesis; meter and quarter unit unverified"}
    quarters = np.arange(0, math.floor(position) + 1, dtype=float)
    knot_quarters = np.array([k["pulse"] for k in knots])
    knot_times = np.array([k["source_seconds"] for k in knots])
    quarter_times = np.interp(quarters, knot_quarters, knot_times)
    quarter_times = quarter_times[(quarter_times >= support[0]) & (quarter_times < support[1])]
    selected_templates = {(meter[0], meter[1]) for _, _, meter, _ in path}
    aliases = []
    for selected in METER_TEMPLATES:
        if (selected[0], selected[1]) not in selected_templates:
            continue
        phase = _template_positions(selected)
        alternatives = [[other[0], other[1]] for other in METER_TEMPLATES
                        if other[:2] != selected[:2] and np.array_equal(_template_positions(other), phase)]
        if alternatives:
            aliases.append({"selected_meter": [selected[0], selected[1]],
                            "same_primary_observation_mask_meters": alternatives})
    base.update(status="proposed_map", map=proposal,
                beat_times_seconds=quarter_times.tolist(),
                bar_starts_seconds=[start for start, _, _, _ in path],
                diagnostics={**base["diagnostics"], "reason": None, "covered_fraction":
                             (support[1]-support[0])/duration, "uncovered_source_intervals":
                             [[a, b] for a, b in ((0.0, support[0]), (support[1], duration)) if b > a],
                             "bar_count": len(path), "meter_change_count": len(meters)-1,
                             "observational_meter_aliases": aliases,
                             "notation_uniqueness_certified": False,
                             "full_source_contract_validated": False})
    resources["cpu_seconds"] = time.process_time() - started
    return base


def infer_tempo_meter(audio_path: str | Path, beat_logits: np.ndarray, downbeat_logits: np.ndarray,
                      fps: float, *, config: Config | None = None, source_sha256: str | None = None) -> dict:
    """Top-level source-only inference API. No evaluation/reference argument exists."""
    config = config or Config()
    path = Path(audio_path)
    actual_hash = _sha256(path)
    if source_sha256 is not None and actual_hash != source_sha256:
        raise ValueError("source audio hash differs from bound input")
    times, onsets, geometry = spectral_flux_from_audio(path, config)
    source = {"sha256": actual_hash, "sample_rate": geometry["sample_rate"],
              "sample_frames": geometry["sample_frames"]}
    result = infer_from_evidence(beat_logits, downbeat_logits, fps, times, onsets, source, config=config)
    result["evidence_provenance"]["audio_feature_geometry"] = geometry
    return result
