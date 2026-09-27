"""Reconstruct candidate maps from frozen alternate Beat This observations.

Source-only runner: no reference catalog, owner map, or score is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

from .constant_grid import infer_constant_map
from .tempo_segments import infer_tempo_segments
from .run_constant_grid11 import digest, read_bound, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    input_path = args.observations.resolve()
    observations = json.loads(input_path.read_text())
    if not observations.get("complete") or observations.get("references_available_to_runner") is not False:
        raise ValueError("complete source-only observations required")
    output = args.output.resolve()
    output.mkdir(parents=True)
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    for name in ("run_alternate_seed_maps.py", "constant_grid.py", "tempo_segments.py"):
        shutil.copy2(Path(__file__).with_name(name), snapshot / name)
    ledger = {"schema_version": 1, "complete": False,
              "references_available_to_runner": False,
              "observation_manifest": {"path": str(input_path), "sha256": digest(input_path)},
              "implementation_sha256": {name: digest(snapshot / name)
                                        for name in ("run_alternate_seed_maps.py",
                                                     "constant_grid.py", "tempo_segments.py")},
              "rows": [], "started_at_utc": datetime.now(timezone.utc).isoformat()}
    for row in observations["rows"]:
        if digest(row["audio"]["path"]) != row["audio"]["sha256"]:
            raise ValueError("source audio binding changed")
        for candidate in row["observations"]:
            logit_path = read_bound(candidate["logits"])
            event_path = read_bound(candidate["events"])
            with np.load(logit_path) as values:
                beat, downbeat, fps = values["beat"], values["downbeat"], float(values["fps"])
            events = json.loads(event_path.read_text())
            constant = infer_constant_map(beat, downbeat, fps,
                                          events["downbeats_seconds"], row["source"])
            segmented = infer_tempo_segments(constant, beat, downbeat, fps,
                                              events["beats_seconds"])
            folder = output / row["id"] / candidate["checkpoint"]
            constant_binding = save(folder / "constant.json", constant)
            segmented_binding = save(folder / "segmented.json", segmented)
            ledger["rows"].append({"id": row["id"],
                                   "checkpoint": candidate["checkpoint"],
                                   "source": row["source"],
                                   "logits": candidate["logits"],
                                   "events": candidate["events"],
                                   "constant": constant_binding,
                                   "segmented": segmented_binding})
            print(row["id"], candidate["checkpoint"],
                  "BPM", round(constant["diagnostics"]["period"]["quarter_bpm"], 4),
                  "meter", constant["map"]["meter_events"][0]["numerator"],
                  "segments",segmented["diagnostics"]["tempo_segments"]["accepted"],
                  flush=True)
            save(output / "prediction-manifest.json", ledger)
    ledger["complete"] = len(ledger["rows"]) == sum(len(row["observations"])
                                             for row in observations["rows"])
    ledger["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "prediction-manifest.json", ledger)


if __name__ == "__main__":
    main()
