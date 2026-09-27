"""Freeze additional Beat This observations on SHA-bound finished mixes.

This runner reads only the prior source-only prediction manifest, its bound WAVs,
and explicit model checkpoints. It does not read accepted musical maps.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import soundfile as sf
import torch

from beat_this.inference import Audio2Frames
from beat_this.model.postprocessor import Postprocessor


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--track-id", action="append", required=True)
    parser.add_argument("--checkpoint", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    if len(set(args.track_id)) != len(args.track_id):
        raise ValueError("track IDs must be unique")
    checkpoints = {p.stem: p.resolve() for p in args.checkpoint}
    if len(checkpoints) != len(args.checkpoint):
        raise ValueError("checkpoint stems must be unique")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    base_path = args.base_manifest.resolve()
    base = json.loads(base_path.read_text())
    if not base.get("complete") or base.get("references_available_to_runner") is not False:
        raise ValueError("complete source-only base manifest required")
    rows = {row["id"]: row for row in base["rows"]}
    if any(track not in rows for track in args.track_id):
        raise ValueError("unknown source-only track ID")
    for path in checkpoints.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    device = torch.device(args.device)
    args.output.mkdir(parents=True)
    snapshot = args.output / "source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot / Path(__file__).name)
    manifest = {
        "schema_version": 1, "complete": False,
        "references_available_to_runner": False,
        "base_manifest_path": str(base_path),
        "base_manifest_sha256": digest(base_path),
        "runner_sha256": digest(__file__),
        "device": args.device,
        "device_name": torch.cuda.get_device_name(0) if args.device == "cuda" else "cpu",
        "model_checkpoints": {key: {"path": str(path), "sha256": digest(path)}
                              for key, path in checkpoints.items()},
        "rows": [], "started_at_utc": datetime.now(timezone.utc).isoformat()}
    for track_id in args.track_id:
        row = rows[track_id]
        audio_path = Path(row["audio"]["path"])
        if digest(audio_path) != row["audio"]["sha256"]:
            raise ValueError(f"source WAV changed: {track_id}")
        info = sf.info(audio_path)
        if (not info.format.startswith("WAV") or
                info.samplerate != row["source"]["sample_rate"] or
                info.frames != row["source"]["sample_frames"]):
            raise ValueError(f"source geometry changed: {track_id}")
        audio, rate = sf.read(audio_path, dtype="float32", always_2d=True)
        if not np.isfinite(audio).all():
            raise ValueError("nonfinite source audio")
        observations = []
        for key, checkpoint in checkpoints.items():
            start = time.perf_counter()
            model = Audio2Frames(checkpoint_path=str(checkpoint),
                                 device=args.device, float16=False)
            beat, downbeat = model(audio, rate)
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            inference_seconds = time.perf_counter() - start
            beats, bars = Postprocessor(type="minimal", fps=50)(beat, downbeat)
            folder = args.output / track_id / key
            folder.mkdir(parents=True)
            logit_path = folder / "logits.npz"
            np.savez_compressed(logit_path, beat=beat.detach().cpu().numpy(),
                                downbeat=downbeat.detach().cpu().numpy(),
                                fps=np.array(50))
            events = {"beats_seconds": np.asarray(beats, dtype=float).tolist(),
                      "downbeats_seconds": np.asarray(bars, dtype=float).tolist()}
            event_path = folder / "events.json"
            event_path.write_text(json.dumps(events, allow_nan=False) + "\n")
            observations.append({"checkpoint": key,
                "checkpoint_sha256": manifest["model_checkpoints"][key]["sha256"],
                "logits": {"path": str(logit_path.resolve()),
                           "sha256": digest(logit_path)},
                "events": {"path": str(event_path.resolve()),
                           "sha256": digest(event_path)},
                "inference_seconds": inference_seconds,
                "frame_count": int(beat.numel()),
                "beat_count": len(beats), "bar_count": len(bars)})
            print(track_id, key, "frames",beat.numel(),
                  "beats",len(beats),"bars",len(bars),flush=True)
            del model, beat, downbeat
            if device.type == "cuda":
                torch.cuda.empty_cache()
        manifest["rows"].append({"id": track_id, "audio": row["audio"],
                                 "source": row["source"],
                                 "observations": observations})
        (args.output / "prediction-manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    manifest["complete"] = len(manifest["rows"]) == len(args.track_id)
    manifest["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    (args.output / "prediction-manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
