"""Independent fixtures for reference units, hidden support and source separation."""

from __future__ import annotations

import argparse
from pathlib import Path
import unittest

from experiments.metronome_benchmark_v1.inference import validate_source
from .common import nearest_rate, oracle_clock, reference_segments, stored_reference, write_json


class PreparationControls(unittest.TestCase):
    def test_master_coordinate_takes_precedence_without_second_shift(self):
        ref = {"tempo_events": [{"time_seconds": 20, "master_seconds": -4, "bpm_quarter": 120},
                                 {"time_seconds": 30, "master_seconds": 6, "bpm_quarter": 150}]}
        segments = reference_segments(ref, [[0, 10]])
        self.assertEqual([(s["start_seconds"], s["end_seconds"], s["quarter_bpm"]) for s in segments],
                         [(0, 6, 120), (6, 10, 150)])

    def test_repeated_declarations_are_not_changes(self):
        ref = {"tempo_events": [{"time_seconds": t, "bpm_quarter": 120} for t in (-2, 0, 4, 8)]}
        self.assertEqual(len(reference_segments(ref, [[0, 10]])), 1)

    def test_support_gaps_are_not_spliced(self):
        ref = {"tempo_events": [{"time_seconds": 0, "bpm_quarter": 120}, {"time_seconds": 5, "bpm_quarter": 140}]}
        segments = reference_segments(ref, [[0, 4], [6, 9]])
        self.assertEqual([(s["start_seconds"], s["end_seconds"]) for s in segments], [(0, 4), (6, 9)])

    def test_explicit_quarters_precede_half_note_clicks(self):
        ref = {"quarter_beats_seconds": [.2, .5, .8, 1.1], "beats_seconds": [.2, .8], "downbeats_seconds": [.2]}
        stored = stored_reference(ref, [[0, 2]])
        self.assertEqual(stored["quarter_times_seconds"], [.2, .5, .8, 1.1])

    def test_existing_arrays_are_not_rebuilt_or_shifted(self):
        ref = {"beats_seconds": [.203, .704, 1.202, 1.707], "downbeats_seconds": [.203]}
        stored = stored_reference(ref, [[0, 2]])
        self.assertEqual(stored["quarter_times_seconds"], ref["beats_seconds"])
        self.assertEqual(stored["additional_offset_applied_seconds"], 0)

    def test_half_open_support_preserves_boundary_ownership(self):
        ref = {"beats_seconds": [0, .5, 1, 1.5, 2], "downbeats_seconds": [0, 2]}
        self.assertEqual(stored_reference(ref, [[0, 2]])["quarter_times_seconds"], [0, .5, 1, 1.5])

    def test_oracle_contract_hides_true_support(self):
        known = oracle_clock({"quarter_bpm": 120, "start_seconds": 3, "end_seconds": 8},
                             [3.2, 3.7, 4.2, 4.7], [3.2])
        self.assertEqual(set(known), {"quarter_bpm", "period_seconds", "phase_seconds", "meter", "bar_phase_seconds"})
        self.assertAlmostEqual(known["phase_seconds"], .2)

    def test_same_rate_separated_phases_stay_distinct(self):
        first = oracle_clock({"quarter_bpm": 120, "start_seconds": 0, "end_seconds": 2}, [.2, .7], [.2])
        later = oracle_clock({"quarter_bpm": 120, "start_seconds": 4, "end_seconds": 6}, [4.37, 4.87], [4.37])
        self.assertNotAlmostEqual(first["phase_seconds"], later["phase_seconds"])

    def test_vocabulary_probe_remains_unrepresentable(self):
        self.assertEqual(float(nearest_rate(120.1)), 120)
        self.assertEqual(float(nearest_rate(120.25)), 120.25)

    def test_source_worker_rejects_reference_field(self):
        row = {"id": "fixture", "audio_path": "fixture.wav", "sample_rate": 32000, "sample_frames": 32000,
               "channels": 1, "duration_seconds": 1}
        validate_source([row])
        with self.assertRaises(ValueError):
            validate_source([{**row, "reference_boundary_seconds": .5}])

    def test_source_worker_rejects_duplicate_identity(self):
        row = {"id": "fixture", "audio_path": "fixture.wav", "sample_rate": 32000, "sample_frames": 32000,
               "channels": 1, "duration_seconds": 1}
        with self.assertRaises(ValueError):
            validate_source([row, row])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PreparationControls))
    write_json(args.output, {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "passed": result.wasSuccessful(), "scope": "Step 0 preparation contracts, not musical accuracy"})
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
