"""Run the frozen balanced route control and sparse joint map on eight sources.

Prediction has a source-only manifest.  No approved tempo/meter map or reference
score is parsed here; scoring is a separate command after this run completes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time

import numpy as np
import soundfile as sf

from .baseline_adapter import complete_balanced_map
from .decoder import infer_tempo_meter


ROOT = Path(__file__).resolve().parents[2]
INPUT_MANIFEST = ROOT / "data/runs/primary8-path-comparison/2026-09-27-v1/joint-inputs/manifest.json"
PRIOR_RUN = ROOT / "data/runs/primary8-path-comparison/2026-09-27-v1"
RANKING_ROOT = ROOT / "data/runs/logic-maintenance/2026-09-26-v1/ranking-fixed-pool/predictions"
SOURCES = ("run_primary8.py", "decoder.py", "baseline_adapter.py")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def binding(path):
    path = Path(path)
    return {"path": str(path), "sha256": digest(path)}


def read_bound(value):
    path = Path(value["path"])
    if digest(path) != value["sha256"]:
        raise ValueError(f"frozen input hash changed: {path}")
    return json.loads(path.read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return binding(path)


def balanced_path(track_id):
    if track_id == "legacy_circle":
        return PRIOR_RUN / "circle-replay/balanced.json"
    if track_id.startswith("daybreak_"):
        return PRIOR_RUN / "balanced-replay" / (track_id + ".json")
    if track_id.startswith("ntm_"):
        return RANKING_ROOT / track_id / "beat_this.json"
    raise ValueError(f"no frozen balanced route for {track_id}")


def load_case(entry):
    payload = read_bound(entry["input_json"])
    if set(payload) != {"schema_version", "id", "input_audio", "guide", "input_policy"}:
        raise ValueError("prediction payload changed shape")
    if (payload["schema_version"] != 1 or payload["id"] != entry["id"] or
            payload["guide"] is not None or
            payload["input_policy"] != "no user tap BPM available; unhinted automatic comparison"):
        raise ValueError("only unhinted exact-identity eight-song input is allowed")
    if set(payload["input_audio"]) != {"path", "sha256"}:
        raise ValueError("audio payload contains an interpretation field")
    audio_path = Path(payload["input_audio"]["path"])
    if digest(audio_path) != payload["input_audio"]["sha256"]:
        raise ValueError(f"approved source audio changed: {entry['id']}")
    info = sf.info(audio_path)
    source = {"sha256": payload["input_audio"]["sha256"],
              "sample_rate": info.samplerate, "sample_frames": info.frames}
    if digest(entry["logits"]["path"]) != entry["logits"]["sha256"]:
        raise ValueError(f"source-only logit cache changed: {entry['id']}")
    with np.load(entry["logits"]["path"], allow_pickle=False) as cache:
        fps = float(cache["fps"])
        beat = np.asarray(cache["beat"], dtype=np.float64)
        downbeat = np.asarray(cache["downbeat"], dtype=np.float64)
        for key in ("source_frame_offset", "frame_time_offset_seconds"):
            if key in cache and float(cache[key]) != 0:
                raise ValueError("nonzero cache time origin needs a separately verified mapping")
    duration = info.frames / info.samplerate
    if (not math.isfinite(fps) or fps <= 0 or beat.ndim != 1 or
            downbeat.shape != beat.shape or not np.isfinite(beat).all() or
            not np.isfinite(downbeat).all() or len(beat)/fps < duration - 1/fps):
        raise ValueError("invalid full-source native-frame evidence")
    core = read_bound(entry["baseline"]["predictions"])
    read_bound(entry["baseline"]["candidates"])
    if any(core["source"][key] != source[key] for key in source):
        raise ValueError("frozen core and current approved source differ")
    if core["source"]["logits_sha256"] != entry["logits"]["sha256"]:
        raise ValueError("frozen core and raw evidence differ")
    old_path = balanced_path(entry["id"])
    frozen = binding(old_path)
    balanced = read_bound(frozen)
    if balanced.get("id") != entry["id"]:
        raise ValueError("frozen selection case identity differs")
    if "method" in balanced and balanced["method"].get("selected_candidate_id"):
        chosen = [candidate for candidate in balanced["candidate_set"]["candidates"]
                  if candidate["id"] == balanced["method"]["selected_candidate_id"]]
        if (len(chosen) != 1 or chosen[0]["clock"] != balanced["method"]["clock"] or
                [event["source_seconds"] for event in chosen[0]["indexed_grid"]] !=
                balanced["method"]["prediction"]["beats_seconds"]):
            raise ValueError("frozen replay selected clock differs from its saved candidate")
    return {"audio_path": audio_path, "source": source, "fps": fps,
            "beat": beat, "downbeat": downbeat,
            "balanced": balanced, "frozen": frozen}


def run(output, only_ids=None):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("run directory must be new")
    document = json.loads(INPUT_MANIFEST.read_text())
    entries = document["cases"]
    if len(entries) != 8 or len({entry["id"] for entry in entries}) != 8:
        raise ValueError("source-only manifest must contain exactly eight unique songs")
    selected = entries if only_ids is None else [entry for entry in entries if entry["id"] in only_ids]
    if only_ids is not None and {entry["id"] for entry in selected} != set(only_ids):
        raise ValueError("unknown requested case")
    original_sources = {name: binding(Path(__file__).with_name(name)) for name in SOURCES}
    ledger = {"schema_version": 1, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "complete": False, "scope": "unhinted eight primary development songs",
              "references_opened_during_prediction": False,
              "source_only_manifest": binding(INPUT_MANIFEST),
              "implementation": original_sources, "runtime": {
                  "python": platform.python_version(), "numpy": np.__version__,
                  "soundfile": sf.__version__, "platform": platform.platform()},
              "rows": []}
    output.mkdir(parents=True)
    save(output / "prediction-manifest.json", ledger)
    for entry in selected:
        track_id = entry["id"]
        case = load_case(entry)
        started = time.perf_counter()
        records = {}
        arms = (("baseline_completed", lambda: complete_balanced_map(
                    case["balanced"], case["beat"], case["downbeat"], case["fps"], case["source"])),
                ("joint_sparse", lambda: infer_tempo_meter(
                    case["audio_path"], case["beat"], case["downbeat"], case["fps"],
                    source_sha256=case["source"]["sha256"])))
        for name, callback in arms:
            arm_started = time.perf_counter()
            try:
                result = callback()
                if not isinstance(result, dict) or result.get("map") is not None and result["map"]["source"]["sha256"] != case["source"]["sha256"]:
                    raise ValueError("inference returned invalid source identity")
            except (ValueError, RuntimeError, KeyError, IndexError, TypeError, MemoryError) as exc:
                result = {"schema_version": 1, "status": "execution_error", "map": None,
                          "bar_starts_seconds": [], "beat_times_seconds": [],
                          "diagnostics": {"error": f"{type(exc).__name__}: {exc}"},
                          "resources": {}, "evidence_provenance": {"source_sha256": case["source"]["sha256"]}}
            result["runner_elapsed_seconds"] = time.perf_counter() - arm_started
            result["runner_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            records[name] = save(output / "predictions" / track_id / (name + ".json"), result)
            print(track_id, name, result["status"], f"{result['runner_elapsed_seconds']:.1f}s", flush=True)
        ledger["rows"].append({"id": track_id, "source": case["source"],
                               "input_payload": entry["input_json"], "logits": entry["logits"],
                               "frozen_balanced": case["frozen"], **records,
                               "total_elapsed_seconds": time.perf_counter() - started})
        save(output / "prediction-manifest.json", ledger)
    checked = [*original_sources.values(), ledger["source_only_manifest"]]
    for row in ledger["rows"]:
        checked.extend((row["input_payload"], row["logits"], row["frozen_balanced"]))
    for value in checked:
        if digest(value["path"]) != value["sha256"]:
            raise ValueError("implementation or source-only input changed during prediction")
    ledger["complete"] = len(ledger["rows"]) == 8 and only_ids is None
    ledger["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "prediction-manifest.json", ledger)
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ids", nargs="+", help="source-only smoke run; never scored as an eight-song comparison")
    args = parser.parse_args()
    run(args.output, args.ids)


if __name__ == "__main__":
    main()
