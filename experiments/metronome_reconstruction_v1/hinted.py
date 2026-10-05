"""Initial tap selects a discrete octave layer; its numeric value stops there.

Candidate BPMs, meters, offsets and scores are all prepared from audio evidence
before any tap is accepted. No time-signature hint is supported.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path

import numpy as np

from .grid import rational_pool, timestamps
from .infer import make_evidence, optimize, phase_seeds, score_candidate


def _fit_layer(evidence: dict, bpms: list[Fraction], config: dict) -> dict:
    coarse = []
    for bpm in bpms:
        period = 60 / float(bpm)
        for phase in phase_seeds(evidence, period, config):
            for meter in config["meters"]:
                for index in range(meter):
                    coarse.append(score_candidate(evidence, bpm, meter, phase + index * period, config))
    coarse.sort(key=lambda row: row["score"], reverse=True)
    starts, seen = [], set()
    for row in coarse:
        meter = row["time_signature"]["numerator"]
        key = (row["quarter_bpm"], meter, round(row["offset_seconds"] / row["period_seconds"]) % meter)
        if key not in seen:
            seen.add(key)
            starts.append(row)
            if len(starts) >= config["refine_candidates"]:
                break
    shifts = np.arange(-config["refine_radius_seconds"],
                       config["refine_radius_seconds"] + config["refine_step_seconds"] / 2,
                       config["refine_step_seconds"])
    refined = []
    for row in starts:
        bpm = Fraction(row["bpm_fraction"]["numerator"], row["bpm_fraction"]["denominator"])
        choices = [score_candidate(evidence, bpm, row["time_signature"]["numerator"],
                                  row["offset_seconds"] + shift, config) for shift in shifts]
        refined.append(max(choices, key=lambda item: item["score"]))
    ranked = sorted(coarse + refined, key=lambda row: row["score"], reverse=True)
    unique, seen = [], set()
    for row in ranked:
        meter = row["time_signature"]["numerator"]
        key = (row["quarter_bpm"], meter, round(row["offset_seconds"] / row["period_seconds"]) % meter)
        if key not in seen:
            unique.append(row)
            seen.add(key)
            if len(unique) == 20:
                break
    return {"best": ranked[0], "top_candidates": unique, "candidate_bpm_count": len(bpms)}


def prepare_audio_family(evidence: dict, config: dict) -> dict:
    """This function has no hint argument and cannot read reference files."""
    beat = evidence["channels"]["beat"]
    if (len(beat["probability"]) < 2 or len(beat["events"]) < config["minimum_audio_peak_events"]
            or float(np.ptp(beat["probability"])) <= 1e-12):
        return {"status": "insufficient_acoustic_evidence", "levels": [],
                "input_duration_seconds": evidence["duration"], "config": config}
    automatic = optimize(evidence, config)
    base = Fraction(automatic["bpm_fraction"]["numerator"], automatic["bpm_fraction"]["denominator"])
    pool = rational_pool(config["bpm_min"], config["bpm_max"], config["denominator_max"])
    values = np.asarray([float(value) for value in pool])
    # Neighborhood width comes from recording duration and the audio base,
    # never from tap accuracy, tap value or reference BPM.
    base_radius = max(0.25, 120 / max(evidence["duration"], 1))
    levels = []
    for power in range(-4, 5):
        scale = Fraction(2 ** power, 1) if power >= 0 else Fraction(1, 2 ** (-power))
        center = float(base * scale)
        radius = min(base_radius * float(scale), center * config["audio_neighbor_relative_cap"])
        indexes = np.flatnonzero(np.abs(values - center) <= radius + 1e-12)
        if not len(indexes):
            continue
        layer = _fit_layer(evidence, [pool[index] for index in indexes], config)
        levels.append({"power": power, "audio_center_bpm": center,
                       "audio_neighbor_radius_bpm": radius, **layer})
    return {
        "status": "audio_family_prepared", "audio_base_bpm": float(base),
        "audio_base_fraction": {"numerator": base.numerator, "denominator": base.denominator},
        "audio_only_original_proposal": automatic,
        "input_duration_seconds": evidence["duration"], "levels": levels, "config": config,
        "all_candidates_and_scores_prepared_before_hint": True,
        "time_signature_hint_accepted": False,
    }


def encode_tap_level(audio_base_bpm: float, initial_quarter_bpm_tap: float) -> dict:
    """Only a discrete integer is returned. No continuous hint feature exits."""
    tap = float(initial_quarter_bpm_tap)
    if not math.isfinite(tap) or tap <= 0:
        raise ValueError("Initial quarter-BPM tap must be finite and positive")
    relative = math.log2(tap / audio_base_bpm)
    lower = math.floor(relative)
    if abs(relative - lower - 0.5) <= 1e-10:
        return {"status": "ambiguous_octave_boundary", "power": None}
    return {"status": "selected", "power": math.floor(relative + 0.5)}


def select_from_family(family: dict, initial_quarter_bpm_tap: float | None = None) -> dict:
    if family["status"] != "audio_family_prepared":
        return {"status": "insufficient_acoustic_evidence", "quarter_bpm": None,
                "time_signature": None, "offset_seconds": None,
                "initial_tap_provided": initial_quarter_bpm_tap is not None}
    config = family["config"]
    if initial_quarter_bpm_tap is None:
        decision = {"status": "not_provided", "power": None}
        permitted = family["levels"]
    else:
        decision = encode_tap_level(family["audio_base_bpm"], initial_quarter_bpm_tap)
        if decision["power"] is None:
            return {"status": "ambiguous_initial_tap_unit", "quarter_bpm": None,
                    "time_signature": None, "offset_seconds": None, "initial_tap_provided": True,
                    "tap_unit_decision": decision, "audio_base_bpm": family["audio_base_bpm"]}
        permitted = [level for level in family["levels"] if level["power"] == decision["power"]]
        if not permitted:
            return {"status": "tap_unit_not_supported_by_audio_family", "quarter_bpm": None,
                    "time_signature": None, "offset_seconds": None, "initial_tap_provided": True,
                    "tap_unit_decision": decision, "audio_base_bpm": family["audio_base_bpm"]}
    selected = max(permitted, key=lambda level: level["best"]["score"])
    best = selected["best"]
    meter = best["time_signature"]["numerator"]
    bar = meter * best["period_seconds"]
    alternatives = selected["top_candidates"]
    rivals = [row for row in alternatives if row["quarter_bpm"] != best["quarter_bpm"]
              or row["time_signature"] != best["time_signature"]
              or abs((row["offset_seconds"] - best["offset_seconds"] + bar / 2) % bar - bar / 2)
              > best["period_seconds"] / 2]
    margin = best["score"] - rivals[0]["score"] if rivals else None
    flags = []
    if margin is not None and margin < config["ambiguity_score_margin"]:
        flags.append("close_competing_clock_within_selected_unit")
    for channel in ("beat", "downbeat"):
        if best[channel + "_evidence"]["weighted_smooth_f1"] < config["weak_evidence_f1"]:
            flags.append("weak_" + channel + "_agreement")
    # Raw tap BPM is intentionally absent. Receipt files can preserve what a
    # user entered, but it is not a score, initialization, refinement or output.
    return {
        **best, "status": "uncertain_fixed_map_proposal" if flags else "fixed_map_proposal",
        "input_duration_seconds": family["input_duration_seconds"],
        "confidence_flags": flags, "top_candidates": alternatives,
        "competing_clock_score_margin": margin,
        "initial_tap_provided": initial_quarter_bpm_tap is not None,
        "tap_unit_decision": decision, "selected_audio_layer_power": selected["power"],
        "audio_base_bpm": family["audio_base_bpm"],
        "audio_layer_center_bpm": selected["audio_center_bpm"],
        "audio_layer_neighbor_radius_bpm": selected["audio_neighbor_radius_bpm"],
        "hint_scope": "initial_section_only; global application relies on this experiment's constant-tempo assumption",
        "raw_tap_number_used_after_unit_selection": False,
        "time_signature_supplied": False,
        "all_candidates_and_scores_prepared_before_hint": True,
    }


def validate_hint_row(row: dict) -> None:
    allowed = {"id", "initial_quarter_bpm_tap", "scope", "origin"}
    extra = set(row) - allowed
    if extra:
        raise ValueError(f"Unsupported hint fields, including any meter/reference input: {sorted(extra)}")
    if row.get("scope", "initial_section") != "initial_section":
        raise ValueError("Only initial-section quarter-BPM tap hints are supported")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--audio", type=Path)
    inputs.add_argument("--evidence", type=Path)
    parser.add_argument("--tap-bpm", type=float)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config-tap-v2.json"))
    parser.add_argument("--checkpoint", type=Path, default=Path("samples/.experiment-state/metronome-v1/final0.ckpt"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.audio:
        import soundfile as sf
        import torch
        from beat_this.inference import Audio2Frames
        if not args.checkpoint.is_file():
            raise FileNotFoundError("Provide a local official checkpoint; this entry point does not download one")
        signal, sr = sf.read(args.audio, dtype="float32", always_2d=True)
        torch.set_num_threads(config["torch_threads"])
        tracker = Audio2Frames(str(args.checkpoint), device=config["device"], float16=False)
        beat, down = tracker(signal, sr)
        evidence = make_evidence(beat.cpu().numpy(), down.cpu().numpy(), len(signal) / sr, config)
    else:
        with np.load(args.evidence) as data:
            if int(data["fps"]) != config["fps"]:
                raise ValueError("Sensor frame rate does not match configuration")
            evidence = make_evidence(data["beat_logits"], data["downbeat_logits"], float(data["duration_seconds"]), config)
    family = prepare_audio_family(evidence, config)
    prediction = select_from_family(family, args.tap_bpm)
    if prediction.get("period_seconds"):
        prediction["quarter_clicks_seconds"] = timestamps(prediction["period_seconds"], prediction["offset_seconds"], evidence["duration"]).tolist()
        prediction["downbeats_seconds"] = timestamps(prediction["period_seconds"] * prediction["time_signature"]["numerator"], prediction["offset_seconds"], evidence["duration"]).tolist()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(prediction, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
