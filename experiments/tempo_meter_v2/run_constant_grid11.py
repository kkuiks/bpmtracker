"""Run the source-only constant-grid control on all eleven frozen inputs.

This runner never opens an owner reference, a score, or a user tempo hint.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .constant_grid import infer_constant_map

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "data/runs/primary8-path-comparison/2026-09-27-v1/joint-inputs/manifest.json"
NEW = ROOT / "data/runs/tempo-meter-v2/primary11-initial-20260927-v1/source-only-added3.json"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_bound(binding):
    path = Path(binding["path"])
    if digest(path) != binding["sha256"]:
        raise ValueError(f"source-only input hash changed: {path}")
    return path


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {"path": str(path), "sha256": digest(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("prediction output must be new")
    old = json.loads(OLD.read_text())["cases"]
    new = json.loads(NEW.read_text())["cases"]
    if len(old) != 8 or len(new) != 3:
        raise ValueError("source-only eleven-song input set is incomplete")
    ledger = {"schema_version": 1, "complete": False,
              "input_manifest_sha256": {"old_eight": digest(OLD), "new_three": digest(NEW)},
              "implementation_sha256": {"constant_grid.py": digest(Path(__file__).with_name("constant_grid.py")),
                                        "run_constant_grid11.py": digest(Path(__file__))},
              "references_available_to_runner": False,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "rows": []}
    for row in old + new:
        is_old = "input_json" in row
        payload = json.loads(read_bound(row["input_json"]).read_text()) if is_old else None
        audio_binding = payload["input_audio"] if is_old else row["audio"]
        audio_path = read_bound(audio_binding)
        audio = sf.info(audio_path)
        source = {"sha256": audio_binding["sha256"], "sample_rate": audio.samplerate,
                  "sample_frames": audio.frames}
        logits_path = read_bound(row["logits"])
        with np.load(logits_path) as arrays:
            beat = arrays["beat"]
            down = arrays["downbeat"]
            fps = float(arrays["fps"])
        official_binding = row["baseline"]["predictions"] if is_old else row["official_result"]
        official = json.loads(read_bound(official_binding).read_text())
        observations = (official["methods"]["official"]["prediction"] if is_old else official)
        if is_old:
            if official["source"]["sha256"] != source["sha256"]:
                raise ValueError(f"official source mismatch: {row['id']}")
        elif official["audio"]["sha256"] != source["sha256"]:
            raise ValueError(f"official source mismatch: {row['id']}")
        predicted = infer_constant_map(beat, down, fps,
                                      observations["downbeats_seconds"], source)
        prediction = save(output / "predictions" / (row["id"] + ".json"), predicted)
        ledger["rows"].append({"id": row["id"], "source": source,
                               "audio": audio_binding, "logits": row["logits"],
                               "official": official_binding, "prediction": prediction})
        print(row["id"], predicted["diagnostics"]["period"]["quarter_bpm"],
              predicted["map"]["meter_events"][0]["numerator"], flush=True)
        save(output / "prediction-manifest.json", ledger)
    ledger["complete"] = len(ledger["rows"]) == 11 and len({r["id"] for r in ledger["rows"]}) == 11
    ledger["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "prediction-manifest.json", ledger)


if __name__ == "__main__":
    main()
