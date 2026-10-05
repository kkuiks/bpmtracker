"""Constructed checks for constant musical grids and false-change scoring."""
import unittest
from copy import deepcopy

import numpy as np

from constant_grid import infer_constant_map
from experiments.tempo_meter_v2.score_primary11 import change_gate
from experiments.tempo_meter_v2.score_primary8 import _tempo_changes, score_arm, quarter_beats
from experiments.analysis_legacy.music_map_contract import prepare_map
from grid_metrics import meter_change_metrics, nearest_event_diagnostics, tempo_change_metrics


class ConstantGridTests(unittest.TestCase):
    def test_recovers_quarter_rate_and_bar_phase_from_periodic_observations(self):
        fps = 50.0
        duration = 64.0
        times = np.arange(int(duration * fps)) / fps
        beats = .18 + np.arange(128) * .5
        bars = beats[::4]
        def logits(events):
            impulse = np.exp(-.5 * ((times[:, None] - events[None, :]) / .025) ** 2)
            return -6 + 12 * impulse.max(axis=1)
        result = infer_constant_map(
            logits(beats), logits(bars), fps, bars,
            {"sha256": "0" * 64, "sample_rate": 48000,
             "sample_frames": int(duration * 48000)})
        self.assertEqual(result["status"], "proposed_map")
        self.assertAlmostEqual(result["diagnostics"]["period"]["quarter_bpm"], 120, places=1)
        self.assertEqual(result["map"]["meter_events"][0]["numerator"], 4)
        self.assertGreater(nearest_event_diagnostics(bars, result["bar_starts_seconds"], .07)["f1"], .99)

    def test_step_tempo_sequence_requires_three_coherent_bar_changes(self):
        from experiments.tempo_meter_v2.tempo_segments import infer_tempo_segments
        fps, duration = 50., 200.
        phase, p0, p1 = .09, 60/205, 60/210
        change_quarters = (344, 472, 552)
        n = np.arange(800)
        times = (phase + np.minimum(n, 344)*p0 +
                 np.clip(n-344, 0, 128)*p1 +
                 np.clip(n-472, 0, 80)*p0 +
                 np.clip(n-552, 0, None)*p1)
        inside = times < duration
        n, times = n[inside], times[inside]
        frames = int(duration*fps)
        beat = np.full(frames, -6.)
        down = np.full(frames, -6.)
        for events, target in ((times, beat), (times[n % 8 == 0], down)):
            for event in events:
                center = round(event*fps)
                for frame in range(max(0, center-3), min(frames, center+4)):
                    target[frame] = max(target[frame],
                        -6 + 12*np.exp(-.5*((frame/fps-event)/.025)**2))
        source = {"sha256": "0"*64, "sample_rate": 48000,
                  "sample_frames": duration*48000}
        base = infer_constant_map(beat, down, fps, times[n % 8 == 0], source)
        result = infer_tempo_segments(base, beat, down, fps, times[n % 2 == 0])
        self.assertTrue(result["diagnostics"]["tempo_segments"]["accepted"])
        self.assertEqual(result["diagnostics"]["tempo_segments"]["selected_change_quarters"],
                         list(change_quarters))
        self.assertEqual(len(result["map"]["clock_knots"]), 5)

    def test_eleven_song_score_arm_counts_tiny_steps_even_with_perfect_beat_f1(self):
        source = {"sha256": "0"*64, "sample_rate": 48000,
                  "sample_frames": 64*48000}
        reference = prepare_map({
            "schema_version": 1, "source": source,
            "clock_knots": [{"pulse": 0., "source_seconds": 0.},
                            {"pulse": 128., "source_seconds": 64.}],
            "support_seconds": [[0., 64.]],
            "quarters_per_pulse": {"numerator": 1, "denominator": 1},
            "bar_anchor_pulse": 0.,
            "meter_events": [{"pulse": 0., "numerator": 4,
                              "denominator": 4, "grouping": [1,1,1,1],
                              "bar_action": "continue"}],
            "analysis_condition": "reference", "shared_origin_id": None})
        prediction = deepcopy(reference)
        prediction["analysis_condition"] = "unhinted"
        at_44 = 20. + 4*60/120.05
        prediction["clock_knots"] = [
            {"pulse": 0., "source_seconds": 0.},
            {"pulse": 40., "source_seconds": 20.},
            {"pulse": 44., "source_seconds": at_44},
            {"pulse": 44. + (64.-at_44)*2, "source_seconds": 64.}]
        score = score_arm(reference, {"status": "proposed_map", "map": prediction},
                          quarter_beats(reference), minimum_tempo_change_bpm=1e-6)
        self.assertEqual(score["map_render_status"], "rendered")
        self.assertEqual(score["quarter_grid_event_70ms"]["f1"], 1.0)
        counts = score["tempo_change_500ms"]["full_change_scores"]
        self.assertEqual(counts["false_positives"], 2)
        self.assertEqual(change_gate(counts), 0.0)

    def test_tiny_extra_tempo_steps_count_as_false_positives(self):
        # Matching tolerates 0.1 BPM only after events have been counted.
        # Alternating tiny steps must not disappear from the eleven-song gate.
        clock = {"clock_knots": [
            {"pulse": 0., "source_seconds": 0.},
            {"pulse": 4., "source_seconds": 2.},
            {"pulse": 8., "source_seconds": 2. + 4.*60./120.05},
            {"pulse": 12., "source_seconds": 2. + 4.*60./120.05 + 2.}]}
        changes = _tempo_changes(clock, [[0., 6.]], minimum_change_bpm=1e-6)
        self.assertEqual(len(changes), 2)
        counts = tempo_change_metrics([], changes,
                                       time_tolerance_seconds=.5)["full_change_scores"]
        self.assertEqual(counts["false_positives"], 2)
        self.assertEqual(change_gate(counts), 0.0)

    def test_many_nearby_guesses_cannot_match_one_change(self):
        ref = [{"source_seconds": 10., "bpm_before": 120.,
                "bpm_after": 130., "type": "step"}]
        pred = [{**ref[0], "source_seconds": t} for t in (9.7, 10., 10.3)]
        counts = tempo_change_metrics(ref, pred,
                                       time_tolerance_seconds=.5)["full_change_scores"]
        self.assertEqual((counts["true_positives"], counts["false_positives"],
                          counts["false_negatives"]), (1, 2, 0))
        self.assertLess(change_gate(counts), .9)

    def test_extra_changes_and_extra_bars_lower_scores(self):
        empty_tempo = tempo_change_metrics([], [{"source_seconds": 10.0,
            "bpm_before": 120.0, "bpm_after": 121.0, "type": "step"}],
            time_tolerance_seconds=.5)["full_change_scores"]
        self.assertEqual(change_gate(empty_tempo), 0.0)
        self.assertEqual(change_gate(meter_change_metrics([], [], time_tolerance_seconds=.5)), 1.0)
        meter = meter_change_metrics([{"source_seconds": 10.0, "numerator": 3,
                                      "denominator": 4}],
                                     [{"source_seconds": 10.0, "numerator": 3, "denominator": 4},
                                      {"source_seconds": 20.0, "numerator": 4, "denominator": 4}],
                                     time_tolerance_seconds=.5)
        self.assertLess(change_gate(meter), .9)
        self.assertLess(nearest_event_diagnostics([1., 2., 3.], [1., 2., 3., 3.5], .07)["f1"], .9)


if __name__ == "__main__":
    unittest.main()
