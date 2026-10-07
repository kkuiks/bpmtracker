"""Focused known-arithmetic controls for feature admission and coarse scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np

from .gtzan import aggregate_annotations, qualify_dataset, reference_from_annotations, score_annotation, select_pilot
from .inference import validate_source, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name("protocol-gtzan-v1.json").read_text())
    cases = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        cases.append({"name": name, "passed": True})

    times = np.array([.13 + i / 2 for i in range(60)])
    positions = np.array([i % 4 + 1 for i in range(60)])
    reference, reasons = reference_from_annotations(times, positions, 30.02, protocol)
    check("known_half_second_pulse_and_origin", not reasons and abs(reference["pulse_bpm"] - 120) < 1e-10
          and abs(reference["fitted_first_annotation_seconds"] - .13) < 1e-10)
    check("original_timestamps_retained", reference["beat_times_seconds"] == times.tolist()
          and reference["source_annotation_unchanged"])
    check("coarse_fit_does_not_certify_producer_precision", reference["precise_producer_clock_verified"] is False
          and reference["notation_denominator_verified"] is False)
    three, reasons = reference_from_annotations(times, [i % 3 + 1 for i in range(60)], 30.02, protocol)
    check("three_pulse_bars_without_notation_claim", not reasons and three["bar_pulse_count"] == 3
          and len(three["downbeat_times_seconds"]) == 20 and three["notation_denominator_verified"] is False)
    partial, reasons = reference_from_annotations(times, None, 30.02, protocol)
    check("missing_bar_annotation_has_no_default_four", not reasons and partial["bar_pulse_count"] is None
          and partial["downbeat_times_seconds"] is None)
    _, reasons = reference_from_annotations(times + .12 * np.sin(np.arange(60)), positions, 30.02, protocol)
    check("nonconstant_annotation_excluded_without_outlier_removal",
          "annotations_do_not_support_approximately_constant_pulse" in reasons)
    changed = [1, 2, 3, 1, 2, 3, 4] * 8 + [1, 2, 3, 4]
    _, reasons = reference_from_annotations(times, changed, 30.02, protocol)
    check("changing_bar_cycle_excluded", "inconsistent_or_changing_annotated_bar_positions" in reasons)
    _, reasons = reference_from_annotations(times, [i % 6 + 1 for i in range(60)], 30.02, protocol)
    check("six_pulse_bars_not_relabelled", "unsupported_annotated_bar_pulse_count" in reasons)
    try:
        reference_from_annotations([0, .5, .5, 1], [1, 2, 3, 4], 30, protocol)
    except ValueError:
        check("duplicate_annotation_timestamps_rejected", True)
    else:
        check("duplicate_annotation_timestamps_rejected", False)
    prediction = {"status": "fixed_map_proposal", "quarter_bpm": 120, "period_seconds": .5,
                  "offset_seconds": .13, "time_signature": {"numerator": 4, "denominator": 4},
                  "quarter_clicks_seconds": times.tolist(), "downbeats_seconds": times[::4].tolist()}
    perfect = score_annotation(prediction, reference, protocol)
    check("known_coarse_event_matches", perfect["beat_f1"]["70"]["f1"] == 1
          and perfect["downbeat_f1"]["70"]["f1"] == 1 and perfect["producer_precision_scored"] is False)
    failure = score_annotation({"status": "inference_failed"}, reference, protocol)
    rows = [{"id": ident, "eligible": True, "selected_for_inference": True, "status": "qualified_coarse",
             "role": "development", "genre": "fixture", "parent_group": ident,
             "conditions": {"audio_only": {"metrics": metrics}}}
            for ident, metrics in [("correct", perfect), ("failed", failure)]]
    summary = aggregate_annotations(rows, {"correct": reference, "failed": reference},
                                    {**protocol, "conditions": ["audio_only"]}, "development")
    result = summary["conditions"]["audio_only"]
    check("failure_preserves_bpm_and_event_denominators", result["selected_denominator"] == 2
          and result["pulse_bpm_denominator"] == 2 and result["failed_or_abstained"] == 1
          and result["beat_macro_f1"]["70"] == .5)
    source = {"id": "fixture", "spectrogram_path": "bundle.npz", "spectrogram_key": "fixture/track",
              "spectrogram_frames": 1501, "mel_bands": 128, "fps": 50, "duration_seconds": 30.02}
    validate_source([source])
    try:
        validate_source([{**source, "beat_times_seconds": [0, .5]}])
    except ValueError:
        check("annotation_fields_rejected_by_feature_worker", True)
    else:
        check("annotation_fields_rejected_by_feature_worker", False)
    with tempfile.TemporaryDirectory(prefix="joljak-gtzan-controls-") as temporary:
        root = Path(temporary)
        annotations = root / "gtzan/annotations/beats"
        annotations.mkdir(parents=True)
        (root / "gtzan/info.json").write_text('{"has_downbeats": true}\n')
        feature = np.zeros((1501, 128), dtype=np.float16)
        np.savez(root / "gtzan.npz", **{f"gtzan_{genre}_00000/track": feature for genre in ("blues", "rock", "pop")})
        for genre in ("blues", "rock"):
            np.savetxt(annotations / f"gtzan_{genre}_00000.beats", np.column_stack((times, positions)), fmt=["%.6f", "%d"])
        qualified, fixture_references = qualify_dataset(root, protocol)
        paired = [row for row in qualified if row["eligible"]]
        check("duplicate_features_share_role_across_genres", len(paired) == 2
              and len({row["parent_group"] for row in paired}) == 1
              and len({row["role"] for row in paired}) == 1)
        selected = select_pilot(qualified, fixture_references, protocol, paired[0]["role"], 100)
        check("pilot_counts_duplicate_group_once", len(selected) == 1)
        reserved = [{**row, "role": "reserved"} for row in paired]
        check("reserved_groups_do_not_enter_development_pilot",
              not select_pilot(reserved, fixture_references, protocol, "development", 100))
        unannotated = next(row for row in qualified if row["id"] == "gtzan_pop_00000")
        check("unannotated_feature_stays_in_catalog", len(qualified) == 3
              and unannotated["status"] == "excluded_scope"
              and unannotated["reasons"] == ["no_published_annotation"])
    write_json(args.output, {"purpose": "GTZAN reference, grouping and scoring controls; not music accuracy",
                             "cases": cases, "passed": True})
    print(f"PASS {len(cases)} focused GTZAN controls", flush=True)


if __name__ == "__main__":
    main()
