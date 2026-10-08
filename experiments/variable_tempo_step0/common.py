"""I/O and evaluation-only coordinate adapters for Variable Expansion Step 0."""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from tools.project_storage import resolve_path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data/samples"
PACKAGE = Path(__file__).parent


def read_json(path):
    return json.loads(resolve_path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(resolve_path(path).read_bytes()).hexdigest()


def nearest_rate(value, denominator=4):
    return Fraction(float(value)).limit_denominator(denominator)


def audio_time(event):
    # Master-relative fields already contain the approved offset. Never add it.
    for key in ("master_seconds", "time_seconds"):
        if key in event:
            return float(event[key])
    raise ValueError("No accepted audio-relative timestamp")


def bpm_value(event):
    for key in ("bpm_quarter", "bpm"):
        if key in event:
            return float(event[key])
    raise ValueError("No explicit quarter BPM")


def stored_reference(ref, support):
    """Read accepted event arrays; do not regenerate, shift or requalify them."""
    if "quarter_times_seconds" in ref:
        quarters = ref["quarter_times_seconds"]
        field = "quarter_times_seconds"
    elif "quarter_beats_seconds" in ref:
        quarters = ref["quarter_beats_seconds"]
        field = "quarter_beats_seconds"
    elif "beats_seconds" in ref:
        quarters = ref["beats_seconds"]
        field = "beats_seconds"
    elif "beat_times_seconds" in ref:
        quarters = ref["beat_times_seconds"]
        field = "beat_times_seconds"
    else:
        quarters = [e["master_seconds"] for e in ref["quarter_events"]]
        field = "quarter_events.master_seconds"
    if "downbeats_seconds" in ref:
        bars = ref["downbeats_seconds"]
    elif "bar_events" in ref:
        bars = [e["master_seconds"] for e in ref["bar_events"]]
    else:
        bars = [e["master_seconds"] for e in ref.get("quarter_events", [])
                if e.get("accent") or e.get("bar_start")]
    def inside(t):
        return any(start <= t < end for start, end in support)
    return {"quarter_times_seconds": sorted(float(t) for t in quarters if inside(float(t))),
            "downbeat_times_seconds": sorted(float(t) for t in bars if inside(float(t))),
            "quarter_field": field, "additional_offset_applied_seconds": 0}


def reference_segments(ref, support):
    states = []
    for event in sorted(ref["tempo_events"], key=audio_time):
        state = {"time": audio_time(event), "bpm": bpm_value(event)}
        if not states or state["bpm"] != states[-1]["bpm"]:
            states.append(state)
    result = []
    for support_start, support_end in support:
        for index, state in enumerate(states):
            start = max(support_start, state["time"])
            end = min(support_end, states[index + 1]["time"] if index + 1 < len(states) else support_end)
            if end > start:
                result.append({"start_seconds": start, "end_seconds": end,
                               "duration_seconds": end - start, "quarter_bpm": state["bpm"]})
    return result


def oracle_clock(segment, quarters, bars, meter=4):
    """Only rate and canonical phase leave this adapter; support stays hidden."""
    bpm = segment["quarter_bpm"]
    period = 60 / bpm
    within = [t for t in quarters if segment["start_seconds"] - 1e-7 <= t < segment["end_seconds"]]
    if not within:
        return None
    phase = within[0] % period
    down = [t for t in bars if segment["start_seconds"] - 1e-7 <= t < segment["end_seconds"]]
    return {"quarter_bpm": bpm, "period_seconds": period, "phase_seconds": phase,
            "meter": meter, "bar_phase_seconds": down[0] % (meter * period) if down else None}


def source_row(ident, path):
    import soundfile as sf
    path = resolve_path(path)
    info = sf.info(path)
    return {"id": ident, "audio_path": str(Path(path).resolve()),
            "sample_rate": info.samplerate, "sample_frames": info.frames,
            "channels": info.channels, "duration_seconds": info.frames / info.samplerate}


def describe(values):
    import numpy as np
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"count": 0}
    return {"count": len(values), "minimum": float(values.min()), "median": float(np.median(values)),
            "p90": float(np.quantile(values, .9)), "maximum": float(values.max())}
