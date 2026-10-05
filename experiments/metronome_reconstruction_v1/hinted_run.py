"""Prepare audio families first, then apply tap-only diagnostic inputs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .grid import timestamps
from .hinted import prepare_audio_family, select_from_family, validate_hint_row
from .infer import make_evidence


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--hints", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.manifest.read_text())["samples"]
    allowed_source_fields = {"id", "audio_path", "sample_rate", "sample_frames", "duration_seconds"}
    if any(set(row) - allowed_source_fields for row in source):
        raise ValueError("Source manifest contains fields beyond source audio identity/geometry")
    config = json.loads(args.config.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(Path(__file__).parent, args.output / "source-snapshot", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(args.config, args.output / "config.json")
    shutil.copyfile(args.manifest, args.output / "inference-manifest.json")
    (args.output / "source-families").mkdir()
    receipt = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
               "valid_denominator": len(source), "reference_files_read_for_inference": False,
               "time_signature_hints_accepted": False,
               "all_audio_families_prepared_before_hint_file_read": True, "families": []}
    families = {}
    for index, row in enumerate(source, 1):
        print(f"AUDIO FAMILY {index}/{len(source)} {row['id']}", flush=True)
        started = time.perf_counter()
        try:
            with np.load(args.evidence / (row["id"] + ".npz")) as data:
                if int(data["fps"]) != config["fps"]:
                    raise ValueError("Sensor frame rate differs from configuration")
                evidence = make_evidence(data["beat_logits"], data["downbeat_logits"], float(data["duration_seconds"]), config)
            family = prepare_audio_family(evidence, config)
            families[row["id"]] = family
            write_json(args.output / "source-families" / (row["id"] + ".json"), family)
            item = {"id": row["id"], "status": family["status"],
                    "seconds": time.perf_counter() - started,
                    "audio_base_bpm": family.get("audio_base_bpm"),
                    "layer_count": len(family["levels"])}
        except Exception as exc:
            item = {"id": row["id"], "status": "failed", "error": repr(exc),
                    "seconds": time.perf_counter() - started}
        receipt["families"].append(item)
        write_json(args.output / "inference-receipt.json", receipt)
        print(json.dumps(item), flush=True)
    receipt["audio_families_completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    # First read of hints occurs here, after every audio family is prepared.
    hint_file = json.loads(args.hints.read_text())
    hints = {}
    for hint in hint_file["samples"]:
        validate_hint_row(hint)
        if hint["id"] in hints:
            raise ValueError("Duplicate hint sample ID")
        hints[hint["id"]] = hint
    source_ids = {row["id"] for row in source}
    if set(hints) != source_ids:
        raise ValueError("Hint and source sample identities differ")
    shutil.copyfile(args.hints, args.output / "diagnostic-hint-inputs.json")
    variants = {"audio_family_control": None, "tap_only": 0, "tap_minus5": -5, "tap_plus5": 5}
    receipt["variants"] = {variant: [] for variant in variants}
    receipt["hint_origin"] = hint_file["origin"]
    inputs_used = {}
    predictions = {variant: {} for variant in variants}
    for variant, delta in variants.items():
        folder = args.output / variant
        (folder / "predictions").mkdir(parents=True)
        (folder / "tempo-maps").mkdir()
        inputs_used[variant] = []
        for row in source:
            ident = row["id"]
            raw = None if delta is None else float(hints[ident]["initial_quarter_bpm_tap"]) + delta
            inputs_used[variant].append({"id": ident, "initial_quarter_bpm_tap": raw,
                                        "scope": "initial_section", "origin": hint_file["origin"]})
            try:
                prediction = select_from_family(families[ident], raw)
                prediction["id"] = ident
                predictions[variant][ident] = prediction
                write_json(folder / "predictions" / (ident + ".json"), prediction)
                if prediction.get("period_seconds"):
                    tempo_map = {key: prediction[key] for key in (
                        "id", "status", "quarter_bpm", "bpm_fraction", "period_seconds", "time_signature",
                        "offset_seconds", "offset_convention", "input_duration_seconds", "confidence_flags",
                        "tap_unit_decision", "initial_tap_provided", "time_signature_supplied")}
                    tempo_map["quarter_clicks_seconds"] = timestamps(prediction["period_seconds"], prediction["offset_seconds"], prediction["input_duration_seconds"]).tolist()
                    tempo_map["downbeats_seconds"] = timestamps(prediction["period_seconds"] * prediction["time_signature"]["numerator"], prediction["offset_seconds"], prediction["input_duration_seconds"]).tolist()
                    write_json(folder / "tempo-maps" / (ident + ".json"), tempo_map)
                item = {"id": ident, "status": prediction["status"], "quarter_bpm": prediction["quarter_bpm"],
                        "meter": prediction["time_signature"], "offset_seconds": prediction["offset_seconds"],
                        "selected_layer_power": prediction.get("selected_audio_layer_power")}
            except Exception as exc:
                item = {"id": ident, "status": "failed", "error": repr(exc)}
            receipt["variants"][variant].append(item)
            print(json.dumps({"variant": variant, **item}), flush=True)
        write_json(args.output / "inference-receipt.json", receipt)
    write_json(args.output / "raw-hint-receipts.json", inputs_used)
    invariance = []
    for row in source:
        ident = row["id"]
        values = [predictions[variant].get(ident) for variant in ("tap_only", "tap_minus5", "tap_plus5")]
        powers = [value.get("tap_unit_decision", {}).get("power") if value else None for value in values]
        usable = all(value and value.get("period_seconds") for value in values)
        same_unit = usable and len(set(powers)) == 1
        invariance.append({"id": ident, "all_variants_returned_maps": bool(usable),
                           "layer_powers": powers, "same_unit": bool(same_unit),
                           "entire_prediction_identical": bool(same_unit and values[0] == values[1] == values[2])})
    write_json(args.output / "hint-invariance.json", {
        "definition": "All model outputs, including scores/meter/offset, must match when the tap selects the same discrete audio layer. Raw tap values are stored only in receipts.",
        "valid_denominator": len(source), "cases": invariance,
        "same_unit_cases": sum(row["same_unit"] for row in invariance),
        "identical_prediction_cases": sum(row["entire_prediction_identical"] for row in invariance),
    })
    receipt["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(args.output / "inference-receipt.json", receipt)


if __name__ == "__main__":
    main()
