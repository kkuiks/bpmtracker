"""Independent source-clock parsing and pre-prediction capability qualification."""

from __future__ import annotations

from fractions import Fraction
from contextlib import ExitStack
import hashlib
import math
from pathlib import Path
import re

import mido
import numpy as np
import soundfile as sf
import yaml


def effective_states(events: list[tuple[int, object]], default: object) -> tuple[list[dict], bool]:
    by_tick = {}
    for tick, value in events:
        if tick in by_tick and by_tick[tick] != value:
            raise ValueError(f"Conflicting clock declarations at tick {tick}")
        by_tick[tick] = value
    states = [{"tick": 0, "value": by_tick.get(0, default), "explicit": 0 in by_tick}]
    for tick, value in sorted(by_tick.items()):
        if tick and value != states[-1]["value"]:
            states.append({"tick": tick, "value": value, "explicit": True})
    return states, 0 in by_tick


def source_clock(path: Path) -> dict:
    midi = mido.MidiFile(path)
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError("Independent type-2 tracks and SMPTE time bases are unsupported")
    tempos, signatures, notes = [], [], []
    last_channel_tick, last_tick = 0, 0
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if not isinstance(tick, int) or tick < 0:
                raise ValueError("Invalid source MIDI tick")
            last_tick = max(last_tick, tick)
            if message.type == "set_tempo":
                if message.tempo <= 0:
                    raise ValueError("Nonpositive source tempo")
                tempos.append((tick, message.tempo))
            elif message.type == "time_signature":
                signatures.append((tick, (message.numerator, message.denominator)))
            if not message.is_meta:
                last_channel_tick = max(last_channel_tick, tick)
            if message.type == "note_on" and message.velocity > 0:
                notes.append(tick)
    tempo_states, explicit_tempo = effective_states(tempos, 500_000)
    meter_states, explicit_meter = effective_states(signatures, (4, 4))

    def seconds_at(tick):
        total = Fraction(0)
        for index, state in enumerate(tempo_states):
            end = min(tick, tempo_states[index + 1]["tick"] if index + 1 < len(tempo_states) else tick)
            total += Fraction(max(0, end - state["tick"]) * state["value"], midi.ticks_per_beat * 1_000_000)
            if end >= tick:
                break
        return float(total)

    return {
        "type": midi.type, "ticks_per_quarter": midi.ticks_per_beat,
        "tempo_declarations": len(tempos), "signature_declarations": len(signatures),
        "tempos": [{**state, "source_seconds": seconds_at(state["tick"])} for state in tempo_states],
        "signatures": [{"tick": state["tick"], "numerator": state["value"][0],
                        "denominator": state["value"][1], "explicit": state["explicit"],
                        "source_seconds": seconds_at(state["tick"])} for state in meter_states],
        "explicit_initial_tempo": explicit_tempo, "explicit_initial_meter": explicit_meter,
        "note_on_count": len(notes), "first_note_seconds": seconds_at(min(notes)) if notes else None,
        "last_channel_event_seconds": seconds_at(last_channel_tick),
        "last_track_event_seconds": seconds_at(last_tick),
    }


def periodic_events(period: float, phase: float, start: float, end: float) -> list[float]:
    """Reference construction independent of the estimator's grid implementation."""
    if not all(math.isfinite(value) for value in (period, phase, start, end)) or period <= 0 or end <= start:
        return []
    first = math.ceil((start - phase) / period - 1e-12)
    stop = math.ceil((end - phase) / period - 1e-12)
    return [phase + index * period for index in range(first, stop)
            if start <= phase + index * period < end]


def clock_compatibility(source: dict, stems: list[dict], protocol: dict) -> tuple[bool, list[str]]:
    problems = []
    expected_tempos = source["tempos"]
    expected_meters = source["signatures"]
    tolerance = protocol["rendered_stem_clock_tolerance_seconds_per_quarter"]
    for stem in stems:
        clock = stem["clock"]
        if len(clock["tempos"]) != len(expected_tempos):
            problems.append(f"{stem['id']}:tempo_section_count")
            continue
        for a, b in zip(expected_tempos, clock["tempos"]):
            if abs(a["value"] - b["value"]) / 1_000_000 > tolerance or abs(a["source_seconds"] - b["source_seconds"]) > tolerance:
                problems.append(f"{stem['id']}:tempo_map")
        a = [(m["source_seconds"], m["numerator"], m["denominator"]) for m in expected_meters]
        b = [(m["source_seconds"], m["numerator"], m["denominator"]) for m in clock["signatures"]]
        if a != b:
            problems.append(f"{stem['id']}:signature_map")
    return not problems, problems


