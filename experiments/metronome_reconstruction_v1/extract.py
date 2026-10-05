"""Fresh official Beat This observations, from the source-only manifest."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import torch
from beat_this.inference import Audio2Frames
from beat_this.model.postprocessor import Postprocessor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    if any("reference" in row or "quarter_bpm" in row or "time_signature" in row
           for row in manifest["samples"]):
        raise ValueError("Inference manifest contains forbidden reference hints")
    torch.set_num_threads(config["torch_threads"])
    torch.set_num_interop_threads(1)
    tracker = Audio2Frames(str(args.checkpoint), device=config["device"], float16=False)
    postprocessor = Postprocessor(type="minimal", fps=config["fps"])
    args.output.mkdir(parents=True, exist_ok=True)
    environment = {
        "beat_this": importlib.metadata.version("beat-this"), "torch": torch.__version__,
        "device": config["device"], "float16": False, "checkpoint": str(args.checkpoint),
        "checkpoint_source": "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt",
        "sensor_fps": config["fps"], "torch_threads": config["torch_threads"],
        "preprocessing": "Official Audio2Frames: channel mean, soxr to 22050 Hz, hop 441; original source untouched",
        "legacy_observations_or_weights_used": False,
    }
    (args.output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    receipt = []
    for index, row in enumerate(manifest["samples"], 1):
        print(f"EXTRACT {index}/{len(manifest['samples'])} {row['id']}", flush=True)
        start = time.perf_counter()
        try:
            signal, sr = sf.read(args.samples_root / row["audio_path"], dtype="float32", always_2d=True)
            # Necessary input geometry guards, not a source-file integrity audit.
            if sr != row["sample_rate"] or len(signal) != row["sample_frames"]:
                raise ValueError("Decoded source geometry differs from the source manifest")
            beat, downbeat = tracker(signal, sr)
            if not torch.isfinite(beat).all() or not torch.isfinite(downbeat).all():
                raise ValueError("Official model returned nonfinite evidence")
            official_beats, official_downbeats = postprocessor(beat, downbeat)
            np.savez_compressed(
                args.output / (row["id"] + ".npz"),
                beat_logits=beat.cpu().numpy(), downbeat_logits=downbeat.cpu().numpy(),
                official_beats=official_beats, official_downbeats=official_downbeats,
                fps=np.asarray(config["fps"]), duration_seconds=np.asarray(len(signal) / sr),
            )
            item = {"id": row["id"], "status": "completed", "seconds": time.perf_counter() - start,
                    "frames": len(beat), "official_beats": len(official_beats),
                    "official_downbeats": len(official_downbeats)}
            del signal, beat, downbeat
        except Exception as exc:
            item = {"id": row["id"], "status": "failed", "seconds": time.perf_counter() - start,
                    "error": repr(exc)}
        receipt.append(item)
        (args.output / "extraction-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(item), flush=True)


if __name__ == "__main__":
    main()
