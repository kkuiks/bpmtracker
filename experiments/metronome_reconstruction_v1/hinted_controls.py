"""Contract controls for the explicitly requested tap-only implementation."""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from .controls import synthetic
from .hinted import encode_tap_level, prepare_audio_family, select_from_family, validate_hint_row
from .infer import make_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    checks = []
    def record(name, passed, **details):
        row = {"name": name, "passed": bool(passed), **details}
        checks.append(row)
        print(json.dumps(row), flush=True)
    family = prepare_audio_family(synthetic(80, 4, .237, 90, config), config)
    predictions = [select_from_family(family, hint) for hint in (155, 160, 165)]
    record("155_160_165_are_identical_after_unit_selection", predictions[0] == predictions[1] == predictions[2], selected_bpm=predictions[0]["quarter_bpm"])
    record("raw_hint_number_not_retained_by_model", all("initial_quarter_bpm_tap" not in p and p["raw_tap_number_used_after_unit_selection"] is False for p in predictions))
    fractional = prepare_audio_family(synthetic(79.75, 4, .237, 90, config), config)
    fractional_predictions = [select_from_family(fractional, hint) for hint in (155, 160, 165)]
    record("audio_precision_not_copied_from_160_hint", fractional_predictions[0]["quarter_bpm"] == 159.5 and fractional_predictions[0] == fractional_predictions[1] == fractional_predictions[2], selected_bpm=fractional_predictions[0]["quarter_bpm"])
    faster = select_from_family(family, 320)
    record("different_unit_changes_scale_not_numeric_target", faster["quarter_bpm"] == 320 and faster["selected_audio_layer_power"] == 2)
    empty = make_evidence(np.full(100, -8), np.full(100, -8), 2, config)
    no_data = select_from_family(prepare_audio_family(empty, config), 160)
    record("tap_cannot_create_a_clock_without_evidence", no_data["quarter_bpm"] is None and no_data["status"] == "insufficient_acoustic_evidence")
    unsupported = select_from_family(family, 1000)
    record("tap_cannot_create_an_unavailable_layer", unsupported["quarter_bpm"] is None)
    record("octave_boundary_is_not_forced", encode_tap_level(80, math.sqrt(80 * 160))["power"] is None)
    for value in (0, -1, float("inf"), float("nan")):
        try:
            encode_tap_level(80, value)
            accepted = True
        except ValueError:
            accepted = False
        record("invalid_tap_rejected_" + str(value), not accepted)
    try:
        validate_hint_row({"id": "fixture", "initial_quarter_bpm_tap": 160, "initial_time_signature": {"numerator": 4, "denominator": 4}})
        accepted = True
    except ValueError:
        accepted = False
    record("time_signature_input_rejected", not accepted)
    three = prepare_audio_family(synthetic(120, 3, .731, 90, config), config)
    inferred = select_from_family(three, 120)
    record("meter_inferred_from_audio_without_meter_input", inferred["time_signature"] == {"numerator": 3,"denominator": 4} and inferred["time_signature_supplied"] is False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"purpose": "Hint contract controls, not real-music accuracy", "passed": all(row["passed"] for row in checks), "checks": checks}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