def mixture_consistency(directory: Path, stem_ids: list[str], protocol: dict) -> dict:
    with ExitStack() as stack:
        mixture = stack.enter_context(sf.SoundFile(directory / "mix.wav"))
        stems = [stack.enter_context(sf.SoundFile(directory / "stems" / f"{ident}.wav")) for ident in stem_ids]
        if any((source.samplerate, source.channels, source.frames) !=
               (mixture.samplerate, mixture.channels, mixture.frames) for source in stems):
            return {"consistent": False, "reason": "source_audio_geometry_disagreement"}
        difference_energy = mixture_energy = maximum = 0.0
        frames = 0
        while mixture.tell() < mixture.frames:
            actual = mixture.read(65536, dtype="float64", always_2d=True)
            summed = np.zeros_like(actual)
            for source in stems:
                summed += source.read(len(actual), dtype="float64", always_2d=True)
            if not np.isfinite(actual).all() or not np.isfinite(summed).all():
                return {"consistent": False, "reason": "nonfinite_source_audio"}
            difference = actual - summed
            difference_energy += float(np.square(difference).sum())
            mixture_energy += float(np.square(actual).sum())
            maximum = max(maximum, float(np.max(abs(difference))))
            frames += len(actual)
    relative = math.sqrt(difference_energy / max(mixture_energy, 1e-30))
    allowance = protocol["mixture_stem_quantization_allowance"] * (len(stems) + 1) / 32768
    return {"consistent": relative <= protocol["mixture_stem_relative_rms_tolerance"] or maximum <= allowance,
            "frames": frames, "relative_rms_error": relative, "maximum_absolute_difference": maximum,
            "quantization_allowance": allowance, "does_not_verify_midi_audio_origin": True}


