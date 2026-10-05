"""Focused native-clock click-export controls for owner listening."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from experiments.tempo_meter_v2.build_primary11_listening import render_click


class Primary11ListeningTests(unittest.TestCase):
    def test_click_keeps_native_frames_and_accents_only_declared_bars(self):
        rate = 48000
        frames = 3 * rate
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"predicted-click.wav"
            report = render_click(path, sample_rate=rate, sample_frames=frames,
                                  quarters=[0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
                                  bars=[0.0, 2.0])
            info = sf.info(path)
            self.assertEqual((info.samplerate, info.frames, info.channels, info.subtype),
                             (rate, frames, 1, "PCM_16"))
            audio, _ = sf.read(path, dtype="float32")
            self.assertEqual((report["quarter_click_count"], report["accented_bar_count"]), (6, 2))
            self.assertGreater(audio[0], audio[rate//2])
            self.assertGreater(audio[2*rate], audio[rate//2])
            for frame in (rate//2, rate, 3*rate//2, 2*rate, 5*rate//2):
                self.assertGreater(audio[frame], 0.)
                self.assertEqual(audio[frame-1], 0.)
            self.assertTrue(np.all(audio[rate//4:rate//2] == 0.))
            self.assertEqual(audio[-1], 0.)

    def test_a_bar_accent_cannot_be_added_at_an_unpredicted_quarter(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "bars on quarters"):
                render_click(Path(directory)/"bad.wav", sample_rate=48000,
                             sample_frames=48000, quarters=[0., .5], bars=[.25])


if __name__ == "__main__":
    unittest.main()
