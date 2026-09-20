"""Timing, seam, and invalid-input checks for independent model inference."""

import unittest
import numpy as np
import torch

from beat_transformer import FPS, MIN_CONTEXT_FRAMES, chunk_spans, infer_frames, validate_logits


class ContextModel(torch.nn.Module):
    def forward(self, x):
        y = x[:, 0, :, :2].transpose(1, 2)
        # Nonlocal dependence in both directions makes insufficient overlap
        # and off-by-one stitches visible without requiring model downloads.
        y = torch.nn.functional.pad(y, (1000, 1000))
        n = x.shape[2]
        y = y[:, :, :n] + 2*y[:, :, 1000:1000+n] + y[:, :, 2000:2000+n]
        return y.transpose(1, 2), None


class BeatTransformerTests(unittest.TestCase):
    def test_native_frame_times_preserve_zero(self):
        t = validate_logits(np.zeros(5), np.zeros(5))
        np.testing.assert_array_equal(t, np.arange(5)*1024/44100)
        self.assertNotEqual(FPS, 50)

    def test_chunk_coverage_and_context(self):
        spans = list(chunk_spans(9000, 2048, 2048))
        self.assertEqual(spans[0], (0, 2048, 0, 4096))
        self.assertEqual(spans[-1][1], 9000)
        self.assertEqual(sum(end-start for start, end, _, _ in spans), 9000)
        for a, b in zip(spans, spans[1:]):
            self.assertEqual(a[1], b[0])
        with self.assertRaises(ValueError):
            list(chunk_spans(9000, 2048, MIN_CONTEXT_FRAMES-1))

    def test_context_and_seam_match_full_inference(self):
        x = np.random.default_rng(382).normal(size=(5, 6201, 128)).astype(np.float32)
        model = ContextModel().eval()
        full, _ = infer_frames(model, x, "cpu", core_frames=6201)
        chunks, _ = infer_frames(model, x, "cpu", core_frames=1536)
        np.testing.assert_array_equal(full, chunks)

    def test_invalid_features_and_logits_rejected(self):
        with self.assertRaises(ValueError):
            infer_frames(ContextModel(), np.zeros((1, 100, 128)), "cpu")
        for beat, downbeat in [([], []), ([1, 2], [1]), ([float("nan")], [0])]:
            with self.assertRaises(ValueError):
                validate_logits(beat, downbeat)


if __name__ == "__main__":
    unittest.main()
