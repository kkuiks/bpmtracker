"""Freeze independent five-drum-class activations from a source-derived stem.

This observation does not read approved tempo/meter maps or select a bar grid.
The model checkout and dependency target are isolated under ignored data/cache.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024*1024), b""):
            h.update(part)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demix-manifest", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--deps-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--input-role", choices=("drums", "mix"), default="drums")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    demix = json.loads(args.demix_manifest.read_text())
    if demix.get("reference_read") is not False or demix.get("source_only") is not True:
        raise ValueError("source-only separated stem required")
    drum = (next(x for x in demix["stems"] if x["stem"] == "drums")
            if args.input_role == "drums" else demix["source"])
    path = Path(drum["path"])
    if sha256(path) != drum["sha256"]:
        raise ValueError("input audio hash changed")
    info = sf.info(path)
    if (info.samplerate, info.frames) != (demix["source"]["sample_rate"],
                                          demix["source"]["sample_frames"]):
        raise ValueError("derived drum stem does not share source sample clock")
    model_root = args.model_root.resolve()
    weights = model_root/"data/adtof_frame_rnn_pytorch_weights.pth"
    if not weights.is_file():
        raise FileNotFoundError(weights)
    model_commit = subprocess.check_output(
        ["git", "-C", str(model_root), "rev-parse", "HEAD"], text=True).strip()
    sys.path.extend((str(args.deps_root.resolve()), str(model_root/"src")))
    import librosa
    import pretty_midi
    import torch
    from adtof_pytorch import transcribe_to_midi
    from adtof_pytorch.post_processing import (
        FRAME_RNN_THRESHOLDS, LABELS_5, PeakPicker,
        activations_to_pretty_midi)
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    torch.set_num_threads(4)
    activations = transcribe_to_midi(
        path, args.output/"unused.mid", return_activations=True,
        weights=weights, device=args.device)
    if (activations.ndim != 3 or activations.shape[0] != 1 or
            activations.shape[2] != len(LABELS_5) or
            not np.isfinite(activations).all()):
        raise ValueError("invalid full-source drum class activations")
    expected = info.frames/info.samplerate
    if abs(activations.shape[1]/100-expected) > .1:
        raise ValueError("drum observation does not span finished mix")
    output = args.output.resolve()
    output.mkdir(parents=True)
    snapshot = output/"source-snapshot"; snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    np.savez_compressed(output/"activations.npz",
                        activations=activations.astype(np.float32),
                        fps=np.array(100), labels=np.asarray(LABELS_5))
    peaks = PeakPicker(thresholds=FRAME_RNN_THRESHOLDS, fps=100).pick(
        activations, labels=LABELS_5, label_offset=0)[0]
    midi = activations_to_pretty_midi(peaks, velocity=100,
        note_duration=.1, program=1, is_drum=True)
    midi.write(str(output/"transcribed-drums.mid"))
    report = {"schema_version": 1, "source_only": True, "reference_read": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": demix["source"], "input_role": args.input_role,
        "demix_manifest_sha256": sha256(args.demix_manifest),
        "stem": {"path": str(path.resolve()), "sha256": drum["sha256"],
                 "sample_rate": info.samplerate, "sample_frames": info.frames},
        "model": {"name": "ADTOF-pytorch Frame_RNN", "source_commit": model_commit,
                  "weights_sha256": sha256(weights), "device": args.device,
                  "fps": 100, "labels_general_midi": LABELS_5,
                  "thresholds": FRAME_RNN_THRESHOLDS,
                  "librosa_version": librosa.__version__,
                  "pretty_midi_version": pretty_midi.__version__,
                  "torch_version": torch.__version__},
        "output": {"activations_sha256": sha256(output/"activations.npz"),
                   "midi_sha256": sha256(output/"transcribed-drums.mid"),
                   "activation_shape": list(activations.shape),
                   "note_count_by_pitch": {str(k): len(v) for k,v in peaks.items()}},
        "runner_sha256": sha256(__file__)}
    (output/"manifest.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print('source seconds',round(expected,3),'activations',activations.shape,
          'notes',report['output']['note_count_by_pitch'])


if __name__ == "__main__":
    main()
