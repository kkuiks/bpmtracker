"""Extract pinned BeatNet's original madmom features in its Python 3.10 frontend.

Run with data/cache/beat-transformer/frontend-venv/bin/python. Output is an
unreviewed source-only observation, never an accepted clock or reference.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import librosa
import madmom
import numpy as np
import soundfile as sf

UPSTREAM_COMMIT = "81cedd4beeb7235262db80969a0c9ce9a48a0ed4"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("feature output must be new")
    if subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip() != UPSTREAM_COMMIT:
        raise ValueError("BeatNet source version changed")
    source = args.upstream / "src/BeatNet/log_spect.py"
    sys.path.insert(0, str((args.upstream / "src").resolve()))
    from BeatNet.log_spect import LOG_SPECT
    info = sf.info(args.audio)
    if not info.format.startswith("WAV") or info.frames <= 0:
        raise ValueError("canonical source WAV required")
    samples, sample_rate = librosa.load(str(args.audio), sr=22050, mono=True)
    if sample_rate != 22050 or abs(len(samples)/sample_rate - info.frames/info.samplerate) > .001:
        raise ValueError("decoded duration differs from physical source")
    extractor = LOG_SPECT(sample_rate=22050, win_length=1411,
                          hop_size=441, n_bands=[24], mode="offline")
    features = np.ascontiguousarray(extractor.process_audio(samples).T, dtype="<f4")
    if features.ndim != 2 or features.shape[1] != 272 or not np.isfinite(features).all():
        raise ValueError("official BeatNet feature geometry changed")
    args.output.mkdir(parents=True)
    np.savez_compressed(args.output / "features.npz", features=features,
                        fps=np.array(50), source_frame_offset=np.array(0))
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "reference_used": False,
              "audio": {"path": str(args.audio.resolve()), "sha256": digest(args.audio),
                        "sample_rate": info.samplerate, "sample_frames": info.frames},
              "frontend": {"upstream_commit": UPSTREAM_COMMIT,
                           "log_spect_sha256": digest(source),
                           "python": sys.version.split()[0],
                           "librosa": librosa.__version__,
                           "madmom": getattr(madmom, "__version__", "unknown"),
                           "numpy": np.__version__,
                           "decoded_sample_rate": sample_rate,
                           "window_samples": 1411, "hop_samples": 441,
                           "feature_shape": list(features.shape),
                           "fps": 50},
              "features": {"path": str((args.output / "features.npz").resolve()),
                           "sha256": digest(args.output / "features.npz")},
              "runner_sha256": digest(Path(__file__))}
    (args.output / "metadata.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"features": result["frontend"]["feature_shape"],
                      "output": str(args.output / "metadata.json")}), flush=True)


if __name__ == "__main__":
    main()
