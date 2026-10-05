"""Freeze source-only BPM-grid rounding controls from an existing prediction set.

Keep the first clock phase and all internal change pulses. Round each segment's
quarter BPM, move later change times by integration, and cover the unchanged
physical source end with a recomputed terminal pulse. No owner map is opened.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

from .run_constant_grid11 import digest, read_bound, save

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from music_map_contract import interpolate_clock, prepare_map, render_bars


def quantize_prediction(prediction: dict, step_bpm: float) -> tuple[dict, list[dict]]:
    if not math.isfinite(step_bpm) or step_bpm <= 0:
        raise ValueError("step_bpm must be positive and finite")
    result = deepcopy(prediction)
    original = prepare_map(result["map"])
    knots = original["clock_knots"]
    unit = original["quarters_per_pulse"]["numerator"] / original[
        "quarters_per_pulse"]["denominator"]
    duration = original["duration_seconds"]
    if abs(knots[-1]["source_seconds"] - duration) > 1e-7:
        raise ValueError("prediction must declare a clock to physical source end")
    updated = [dict(knots[0])]
    segments = []
    for index, (first, last) in enumerate(zip(knots, knots[1:])):
        rate = 60 * (last["pulse"] - first["pulse"]) * unit / (
            last["source_seconds"] - first["source_seconds"])
        rounded = round(rate / step_bpm) * step_bpm
        if rounded <= 0:
            raise ValueError("rounded BPM must stay positive")
        if index == len(knots) - 2:
            end_time = duration
            end_pulse = updated[-1]["pulse"] + (
                end_time - updated[-1]["source_seconds"]) * rounded / (60 * unit)
        else:
            end_pulse = last["pulse"]
            end_time = updated[-1]["source_seconds"] + (
                end_pulse - updated[-1]["pulse"]) * 60 * unit / rounded
        if end_pulse <= updated[-1]["pulse"] or end_time <= updated[-1]["source_seconds"]:
            raise ValueError("rounded clock is not monotonic")
        updated.append({"pulse": float(end_pulse), "source_seconds": float(end_time)})
        segments.append({
            "original_bpm": rate,
            "rounded_bpm": rounded,
            "boundary_pulse": last["pulse"] if index < len(knots) - 2 else None,
            "original_end_seconds": last["source_seconds"],
            "rounded_end_seconds": end_time,
        })
    result["map"]["clock_knots"] = updated
    prepared = prepare_map(result["map"])
    rendered = render_bars(prepared)
    if rendered["status"] != "rendered":
        raise ValueError(f"rounded map cannot render bars: {rendered['status']}")
    first_pulse = math.ceil(updated[0]["pulse"] - 1e-9)
    last_pulse = math.floor(updated[-1]["pulse"] + 1e-9)
    support = prepared["support_seconds"]
    result["beat_times_seconds"] = [
        time for pulse in range(first_pulse, last_pulse + 1)
        if (time := interpolate_clock(updated, float(pulse))) < duration
        and any(lo - 1e-9 <= time < hi for lo, hi in support)]
    result["bar_starts_seconds"] = [
        time for time in rendered["bar_events_seconds"]
        if 0 <= time < duration and any(lo - 1e-9 <= time < hi for lo, hi in support)]
    result["diagnostics"]["bpm_quantization_control"] = {
        "source_only": True,
        "step_bpm": step_bpm,
        "first_clock_phase_preserved": True,
        "internal_change_pulses_preserved": True,
        "physical_source_end_preserved": True,
    }
    return result, segments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--step-bpm", type=float, choices=(0.5, 1.0), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new quantization output required")
    manifest = json.loads(args.candidate_manifest.read_text())
    if (manifest.get("complete") is not True or
            manifest.get("references_available_to_runner") is not False or
            len(manifest.get("rows", [])) != 11):
        raise ValueError("complete source-only eleven-song manifest required")
    output = args.output.resolve()
    prediction_dir = output / "predictions"
    prediction_dir.mkdir(parents=True)
    rows = []
    for item in manifest["rows"]:
        original = json.loads(read_bound(item["prediction"]).read_text())
        if original["map"]["source"] != item["source"]:
            raise ValueError(f"source clock mismatch: {item['id']}")
        result, segments = quantize_prediction(original, args.step_bpm)
        path = prediction_dir / (item["id"] + ".json")
        save(path, result)
        rows.append({
            "id": item["id"],
            "source": item["source"],
            "prediction": {"path": str(path), "sha256": digest(path)},
            "selected_input": item["prediction"],
            "bpm_segments": segments,
        })
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot / Path(__file__).name)
    frozen = {
        "schema_version": 1,
        "complete": True,
        "references_available_to_runner": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_manifest_sha256": digest(args.candidate_manifest),
        "runner_sha256": digest(__file__),
        "step_bpm": args.step_bpm,
        "rounding_policy": (
            "Round every declared segment quarter BPM to nearest step, "
            "retain first phase and internal change pulses, integrate "
            "boundary times, recompute terminal pulse at unchanged source end."),
        "rows": rows,
    }
    save(output / "prediction-manifest.json", frozen)
    print(args.step_bpm, len(rows), "source-only rounded predictions")


if __name__ == "__main__":
    main()