def qualify_track(directory: Path, protocol: dict) -> tuple[dict, dict | None]:
    ident = directory.name
    row = {"id": ident, "status": "data_error", "eligible": False,
           "capabilities": [], "reasons": [], "data_origin": "synthetic_mixture",
           "role": "development_pilot", "manual_judgments": 0}
    try:
        metadata = yaml.safe_load((directory / "metadata.yaml").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("stems"), dict):
            raise ValueError("Missing source metadata")
        midi_path, audio_path = directory / "all_src.mid", directory / "mix.wav"
        audio = sf.info(audio_path)
        if audio.frames <= 0 or audio.samplerate <= 0 or audio.channels not in (1, 2):
            raise ValueError("Invalid mixture geometry")
        source = source_clock(midi_path)
        if any(not isinstance(key, str) or not re.fullmatch(r"S\d{2,3}", key) for key in metadata["stems"]):
            raise ValueError("Unsupported stem identity")
        rendered = [key for key in sorted(metadata["stems"])
                    if (directory / "stems" / f"{key}.wav").is_file()]
        if not rendered:
            raise ValueError("No source audio files paired with the mixture")
        stems = [{"id": key, "clock": source_clock(directory / "MIDI" / f"{key}.mid")} for key in rendered]
        compatible, problems = clock_compatibility(source, stems, protocol)
        mixing = mixture_consistency(directory, rendered, protocol)
        flag_disagreements = [key for key in rendered if not metadata["stems"][key].get("audio_rendered")
                              or not metadata["stems"][key].get("midi_saved")]
        midi_digest = hashlib.sha256(midi_path.read_bytes()).hexdigest()
        matched = re.search(r"\bTR[A-Z0-9]{16}\b", str(metadata.get("lmd_midi_dir", "")))
        source_identity = str(metadata.get("UUID", midi_digest))
        group = f"msd:{matched.group()}" if matched else f"midi:{midi_digest}"
        row.update({"audio_path": str(audio_path.resolve()), "sample_rate": audio.samplerate,
                    "sample_frames": audio.frames, "channels": audio.channels,
                    "duration_seconds": audio.duration, "source_identity": source_identity,
                    "source_midi_sha256": midi_digest, "parent_group": group,
                    "grouping_level": "matched_recording" if matched else "exact_source_midi",
                    "rendered_source_count": len(stems), "source_clock": source,
                    "rendered_clock_compatible": compatible, "rendered_clock_problems": problems,
                    "mixture_stem_consistency": mixing,
                    "metadata_bookkeeping_disagreements": flag_disagreements,
                    "rendered_note_on_count": sum(stem["clock"]["note_on_count"] for stem in stems),
                    "sensor_training_overlap": "unknown", "absolute_audio_origin_verified": False})
        reasons = row["reasons"]
        if audio.duration < protocol["minimum_audio_duration_seconds"]:
            reasons.append("too_short")
        if row["rendered_note_on_count"] < protocol["minimum_note_on_events"]:
            reasons.append("insufficient_source_events")
        if not compatible:
            reasons.append("rendered_source_clock_disagreement")
        if protocol["require_mixture_stem_consistency"] and not mixing["consistent"]:
            reasons.append("mixture_does_not_match_paired_stems")
        if not source["explicit_initial_tempo"]:
            reasons.append("missing_explicit_initial_tempo")
        if len(source["tempos"]) != 1:
            reasons.append("variable_encoded_tempo")
        if len(source["signatures"]) != 1:
            reasons.append("variable_encoded_meter")
        tempo = source["tempos"][0]["value"]
        bpm = Fraction(60_000_000, tempo)
        if not protocol["quarter_bpm_range"][0] <= bpm <= protocol["quarter_bpm_range"][1]:
            reasons.append("unsupported_encoded_bpm")
        signature = source["signatures"][0]
        meter = [signature["numerator"], signature["denominator"]]
        if source["explicit_initial_meter"] and meter not in protocol["supported_meters"]:
            reasons.append("unsupported_encoded_meter")
        if reasons:
            row["status"] = "excluded_scope"
            return row, None

        capabilities = ["encoded_quarter_bpm", "bpm_implied_drift"]
        if source["explicit_initial_meter"]:
            capabilities.append("encoded_meter")
        row.update(status="qualified_partial", eligible=True, capabilities=capabilities)
        notes = ["Absolute audio origin is not independently established; absolute phase is unscored."]
        if flag_disagreements:
            notes.append("Metadata bookkeeping flags disagree with paired files; mixture/stem consistency establishes the input pairing.")
        if not source["explicit_initial_meter"]:
            notes.append("Implicit MIDI 4/4 is not treated as a meter annotation.")
        row["qualification_notes"] = notes
        starts = [stem["clock"]["first_note_seconds"] for stem in stems if stem["clock"]["first_note_seconds"] is not None]
        support_start = min(starts) if starts else 0.0
        support_end = min(audio.duration, max(stem["clock"]["last_channel_event_seconds"] for stem in stems))
        reference = {
            "id": ident, "kind": "encoded_source_midi_clock", "capabilities": capabilities,
            "quarter_bpm": float(bpm), "quarter_bpm_fraction": {"numerator": bpm.numerator, "denominator": bpm.denominator},
            "period_seconds": tempo / 1_000_000,
            "time_signature": {"numerator": meter[0], "denominator": meter[1]} if source["explicit_initial_meter"] else None,
            "source_clock_zero_seconds": 0.0,
            "audio_offset_seconds": None, "absolute_audio_origin_verified": False,
            "source_support_seconds": [support_start, support_end],
            "quarter_source_seconds": periodic_events(tempo / 1_000_000, 0, support_start, support_end),
            "downbeat_source_seconds": periodic_events(tempo / 1_000_000 * meter[0] * 4 / meter[1], 0, support_start, support_end) if source["explicit_initial_meter"] else None,
            "phase_reference_limit": "Source-axis events are not verified audio-relative phase references.",
            "reference_creation_uses_model_predictions": False,
        }
        return row, reference
    except Exception as exc:
        row["reasons"].append("source_data_error")
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row, None


def qualify_dataset(root: Path, protocol: dict) -> tuple[list[dict], dict[str, dict]]:
    rows, references = [], {}
    for number in range(protocol["track_ids"]["first"], protocol["track_ids"]["last"] + 1):
        row, reference = qualify_track(root / f"Track{number:05d}", protocol)
        rows.append(row)
        if reference is not None:
            references[row["id"]] = reference
    return rows, references
