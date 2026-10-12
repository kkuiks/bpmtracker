"""Independent known-clock fixtures and an actual source-worker isolation check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from .acoustic import silent_intervals, zero_frames
from .boundary import localize
from .common import ROOT, read_json, write_json
from .support import MATCH, MISMATCH, UNKNOWN, classify, features, observable_channel

PARAMETERS = None
MODEL = None


def evidence(times, duration, silent=None):
    return {"duration": duration, "fps": 50, "channels": {"beat": {
        "events": np.asarray(times, dtype=float), "weights": np.full(len(times), .99)}},
        **({"silent_intervals_seconds": np.asarray(silent, dtype=float)} if silent is not None else {})}


def clock(bpm, phase):
    return {"quarter_bpm": bpm, "period_seconds": 60 / bpm, "phase_seconds": phase % (60 / bpm)}


class AlgorithmControls(unittest.TestCase):
    def test_dense_correct_clock_matches(self):
        e = evidence(.137 + np.arange(40) * .5, 20)
        c = clock(120, .137)
        f = features(e, c, 8, .1, MODEL)
        states, change = classify(f, c, PARAMETERS["8"])
        self.assertEqual(states[100], MATCH)
        self.assertFalse(change[100])

    def test_sustained_opposite_phase_contradicts(self):
        e = evidence(.137 + np.arange(40) * .5, 20)
        c = clock(120, .387)
        f = features(e, c, 8, .1, MODEL)
        states, _ = classify(f, c, PARAMETERS["8"])
        self.assertEqual(states[100], MISMATCH)

    def test_missing_evidence_is_unknown(self):
        e = evidence([], 20)
        c = clock(120, .137)
        states, changes = classify(features(e, c, 8, .1, MODEL), c, PARAMETERS["8"])
        self.assertTrue(np.all(states == UNKNOWN))
        self.assertFalse(changes.any())

    def test_one_bad_beat_does_not_create_contradiction(self):
        times = .137 + np.arange(40) * .5
        times[20] += .13
        e, c = evidence(times, 20), clock(120, .137)
        states, _ = classify(features(e, c, 8, .1, MODEL), c, PARAMETERS["8"])
        self.assertFalse(np.any(states == MISMATCH))

    def test_context_completed_peaks_in_long_zero_audio_are_unknown(self):
        e = evidence(.137 + np.arange(40) * .5, 20, [[5, 9]])
        original = e["channels"]["beat"]["events"].copy()
        c = clock(120, .137)
        states, changes = classify(features(e, c, 16, .1, MODEL), c, PARAMETERS["16"])
        self.assertEqual(states[70], UNKNOWN)
        self.assertFalse(changes[70])
        self.assertTrue(np.array_equal(original, e["channels"]["beat"]["events"]))

    def test_ordinary_interbeat_silence_retains_evidence(self):
        times = .137 + np.arange(40) * .5
        gaps = [[t + .025, t + .475] for t in times[:-1]]
        e = evidence(times, 20, gaps)
        events, _ = observable_channel(e, .5)
        self.assertEqual(len(events), len(times))
        c = clock(120, .137)
        states, _ = classify(features(e, c, 8, .1, MODEL), c, PARAMETERS["8"])
        self.assertEqual(states[100], MATCH)

    def test_zero_pcm_requires_every_channel_to_be_zero(self):
        signal = np.zeros((6400, 2), dtype=np.float32)
        signal[1281, 1] = .01
        zero = zero_frames(signal, 32000, 50, 10)
        self.assertFalse(zero[2])
        self.assertTrue(zero[1])
        spans = silent_intervals(zero, 50, .2)
        self.assertEqual(spans.tolist(), [[0, .04], [.06, .2]])

    def test_quantization_drift_does_not_propose_new_nominal_rates(self):
        times = np.round((.137 + np.arange(512) * (600 / 1201)) * 50) / 50
        e, c = evidence(times, 256), clock(120, .137)
        for span in (4, 8, 16):
            states, changes = classify(features(e, c, span, .1, MODEL), c, PARAMETERS[str(span)])
            self.assertTrue(np.any(states == MISMATCH))
            self.assertFalse(changes.any())

    def test_two_clock_switch_retains_original_time_and_ambiguity(self):
        boundary = 20.137
        left = .137 + np.arange(40) * .5
        right = boundary + np.arange(40) * (60 / 140)
        e = evidence(np.r_[left, right], 38)
        result = localize(e, clock(120, .137), clock(140, boundary), .025)
        self.assertEqual(result["status"], "supported_two_clock_switch")
        self.assertTrue(any(a <= boundary <= b for a, b in result["optimal_intervals_seconds"]))
        self.assertAlmostEqual(result["oracle_phase_continuity"]["time_seconds"], boundary)
        self.assertFalse(result["window_boundary_used"])

    def test_identical_clocks_do_not_manufacture_boundary(self):
        e = evidence(.137 + np.arange(40) * .5, 20)
        result = localize(e, clock(120, .137), clock(120, .137), .025)
        self.assertIsNone(result["audio_time_seconds"])

    def test_harmonic_grid_nesting_is_not_forced_to_a_boundary(self):
        boundary = .137 + 40 * .375
        e = evidence(np.r_[.137 + np.arange(40) * .375, boundary + np.arange(40) * .75], 46)
        result = localize(e, clock(160, .137), clock(80, boundary), .025)
        self.assertIsNone(result["audio_time_seconds"])

    def test_actual_local_source_worker_cannot_open_reference_record(self):
        with tempfile.TemporaryDirectory(prefix="step0-source-control-") as directory:
            root = Path(directory)
            (root / "local-proposal-v2").mkdir()
            (root / "original/evidence").mkdir(parents=True)
            (root / "candidate-recovery").mkdir()
            (root / "candidate-recovery/results.json").write_text("invalid reference sentinel: must not be opened")
            write_json(root / "local-proposal-v2/protocol.json", {"window_seconds_sweep": [4], "stride_fraction": .5})
            write_json(root / "model-config.json", MODEL)
            write_json(root / "source-inputs.json", {"samples": [{"id": "fixture", "audio_path": "not-opened.wav",
                       "sample_rate": 32000, "sample_frames": 128000, "channels": 1, "duration_seconds": 4}]})
            logits = np.full(200, -9.0)
            logits[np.arange(7, 200, 25)] = 9
            np.savez_compressed(root / "original/evidence/fixture.npz", beat_logits=logits, downbeat_logits=logits,
                                fps=50, duration_seconds=4)
            result = subprocess.run([sys.executable, "-m", "experiments.variable_tempo_step0.proposal", "--run", str(root),
                                     "--stage", "prepare"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = read_json(root / "local-proposal-v2/source-receipt.json")
            self.assertTrue(receipt["completed"])
            self.assertFalse(receipt["reference_files_read"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    global PARAMETERS, MODEL
    PARAMETERS = read_json(args.run / "support-v3/parameters.json")["parameters"]
    MODEL = read_json(args.run / "model-config.json")
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AlgorithmControls))
    write_json(args.run / "algorithm-controls.json", {"tests_run": result.testsRun, "errors": len(result.errors),
               "failures": len(result.failures), "passed": result.wasSuccessful(),
               "not_real_music_accuracy": True})
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
