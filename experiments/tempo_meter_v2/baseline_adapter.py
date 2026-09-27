"""New, deliberately simple map-completion control for frozen balanced clocks.

This is not part of the historical ``balanced_evidence`` route. It reads that
route's selected clock without changing any fitted time or selected beat, then
uses source-only Beat This logits to propose one pulse unit, constant meter and
bar phase. A missing clock, weak downbeats or ambiguous physical hypotheses
produces ``unresolved``. No reference, tap value or per-song setting enters.

The output map uses musical quarter coordinates and is compatible with the
existing music-map contract. Its support is limited to complete bars within
the selected clock's physical support. It is an unaccepted comparison control,
not a correction to the original baseline or a full-song accuracy claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Meter:
    numerator: int
    denominator: int
    grouping: tuple[int, ...]
    beat_offsets_quarters: tuple[float, ...]

    @property
    def quarters_per_bar(self) -> float:
        return 4 * self.numerator / self.denominator

    @property
    def label(self) -> str:
        return f"{self.numerator}/{self.denominator}"


METERS = (
    Meter(2, 4, (1, 1), (0., 1.)),
    Meter(3, 4, (1, 1, 1), (0., 1., 2.)),
    Meter(4, 4, (1, 1, 1, 1), (0., 1., 2., 3.)),
    Meter(5, 4, (1, 1, 1, 1, 1), (0., 1., 2., 3., 4.)),
    Meter(6, 4, (1, 1, 1, 1, 1, 1), (0., 1., 2., 3., 4., 5.)),
    Meter(4, 2, (1, 1, 1, 1), (0., 2., 4., 6.)),
    Meter(6, 8, (3, 3), (0., 1.5)),
    Meter(8, 4, (1,) * 8, tuple(float(i) for i in range(8))),
)


@dataclass(frozen=True)
class ControlConfig:
    # These are broad predeclared search bounds, not truth labels.
    units: tuple[Fraction, ...] = (Fraction(1, 2), Fraction(1), Fraction(2), Fraction(4))
    meters: tuple[Meter, ...] = METERS
    min_quarter_bpm: float = 35.
    max_quarter_bpm: float = 320.
    max_bar_seconds: float = 8.
    min_complete_bars: int = 4
    phase_step_quarters: Fraction = Fraction(1, 2)
    sample_radius_frames: int = 2
    min_mean_downbeat_logit: float = 0.
    min_positive_downbeat_fraction: float = .5
    min_score_margin_per_second: float = .05


def _config(value: ControlConfig | None) -> ControlConfig:
    config = value or ControlConfig()
    if not isinstance(config, ControlConfig):
        raise TypeError("config must be ControlConfig")
    if not config.units or not config.meters or any(u <= 0 for u in config.units):
        raise ValueError("unit and meter vocabularies must be nonempty and positive")
    if (config.min_quarter_bpm <= 0 or config.max_quarter_bpm <= config.min_quarter_bpm
            or config.max_bar_seconds <= 0 or config.min_complete_bars < 1
            or config.phase_step_quarters <= 0 or config.sample_radius_frames < 0
            or not 0 <= config.min_positive_downbeat_fraction <= 1
            or config.min_score_margin_per_second < 0):
        raise ValueError("invalid control bounds")
    return config


def _source(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("source must supply physical sample geometry")
    digest = value.get("sha256")
    rate, frames = value.get("sample_rate"), value.get("sample_frames")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in digest)
            or isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0
            or isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0):
        raise ValueError("source needs SHA-256, positive sample rate and frame count")
    return {"sha256": digest.lower(), "sample_rate": rate, "sample_frames": frames}


def _logits(values, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not np.isfinite(array).all():
        raise ValueError(f"{name} must be a finite one-dimensional logit array")
    return array


def _pool_from_binding(binding: dict) -> dict:
    path = Path(binding["path"])
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != binding["sha256"]:
        raise ValueError("selected candidate pool hash changed")
    return json.loads(contents)


def _selection(balanced: dict, source: dict, candidate_pool: dict | None):
    """Return the selected frozen clock and beats from either saved schema."""
    if not isinstance(balanced, dict):
        raise ValueError("balanced prediction must be an object")
    if balanced.get("references_used_for_prediction") or balanced.get("references_used_for_selection"):
        raise ValueError("reference-assisted selection is not a baseline input")
    source_hash = balanced.get("source_sha256") or balanced.get("source", {}).get("sha256")
    if source_hash != source["sha256"]:
        raise ValueError("balanced prediction and source hash differ")
    declared_source = balanced.get("source")
    if declared_source and any(declared_source.get(key) != source[key]
                               for key in ("sample_rate", "sample_frames")):
        raise ValueError("balanced prediction and source sample geometry differ")
    if "method" in balanced:
        candidate_set = balanced.get("candidate_set") or {}
        if candidate_set.get("reference_used_for_prediction") or candidate_set.get("anchor_input"):
            raise ValueError("reference-assisted candidate set is not a baseline input")
        selected = balanced["method"]
        candidate_id = selected.get("selected_candidate_id")
        beat_times = selected.get("prediction", {}).get("beats_seconds", [])
        clock = selected.get("clock") if candidate_id else None
        pool_binding = None
        pool_hash_verified = None
    else:
        if balanced.get("model") != "beat_this":
            raise ValueError("NTM balanced selection must use Beat This")
        selected = balanced["selections"]["balanced_evidence"]
        candidate_id = selected.get("candidate_id")
        beat_times = selected.get("prediction", [])
        pool_binding = balanced.get("candidate_source")
        clock = None
        pool_hash_verified = False
        if candidate_id:
            if candidate_pool is None:
                if not isinstance(pool_binding, dict):
                    raise ValueError("selected NTM candidate has no bound candidate pool")
                candidate_pool = _pool_from_binding(pool_binding)
                pool_hash_verified = True
            if candidate_pool.get("reference_used_for_prediction") or candidate_pool.get("anchor_input"):
                raise ValueError("reference-assisted candidate pool is not a baseline input")
            matches = [item for item in candidate_pool["candidates"] if item["id"] == candidate_id]
            if len(matches) != 1:
                raise ValueError("selected candidate is absent or duplicated in the bound pool")
            candidate = matches[0]
            clock = candidate["clock"]
            expected = [item["source_seconds"] for item in candidate["indexed_grid"]]
            if len(beat_times) != len(expected) or any(abs(a-b) > 1e-7 for a, b in zip(beat_times, expected)):
                raise ValueError("selected beats differ from the selected frozen candidate")
    beat_times = [float(t) for t in beat_times]
    if any(not math.isfinite(t) for t in beat_times) or any(b <= a for a, b in zip(beat_times, beat_times[1:])):
        raise ValueError("selected beat times must increase and be finite")
    return candidate_id, clock, beat_times, pool_binding, pool_hash_verified


def _clock_geometry(clock: dict) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    span = clock["pulse_index_span"]
    lo, hi = float(span[0]), float(span[1])
    knots = [float(v) for v in clock["knot_pulse_indices"] if lo < float(v) < hi]
    coefficients = [float(v) for v in clock["coefficients"]]
    if not lo < hi or len(coefficients) != len(clock["knot_pulse_indices"]) + 2:
        raise ValueError("frozen clock has invalid pulse geometry")
    pulses = np.asarray([lo, *knots, hi], dtype=np.float64)
    times = np.asarray([coefficients[0] + coefficients[1] * u + sum(
        delta * max(u - float(k), 0.) for k, delta in zip(clock["knot_pulse_indices"], coefficients[2:]))
        for u in pulses], dtype=np.float64)
    if not np.isfinite(times).all() or np.any(np.diff(pulses) <= 0) or np.any(np.diff(times) <= 0):
        raise ValueError("frozen clock must strictly increase")
    support = clock["support_seconds"]
    if len(support) != 2 or not float(support[0]) < float(support[1]):
        raise ValueError("frozen clock needs an increasing support interval")
    return pulses, times, (float(support[0]), float(support[1]))


def _sample(values: np.ndarray, times: np.ndarray, fps: float, radius: int) -> np.ndarray:
    frames = np.floor(times * fps + .5).astype(np.int64)
    if np.any(frames < 0) or np.any(frames >= len(values)):
        raise ValueError("hypothesis event exceeds raw-logit support")
    offsets = np.arange(-radius, radius + 1)
    indices = np.clip(frames[:, None] + offsets, 0, len(values) - 1)
    return np.max(values[indices], axis=1)


def _hypotheses(pulses, seconds, support, duration, beat, downbeat, fps, config):
    lower = max(0., seconds[0], support[0])
    upper = min(duration, seconds[-1], support[1], (len(beat) - 1) / fps,
                (len(downbeat) - 1) / fps)
    if upper <= lower:
        return [], [lower, upper]
    pulse_lower, pulse_upper = np.interp([lower, upper], seconds, pulses)
    results = []
    for unit in config.units:
        q = float(unit)
        # A selected latent pulse is converted to an explicit number of quarters.
        segment_quarter_bpm = 60 * q * np.diff(pulses) / np.diff(seconds)
        if (np.min(segment_quarter_bpm) < config.min_quarter_bpm
                or np.max(segment_quarter_bpm) > config.max_quarter_bpm):
            continue
        for meter in config.meters:
            bar_length = meter.quarters_per_bar / q
            if np.max(np.diff(seconds) / np.diff(pulses)) * bar_length > config.max_bar_seconds:
                continue
            count = int(round(meter.quarters_per_bar / float(config.phase_step_quarters)))
            if count < 1 or not math.isclose(count * float(config.phase_step_quarters),
                                             meter.quarters_per_bar, abs_tol=1e-9):
                raise ValueError("phase step must divide every candidate bar")
            for phase_index in range(count):
                anchor = pulses[0] + phase_index * float(config.phase_step_quarters) / q
                first = math.ceil((pulse_lower - anchor) / bar_length - 1e-10)
                last = math.floor((pulse_upper - anchor) / bar_length + 1e-10)
                bar_pulses = anchor + np.arange(first, last + 1, dtype=np.float64) * bar_length
                if len(bar_pulses) < config.min_complete_bars + 1:
                    continue
                # All tested schedules are complete bars inside frozen clock support.
                starts = bar_pulses[:-1]
                beat_pulses = (starts[:, None] + np.asarray(meter.beat_offsets_quarters)[None, :] / q).ravel()
                bar_times = np.interp(bar_pulses, pulses, seconds)
                beat_times = np.interp(beat_pulses, pulses, seconds)
                if (np.any(bar_times < 0) or np.any(bar_times > duration)
                        or np.any(beat_times < 0) or np.any(beat_times >= duration)):
                    continue
                beat_values = _sample(beat, beat_times, fps, config.sample_radius_frames)
                down_values = _sample(downbeat, bar_times[:-1], fps, config.sample_radius_frames)
                score = (float(beat_values.sum()) + float(down_values.sum())) / (upper - lower)
                results.append({"score_per_second": score, "unit": unit, "meter": meter,
                                "phase_index": phase_index, "bar_pulses": bar_pulses,
                                "bar_times": bar_times,
                                "mean_downbeat_logit": float(down_values.mean()),
                                "positive_downbeat_fraction": float(np.mean(down_values > 0)),
                                "mean_beat_logit": float(beat_values.mean())})
    results.sort(key=lambda item: (-item["score_per_second"], item["meter"].label,
                                   item["unit"], item["phase_index"]))
    return results, [lower, upper]


def _brief(item: dict) -> dict:
    return {"unit_quarters_per_latent_pulse": str(item["unit"]),
            "meter": item["meter"].label, "phase_index": item["phase_index"],
            "score_per_second": item["score_per_second"],
            "mean_downbeat_logit": item["mean_downbeat_logit"],
            "positive_downbeat_fraction": item["positive_downbeat_fraction"],
            "complete_bars": len(item["bar_pulses"]) - 1}


def complete_balanced_map(
    balanced: dict, beat_logits, downbeat_logits, fps: float, source: dict, *,
    candidate_pool: dict | None = None, config: ControlConfig | None = None,
) -> dict:
    """Complete a frozen selected clock with source-only musical hypotheses.

    The NTM schema resolves its selected clock from its SHA-bound candidate
    pool unless the caller supplies an already loaded pool for controlled use.
    This function never scores or reads a reference and never edits its inputs.
    """
    config = _config(config)
    source = _source(source)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be finite and positive")
    beat, downbeat = _logits(beat_logits, "beat logits"), _logits(downbeat_logits, "downbeat logits")
    if len(beat) != len(downbeat) or len(beat) < 2:
        raise ValueError("beat and downbeat logits must share a nonempty frame grid")
    candidate_id, clock, beat_times, pool_binding, pool_hash_verified = _selection(
        balanced, source, candidate_pool)
    base = {"schema_version": 1, "status": "unresolved", "map": None,
            "bar_starts_seconds": [], "beat_times_seconds": beat_times,
            "diagnostics": {"control": "new_balanced_map_completion_v1",
                            "frozen_selected_candidate_id": candidate_id,
                            "reference_used_for_inference": False,
                            "selected_beat_times_changed": False,
                            "selected_clock_times_changed": False,
                            "global_constant_meter_only": True,
                            "score_interpretation": "raw-logit event-versus-background sum per source second; uncalibrated",
                            "downbeat_sampling_radius_frames": config.sample_radius_frames,
                            "phase_step_quarters": str(config.phase_step_quarters)},
            "resources": {"hypotheses_scored": 0},
            "evidence_provenance": {"source_sha256": source["sha256"],
                                    "beat_logits_float64_sha256": hashlib.sha256(beat.astype("<f8").tobytes()).hexdigest(),
                                    "downbeat_logits_float64_sha256": hashlib.sha256(downbeat.astype("<f8").tobytes()).hexdigest(),
                                    "fps": float(fps), "candidate_pool_binding": pool_binding,
                                    "candidate_pool_hash_verified_by_adapter": pool_hash_verified}}
    if clock is None:
        base["diagnostics"]["reason"] = "no_frozen_selected_clock"
        return base
    pulses, seconds, support = _clock_geometry(clock)
    duration = source["sample_frames"] / source["sample_rate"]
    hypotheses, evidence_support = _hypotheses(pulses, seconds, support, duration,
                                               beat, downbeat, float(fps), config)
    base["resources"]["hypotheses_scored"] = len(hypotheses)
    base["diagnostics"]["frozen_clock_support_seconds"] = list(support)
    base["diagnostics"]["evidence_support_seconds"] = evidence_support
    base["diagnostics"]["top_hypotheses"] = [_brief(item) for item in hypotheses[:5]]
    if not hypotheses:
        base["diagnostics"]["reason"] = "no_valid_complete_bar_hypothesis"
        return base
    best = hypotheses[0]
    if (best["mean_downbeat_logit"] < config.min_mean_downbeat_logit
            or best["positive_downbeat_fraction"] < config.min_positive_downbeat_fraction):
        base["diagnostics"]["reason"] = "weak_downbeat_evidence"
        return base
    if (len(hypotheses) > 1 and best["score_per_second"] - hypotheses[1]["score_per_second"]
            < config.min_score_margin_per_second):
        base["diagnostics"]["reason"] = "ambiguous_unit_meter_or_phase"
        return base
    unit = float(best["unit"])
    meter = best["meter"]
    clock_knots = [{"pulse": float(u * unit), "source_seconds": float(t)}
                   for u, t in zip(pulses, seconds)]
    bar_starts = best["bar_times"].tolist()
    map_value = {"schema_version": 1, "source": source,
                 "clock_knots": clock_knots,
                 "support_seconds": [[bar_starts[0], bar_starts[-1]]],
                 "quarters_per_pulse": {"numerator": 1, "denominator": 1},
                 "meter_events": [{"pulse": float(pulses[0] * unit),
                                    "numerator": meter.numerator, "denominator": meter.denominator,
                                    "grouping": list(meter.grouping), "bar_action": "continue"}],
                 "bar_anchor_pulse": float(best["bar_pulses"][0] * unit),
                 "shared_origin_id": None, "analysis_condition": "unhinted"}
    base["status"] = "proposed_map"
    base["map"] = map_value
    base["bar_starts_seconds"] = bar_starts
    base["diagnostics"]["inferred_quarters_per_frozen_pulse"] = str(best["unit"])
    base["diagnostics"]["support_limited_to_complete_bars"] = True
    return base
