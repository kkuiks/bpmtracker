"""Prepare audio observations and run process-isolated tempo-map inference."""
from __future__ import annotations

import math
from pathlib import Path


def prepare_source(events: dict, family: dict | None = None) -> dict:
    """Prepare every source candidate before selecting the user's beat unit."""
    from .source import prepare
    return prepare(events, family)


def prepare_observations(beat_logits, downbeat_logits, waveform, sample_rate: int,
                         fixed_config: dict) -> tuple[dict, dict, dict]:
    """Use the existing final0 observations, fixed family, and frozen PCM sensor."""
    import numpy as np
    from algorithms.fixed.infer import make_evidence
    from algorithms.fixed.hinted import prepare_audio_family
    from .observations import event_peaks, pcm_flux

    if sample_rate <= 0 or waveform.ndim != 2 or len(waveform) == 0:
        raise ValueError("Select a non-empty mono or stereo audio range")
    duration = len(waveform) / sample_rate
    evidence = make_evidence(beat_logits, downbeat_logits, duration, fixed_config)
    times, weights = event_peaks(beat_logits)
    downbeat_times, downbeat_weights = event_peaks(downbeat_logits)
    pcm_times, pcm_weights = pcm_flux(waveform, sample_rate, duration)
    events = dict(times=times, weights=weights, downbeat_times=downbeat_times,
                  downbeat_weights=downbeat_weights, pcm_times=pcm_times,
                  pcm_weights=pcm_weights, duration=np.asarray(duration))
    family = prepare_audio_family(evidence, fixed_config)
    if not family.get("audio_only_original_proposal"):
        return events, {"available": False, "units": [], "duration_seconds": duration,
                        "reason": family.get("status", "no_source_clock")}, family
    return events, prepare_source(events, family), family


def initial_unit(prepared: dict, tap: float | None = None) -> dict:
    """Keep the original discrete-unit encoding; never invent a tempo target."""
    if not prepared.get("available") or not prepared.get("units"):
        return {"available": False, "reason": "no_source_clock"}
    if tap is None:
        if len(prepared["units"]) == 1:
            return {"available": True, "unit_id": prepared["units"][0]["id"]}
        return {"available": False, "reason": "initial_unit_required"}
    if not math.isfinite(tap) or tap <= 0:
        raise ValueError("Tap a positive approximate quarter BPM")
    from .source import encode
    return encode(prepared, tap)


def unit_choices(prepared: dict) -> list[dict]:
    return [{"unit_id": row["id"], "approximate_bpm": row["representative_bpm"]}
            for row in prepared.get("units", [])]


def predict(packet: dict) -> dict:
    """Run one prediction in a fresh worker; the frozen API has module hooks."""
    if not packet.get("unit", {}).get("available"):
        raise ValueError("Choose an available source beat unit before prediction")
    from .api import predict as predict_full
    return predict_full(packet)


def predict_with_trace(packet: dict):
    if not packet.get("unit", {}).get("available"):
        raise ValueError("Choose an available source beat unit before prediction")
    from .api import predict_with_trace as predict_full
    return predict_full(packet)


def configuration_path() -> Path:
    return Path(__file__).with_name("parameters.json")
