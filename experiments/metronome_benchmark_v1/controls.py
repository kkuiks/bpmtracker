"""Focused parser, qualification, and scoring controls with independent fixtures."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile

import numpy as np
import soundfile as sf

from .inference import validate_source, write_json
from .metrics import aggregate, clock_error, event_f1, score
from .references import periodic_events, qualify_track, source_clock


def vlq(value):
    result = [value & 127]
    while value > 127:
        value >>= 7
        result.insert(0, 128 | (value & 127))
    return bytes(result)


def fixture_midi(path, *, tempos=((0, 500_000),), signatures=((0, 4, 4),), division=480, kind=1):
    metadata = [(tick, b"\xff\x51\x03" + value.to_bytes(3, "big")) for tick, value in tempos]
    metadata += [(tick, bytes([0xff, 0x58, 4, numerator, int(math.log2(denominator)), 24, 8]))
                 for tick, numerator, denominator in signatures]
    notes = []
    for index in range(16):
        notes.extend([(index * division, bytes([0x90, 60 + index % 5, 90])),
                      (index * division + division // 2, bytes([0x80, 60 + index % 5, 0]))])
    chunks = []
    for events in [metadata, notes]:
        data, previous = bytearray(), 0
        for tick, event in sorted(events, key=lambda value: value[0]):
            data.extend(vlq(tick - previous) + event)
            previous = tick
        data.extend(b"\x00\xff\x2f\x00")
        chunks.append(b"MTrk" + struct.pack(">I", len(data)) + data)
    path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, kind, 2, division & 0xffff) + b"".join(chunks))


def expect_error(function):
    try:
        function()
    except ValueError:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((Path(__file__).with_name("protocol.json")).read_text())
    cases = []

    def check(name, passed):
        cases.append({"name": name, "passed": bool(passed)})

    with tempfile.TemporaryDirectory(prefix="joljak-benchmark-controls-") as temporary:
        root = Path(temporary)
        path = root / "fixture.mid"
        fixture_midi(path, tempos=((0, 500_000), (480, 500_000)), signatures=((0, 4, 4), (480, 4, 4)))
        clock = source_clock(path)
        check("repeated_declarations_are_not_changes", len(clock["tempos"]) == len(clock["signatures"]) == 1
              and clock["tempo_declarations"] == clock["signature_declarations"] == 2)
        fixture_midi(path, tempos=((0, 500_000), (480, 1_000_000)))
        clock = source_clock(path)
        check("piecewise_tick_to_seconds", clock["tempos"][1]["source_seconds"] == .5
              and clock["last_channel_event_seconds"] == 15.0)
        fixture_midi(path, signatures=((0, 3, 4),))
        check("explicit_three_four", source_clock(path)["signatures"][0]["numerator"] == 3)
        fixture_midi(path, signatures=())
        check("implicit_meter_is_marked", not source_clock(path)["explicit_initial_meter"])
        fixture_midi(path, tempos=())
        check("implicit_tempo_is_marked", not source_clock(path)["explicit_initial_tempo"])
        fixture_midi(path, tempos=((0, 500_000), (0, 600_000)))
        check("conflicting_clock_declarations_rejected", expect_error(lambda: source_clock(path)))
        fixture_midi(path, kind=2)
        check("independent_midi_tracks_rejected", expect_error(lambda: source_clock(path)))
        fixture_midi(path, division=0xE828)
        check("smpte_clock_rejected", expect_error(lambda: source_clock(path)))

        directory = root / "Track00001"
        (directory / "MIDI").mkdir(parents=True)
        (directory / "stems").mkdir()
        sf.write(directory / "mix.wav", np.zeros(40 * 8000), 8000)
        shutil.copyfile(directory / "mix.wav", directory / "stems/S00.wav")
        (directory / "metadata.yaml").write_text("UUID: fixture\nstems:\n  S00:\n    audio_rendered: false\n    midi_saved: false\n")

        def qualify(tempos=((0, 500_000),), signatures=((0, 4, 4),), stem_tempos=None):
            fixture_midi(directory / "all_src.mid", tempos=tempos, signatures=signatures)
            fixture_midi(directory / "MIDI/S00.mid", tempos=stem_tempos if stem_tempos is not None else tempos,
                         signatures=signatures)
            return qualify_track(directory, protocol)

        row, reference = qualify()
        check("fixed_encoded_clock_qualified", row["eligible"] and reference["quarter_bpm"] == 120)
        check("paired_files_override_bookkeeping_flags", row["eligible"] and row["metadata_bookkeeping_disagreements"] == ["S00"])
        check("unknown_audio_origin_not_promoted", reference["audio_offset_seconds"] is None
              and not reference["absolute_audio_origin_verified"])
        row, reference = qualify(signatures=())
        check("missing_meter_remains_unscored", row["eligible"] and reference["time_signature"] is None
              and "encoded_meter" not in row["capabilities"])
        row, reference = qualify(tempos=())
        check("missing_initial_tempo_excluded", not row["eligible"] and reference is None)
        row, reference = qualify(tempos=((0, 500_000), (480, 600_000)))
        check("variable_tempo_excluded_before_prediction", not row["eligible"] and "variable_encoded_tempo" in row["reasons"])
        row, reference = qualify(signatures=((0, 4, 4), (480, 3, 4)))
        check("variable_meter_excluded_before_prediction", not row["eligible"] and "variable_encoded_meter" in row["reasons"])
        row, reference = qualify(signatures=((0, 6, 8),))
        check("unsupported_meter_not_relabelled", not row["eligible"] and "unsupported_encoded_meter" in row["reasons"])
        row, reference = qualify(stem_tempos=((0, 600_000),))
        check("rendered_stem_disagreement_excluded", not row["eligible"] and "rendered_source_clock_disagreement" in row["reasons"])
        sf.write(directory / "stems/S00.wav", np.full(40 * 8000, .2), 8000)
        row, reference = qualify()
        check("unmatched_source_audio_excluded", not row["eligible"] and "mixture_does_not_match_paired_stems" in row["reasons"])

    check("reference_events_use_half_open_support", periodic_events(.5, 0, 0, 2) == [0, .5, 1, 1.5])
    check("source_reference_crop_keeps_phase", periodic_events(.5, 0, .2, 2) == [.5, 1, 1.5])
    event = event_f1([.99, 1, 1.01], [1], .02)
    check("event_matching_capacity_one", event["tp"] == 1 and event["fp"] == 2 and event["f1"] == .5)
    errors = clock_error([0, .5, 1, 1.5, 2, 2.5], .501, .123)
    check("drift_preserves_clock_index", abs(errors["initial_signed_ms"] - 123) < 1e-9
          and abs(errors["accumulated_drift_ms"] - 5) < 1e-9)
    errors = clock_error([0, 2, 4], 2, .5)
    check("bar_group_error_not_wrapped_into_quarter", errors["maximum_absolute_ms"] == 500)

    reference = {"quarter_bpm": 120., "quarter_bpm_fraction": {"numerator": 120, "denominator": 1},
        "period_seconds": .5, "time_signature": {"numerator": 4, "denominator": 4},
        "source_support_seconds": [0, 4], "quarter_source_seconds": [0, .5, 1, 1.5, 2, 2.5, 3, 3.5],
        "downbeat_source_seconds": [0, 2]}
    prediction = {"status": "fixed_map_proposal", "quarter_bpm": 120., "period_seconds": .5,
        "time_signature": {"numerator": 4, "denominator": 4}, "offset_seconds": 0.,
        "quarter_clicks_seconds": reference["quarter_source_seconds"], "downbeats_seconds": [0, 2], "confidence_flags": []}
    value = score(prediction, reference, 30, protocol)
    check("perfect_projection_does_not_certify_phase", not value["absolute_phase"]["scored"]
          and value["declared_origin_diagnostic"]["quarter_f1"]["20"]["f1"] == 1)
    wrong = {**prediction, "quarter_bpm": 121., "period_seconds": 60 / 121}
    value = score(wrong, reference, 30, protocol)
    check("rate_implied_drift_has_known_sign_and_size", abs(value["bpm_implied_drift_ms_over_input"] - 30 * (120 / 121 - 1) * 1000) < 1e-9)
    missing = {"status": "insufficient_acoustic_evidence", "quarter_bpm": None}
    entries = [{"id": str(index), "eligible": True, "status": "qualified_partial", "parent_group": str(index),
                "capabilities": ["encoded_quarter_bpm", "encoded_meter"],
                "conditions": {"audio_only": {"metrics": score(item, reference, 30, protocol)}}}
               for index, item in enumerate([prediction, missing])]
    summary = aggregate(entries, ["audio_only"], protocol)["conditions"]["audio_only"]
    check("abstention_kept_in_denominator", summary["qualified_denominator"] == 2 and summary["failed_or_abstained"] == 1
          and summary["encoded_meter_denominator"] == 2)
    source = {"id": "fixture", "audio_path": "input.wav", "sample_rate": 8000,
              "sample_frames": 8000, "channels": 1, "duration_seconds": 1.}
    check("reference_fields_rejected_by_inference", expect_error(lambda: validate_source([{**source, "quarter_bpm": 120}])))
    check("duplicate_source_ids_rejected", expect_error(lambda: validate_source([source, source])))
    report = {"purpose": "Focused benchmark parser and metric controls; not audio accuracy",
              "cases": cases, "passed": all(case["passed"] for case in cases)}
    write_json(args.output, report)
    print(json.dumps(report, indent=2), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
