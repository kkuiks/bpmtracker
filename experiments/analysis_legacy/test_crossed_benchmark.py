import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from run_crossed_benchmark import load_logits, reconstruct_model, source_compatibility


def pulse_logits(fps, duration=25.):
    logits = np.full(round(fps * duration), -8., dtype=np.float32)
    for t in np.arange(1., duration - 1, .5):
        logits[round(t * fps)] = 8.
    return logits, np.full_like(logits, -8.)


class CrossedTests(unittest.TestCase):
    def test_source_hash_and_complete_duration_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.wav'
            sf.write(path, np.zeros((8000, 2)), 8000)
            digest = sha256(path)
            catalog = {'input': {'kind': 'audio', 'path': str(path), 'sha256': digest}, 'duration_seconds': 1.}
            baseline = {'input_sha256': digest, 'duration_seconds': 1.}
            alternate = {'audio': {'sha256': digest, 'sample_rate': 8000, 'channels': 2,
                                   'source_frames': 8000, 'analyzed_frames': 8000,
                                   'duration_seconds': 1., 'source_frame_offset': 0},
                         'model': {'frame_time_offset_seconds': 0}}
            self.assertTrue(source_compatibility(catalog, baseline, alternate)['same_canonical_audio_verified'])
            alternate['audio']['analyzed_frames'] = 4000
            with self.assertRaises(ValueError):
                source_compatibility(catalog, baseline, alternate)
            alternate['audio']['analyzed_frames'] = 8000
            alternate['audio']['sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                source_compatibility(catalog, baseline, alternate)

    def test_logit_origin_and_native_fps_cannot_be_silently_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'logits.npz'
            fps = 44100 / 1024
            np.savez(path, beat=np.zeros(44), downbeat=np.zeros(44), fps=fps,
                     source_frame_offset=0, frame_time_offset_seconds=0.)
            self.assertEqual(load_logits(path, 1., fps)[2], fps)
            with self.assertRaises(ValueError):
                load_logits(path, 1., 50.)
            np.savez(path, beat=np.zeros(44), downbeat=np.zeros(44), fps=fps,
                     source_frame_offset=0, frame_time_offset_seconds=-2048 / 44100)
            with self.assertRaises(ValueError):
                load_logits(path, 1., fps)

    def test_official_decoder_differences_do_not_seed_crossed_candidates(self):
        beat, downbeat = pulse_logits(50.)
        official_a = {'beats_seconds': [1., 2., 3.], 'downbeats_seconds': [1.]}
        official_b = {'beats_seconds': [1.25, 3.25], 'downbeats_seconds': []}
        a = reconstruct_model(beat, downbeat, 50., official_a, 25.)
        b = reconstruct_model(beat, downbeat, 50., official_b, 25.)
        self.assertNotEqual(a['official']['prediction'], b['official']['prediction'])
        self.assertEqual(a['clock_current'], b['clock_current'])
        self.assertEqual(a['candidate_set'], b['candidate_set'])
        self.assertFalse(a['candidate_set']['reference_used_for_prediction'])

    def test_native_frame_times_produce_consistent_source_clock(self):
        results = []
        for fps in (50., 44100 / 1024):
            beat, downbeat = pulse_logits(fps)
            output = reconstruct_model(beat, downbeat, fps,
                                       {'beats_seconds': [], 'downbeats_seconds': []}, 25.)
            clock = output['clock_current']['clock']
            self.assertIsNotNone(clock)
            self.assertAlmostEqual(clock['segments'][0]['pulse_rate_per_minute'], 120, delta=.2)
            times = np.array(output['clock_current']['prediction']['beats_seconds'])
            self.assertTrue(np.all((times >= 0) & (times < 25)))
            self.assertEqual(output['native_frame_rate'], fps)
            results.append(times)
        np.testing.assert_allclose(results[0], results[1], atol=.02)


if __name__ == '__main__':
    unittest.main()
