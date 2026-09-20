import tempfile
from decimal import Decimal
from pathlib import Path
import unittest

from inspect_inputs import compare_reference_text, read_tempo_reference


class ReferenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tempo.smt"

    def write_events(self, events):
        nodes = [f'<obj class="MTempoEvent"><float name="PPQ" value="{tick}"/><float name="BPM" value="{bpm}"/></obj>' for tick, bpm in events]
        self.path.write_text("<MasterTrack>" + "".join(nodes) + "</MasterTrack>")

    def test_step_integration_uses_preceding_tempo_and_explicit_resolution(self):
        self.write_events([(0, 120), (960, 60), (1920, 180)])
        result = read_tempo_reference(self.path, 960)
        self.assertEqual([e["time_seconds"] for e in result["events"]], [Decimal(0), Decimal("0.5"), Decimal("1.5")])
        self.assertEqual(result["audio_origin_alignment"], "unverified")

    def test_nonzero_origin_and_duplicate_or_unsorted_positions_are_rejected(self):
        for events in [[(480, 120)], [(0, 120), (0, 90)], [(0, 120), (960, 90), (480, 100)]]:
            with self.subTest(events=events):
                self.write_events(events)
                with self.assertRaises(ValueError):
                    read_tempo_reference(self.path, 480)

    def test_invalid_tempo_or_resolution_is_rejected(self):
        for bpm in [0, -1, "NaN", "Infinity"]:
            self.write_events([(0, bpm)])
            with self.subTest(bpm=bpm), self.assertRaises(ValueError):
                read_tempo_reference(self.path, 480)
        self.write_events([(0, 120)])
        for tpq in [0, -1, "NaN", "Infinity"]:
            with self.subTest(tpq=tpq), self.assertRaises(ValueError):
                read_tempo_reference(self.path, tpq)

    def test_rounded_reference_can_match_without_becoming_verified_audio_alignment(self):
        self.write_events([(0, 180), (480, 120)])
        result = read_tempo_reference(self.path, 480)
        text = Path(self.directory.name) / "reference.txt"
        text.write_text("TPQ used : 480.000\n0 0.000 0.000 180.000\n1 480.000 0.333 120.000\n")
        self.assertTrue(compare_reference_text(text, result)["within_display_rounding"])
        self.assertEqual(result["audio_origin_alignment"], "unverified")
        text.write_text(text.read_text().replace("0.333", "0.334"))
        self.assertFalse(compare_reference_text(text, result)["within_display_rounding"])

    def test_reference_resolution_mismatch_is_rejected(self):
        self.write_events([(0, 120)])
        result = read_tempo_reference(self.path, 960)
        text = Path(self.directory.name) / "reference.txt"
        text.write_text("TPQ used : 480.000\n0 0.000 0.000 120.000\n")
        with self.assertRaises(ValueError):
            compare_reference_text(text, result)


if __name__ == "__main__":
    unittest.main()
