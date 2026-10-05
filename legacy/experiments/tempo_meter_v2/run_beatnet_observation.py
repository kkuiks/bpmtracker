"""Run pinned BeatNet CRNN weights on frozen source-only feature arrays.

This imports the upstream model without modifying its implementation. It saves
raw class probabilities; no owner map, BPM hint or reference is opened.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import torch

UPSTREAM_COMMIT = "81cedd4beeb7235262db80969a0c9ce9a48a0ed4"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-metadata", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("observation output must be new")
    if subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip() != UPSTREAM_COMMIT:
        raise ValueError("BeatNet source version changed")
    metadata = json.loads(args.feature_metadata.read_text())
    if metadata["frontend"]["upstream_commit"] != UPSTREAM_COMMIT or metadata["reference_used"] is not False:
        raise ValueError("feature provenance mismatch")
    feature_path = Path(metadata["features"]["path"])
    if digest(feature_path) != metadata["features"]["sha256"]:
        raise ValueError("feature hash changed")
    with np.load(feature_path) as arrays:
        features = arrays["features"].astype("float32", copy=False)
        fps = int(arrays["fps"])
    if features.ndim != 2 or features.shape[1] != 272 or fps != 50:
        raise ValueError("invalid BeatNet feature geometry")
    source = args.upstream / "src/BeatNet/model.py"
    sys.path.insert(0, str((args.upstream / "src").resolve()))
    from BeatNet.model import BDA
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable")
    torch.set_num_threads(1)
    args.output.mkdir(parents=True)
    rows = []
    for model_number in (1, 2, 3):
        weight_path = args.upstream / f"src/BeatNet/models/model_{model_number}_weights.pt"
        model = BDA(272, 150, 2, str(device))
        model.load_state_dict(torch.load(weight_path, map_location=device, weights_only=True), strict=True)
        model.eval()
        with torch.inference_mode():
            raw = model(torch.from_numpy(features).unsqueeze(0).to(device))[0]
            probability = model.final_pred(raw).cpu().numpy()
        if (probability.shape != (3, len(features)) or not np.isfinite(probability).all() or
                not np.allclose(probability.sum(axis=0), 1, atol=1e-5)):
            raise ValueError("invalid BeatNet class probabilities")
        output_path = args.output / f"model{model_number}.npz"
        np.savez_compressed(output_path, beat=probability[0],
                            downbeat=probability[1], other=probability[2],
                            fps=np.array(fps), source_frame_offset=np.array(0))
        rows.append({"model_number": model_number,
                     "weights_sha256": digest(weight_path),
                     "probabilities": {"path": str(output_path.resolve()),
                                       "sha256": digest(output_path)}})
        print(f"model{model_number} {probability.shape}", flush=True)
        del model
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "reference_used": False,
              "audio": metadata["audio"],
              "feature_metadata": {"path": str(args.feature_metadata.resolve()),
                                   "sha256": digest(args.feature_metadata)},
              "upstream_commit": UPSTREAM_COMMIT,
              "model_py_sha256": digest(source),
              "runner_sha256": digest(Path(__file__)),
              "device": args.device, "torch": torch.__version__,
              "python": sys.version.split()[0],
              "models": rows}
    (args.output / "manifest.json").write_text(json.dumps(result, indent=2)+"\n")


if __name__ == "__main__":
    main()
