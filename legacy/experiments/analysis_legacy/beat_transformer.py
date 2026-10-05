"""Pinned Beat Transformer loading and bounded, context-preserving inference.

The upstream implementation is kept in ignored model storage, not copied into
product code. In particular its checkpoint-compatible attention-head bug is
intentionally preserved. Frame times follow the official demo: i * 1024/44100.
"""

import hashlib
import importlib
from pathlib import Path
import sys

import numpy as np
import torch


UPSTREAM_COMMIT = "063667fc9e4e11507f9d76dc1154d9db953a85eb"
FPS = 44100 / 1024
# Nine layers have maximum left/right reach 4 * sum(2**i), plus
# the two temporal frontend convolutions (radii 2 and 1).
MIN_CONTEXT_FRAMES = 4 * (2**9 - 1) + 3


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_model(upstream_dir, checkpoint, device):
    upstream_dir = Path(upstream_dir)
    sys.path.insert(0, str((upstream_dir / "code").resolve()))
    try:
        module = importlib.import_module("DilatedTransformer")
    finally:
        sys.path.pop(0)
    if Path(module.__file__).resolve() != (upstream_dir / "code/DilatedTransformer.py").resolve():
        raise ValueError("a different Beat Transformer module is already loaded")
    model = module.Demixed_DilatedTransformerModel(
        attn_len=5, instr=5, ntoken=2, dmodel=256, nhead=8,
        d_hid=1024, nlayers=9, norm_first=True,
    )
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state["state_dict"], strict=True)
    return model.to(device).eval()


def chunk_spans(frame_count, core_frames, context_frames):
    if frame_count <= 0 or core_frames <= 0:
        raise ValueError("frame_count and core_frames must be positive")
    if context_frames < MIN_CONTEXT_FRAMES:
        raise ValueError(f"context must cover at least {MIN_CONTEXT_FRAMES} frames")
    for start in range(0, frame_count, core_frames):
        end = min(frame_count, start + core_frames)
        yield start, end, max(0, start-context_frames), min(frame_count, end+context_frames)


def infer_frames(model, features, device, core_frames=2048, context_frames=2048):
    features = np.asarray(features, dtype=np.float32)
    if features.ndim != 3 or features.shape[0] != 5 or features.shape[2] != 128:
        raise ValueError("expected five real separated stem features [5, time, 128]")
    if not np.isfinite(features).all():
        raise ValueError("features contain non-finite values")
    spans = list(chunk_spans(features.shape[1], core_frames, context_frames))
    result = np.empty((features.shape[1], 2), dtype=np.float32)
    with torch.inference_mode():
        for start, end, left, right in spans:
            value = torch.from_numpy(features[:, left:right].copy()).unsqueeze(0).to(device)
            # forward() returns frame logits without allocating visualization's T*T matrices.
            prediction, _ = model(value)
            retained = prediction[0, start-left:end-left].detach().cpu().numpy()
            if retained.shape != (end-start, 2) or not np.isfinite(retained).all():
                raise ValueError("invalid model output")
            result[start:end] = retained
            del value, prediction
    return result, spans


def validate_logits(beat, downbeat, fps=FPS):
    beat, downbeat = np.asarray(beat), np.asarray(downbeat)
    if beat.ndim != 1 or beat.shape != downbeat.shape or not beat.size:
        raise ValueError("beat/downbeat logits must have matching nonempty one-dimensional shapes")
    if not np.isfinite(beat).all() or not np.isfinite(downbeat).all():
        raise ValueError("logits must be finite")
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be positive")
    return np.arange(len(beat), dtype=np.float64) / fps
