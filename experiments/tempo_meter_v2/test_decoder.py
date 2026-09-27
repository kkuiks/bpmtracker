"""Constructed contracts for the sparse source-only map proposal."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from decoder import Config, infer_from_evidence, infer_tempo_meter, spectral_flux_from_audio


FPS = 50.0
SR = 48000


def pulses(axis, events, width):
    return np.maximum.reduce([np.exp(-0.5 * ((axis - event) / width) ** 2) for event in events])


def constructed(duration, beats, bars, *, onsets=True):
    frame_times = np.arange(round(duration * FPS)) / FPS
    onset_times = np.arange(round(duration * 100)) / 100
    beat = 8 * pulses(frame_times, beats, .025) - 3
    down = 8 * pulses(frame_times, bars, .03) - 3
    independent = 6 * pulses(onset_times, beats, .02) if onsets else np.zeros(len(onset_times))
    source = {'sha256': '0' * 64, 'sample_rate': SR, 'sample_frames': round(duration * SR)}
    return beat, down, onset_times, independent, source


class SparseDecoderTests(unittest.TestCase):
    def test_joint_path_represents_a_meter_change_at_its_physical_bar_boundary(self):
        # The pulse interval stays the same. Only downbeat spacing changes.
        duration = 24.0
        beats = np.arange(0, duration, .5)
        bars = np.r_[np.arange(0, 12, 1.0), np.arange(12, duration, 2.0)]
        args = constructed(duration, beats, bars)
        result = infer_from_evidence(args[0], args[1], FPS, args[2], args[3], args[4],
                                     config=Config(max_cpu_seconds=30))
        self.assertEqual(result['status'], 'proposed_map')
        self.assertEqual([(e['numerator'], e['denominator']) for e in result['map']['meter_events']],
                         [(2, 4), (4, 4)])
        self.assertAlmostEqual(result['bar_starts_seconds'][12], 12.0)
        self.assertEqual(result['map']['shared_origin_id'], None)
        self.assertFalse(result['diagnostics']['full_source_contract_validated'])

    def test_joint_path_represents_quarter_bpm_change_without_meter_change(self):
        duration = 28.8
        beats = np.r_[np.arange(0, 16, .5), np.arange(16, duration, .4)]
        bars = np.r_[np.arange(0, 16, 2.0), np.arange(16, duration, 1.6)]
        args = constructed(duration, beats, bars)
        result = infer_from_evidence(args[0], args[1], FPS, args[2], args[3], args[4],
                                     config=Config(max_cpu_seconds=30))
        self.assertEqual(result['status'], 'proposed_map')
        self.assertEqual(len(result['map']['meter_events']), 1)
        knots = result['map']['clock_knots']
        self.assertIn({'pulse': 32.0, 'source_seconds': 16.0}, knots)
        before = next(i for i, knot in enumerate(knots) if knot['source_seconds'] == 16.0)
        self.assertAlmostEqual(60 * 4 / (knots[before]['source_seconds']-knots[before-1]['source_seconds']), 120)
        self.assertAlmostEqual(60 * 4 / (knots[before+1]['source_seconds']-knots[before]['source_seconds']), 150)

    def test_no_periodic_source_evidence_declares_abstention(self):
        times = np.arange(0, 8, .01)
        result = infer_from_evidence(np.zeros(400), np.zeros(400), FPS, times,
                                     np.zeros(len(times)),
                                     {'sha256': '0' * 64, 'sample_rate': SR, 'sample_frames': 8 * SR})
        self.assertEqual(result['status'], 'unresolved')
        self.assertIsNone(result['map'])
        self.assertEqual(result['diagnostics']['reason'], 'no_local_periodicity')

    def test_audio_feature_clock_and_bound_source_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.wav'
            audio = np.zeros((2 * SR, 2), dtype=np.float32)
            audio[SR:SR+100] = .7
            sf.write(path, audio, SR, subtype='PCM_16')
            times, strength, geometry = spectral_flux_from_audio(path, Config())
            self.assertEqual(geometry['sample_frames'], 2 * SR)
            self.assertGreater(np.max(strength[np.abs(times - 1.0) < .025]), 0)
            self.assertEqual(np.max(strength[np.abs(times - .5) < .025]), 0)
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                infer_tempo_meter(path, np.zeros(100), np.zeros(100), FPS,
                                  source_sha256='0' * 64)


if __name__ == '__main__':
    unittest.main()
