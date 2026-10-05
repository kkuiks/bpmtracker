"""Source-only 14-quarter repeated-meter diagnostic on the eleven-song set.

This ranks written bar hypotheses but never creates a full map or reads a
reference. It uses sustained self-similarity to select regions, then scores
two Beat This observations and an independent All-In-One downbeat stream.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

from .constant_grid import _probability
from .run_constant_grid11 import digest, read_bound
from .tempo_segments import _sample


def strong_14_runs(path: Path) -> list[list[int]]:
    with np.load(path) as arrays:
        size = min(len(arrays[f"lag{lag}"]) for lag in (13, 14, 15))
        main = arrays["lag14"][:size]
        contrast = main - np.maximum(arrays["lag13"][:size], arrays["lag15"][:size])
    hits = np.flatnonzero((main > .65) & (contrast > .12))
    runs: list[list[int]] = []
    for index in hits:
        if not runs or index > runs[-1][-1] + 1:
            runs.append([int(index)])
        else:
            runs[-1].append(int(index))
    return [[run[0], run[-1], len(run)] for run in runs if len(run) >= 5]


def regions(runs: list[list[int]], length: int) -> list[list[int]]:
    expanded = [[max(0, start - 14), min(length, stop + 28)]
                for start, stop, _ in runs]
    merged: list[list[int]] = []
    for left, right in expanded:
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(right, merged[-1][1])
        else:
            merged.append([left, right])
    return expanded + [span for span in merged if span not in expanded]


def rank_region(times, views, span):
    begin, end = span
    rows = []
    for exceptional in (2, 6):
        offsets = [0] + [exceptional + 4*i for i in range((14-exceptional)//4)]
        for phase in range(14):
            indices = [q for q in range(begin, end) if (q-phase) % 14 in offsets]
            scores = {name: float(values[indices].mean()) for name, values in views.items()}
            rows.append({"exceptional_bar_quarters": exceptional,
                         "phase_modulo14": phase, "bar_offsets": offsets,
                         "bar_count": len(indices), "observations": scores})
    columns = np.asarray([[r["observations"][name]
                           for name in ("beatthis0", "beatthis1", "allinone")]
                          for r in rows])
    standardized = (columns - columns.mean(axis=0))/(columns.std(axis=0)+1e-12)
    rankings = {name: [int(i) for i in np.argsort(-standardized[:, cols].mean(axis=1))]
                for name, cols in (("beatthis_two", (0, 1)),
                                   ("all_three", (0, 1, 2)))}
    return {"pulse_interval": span, "candidates": rows,
            "standardized_columns": standardized.tolist(), "rankings": rankings,
            "top_five": {name: [{"exceptional_bar_quarters": rows[i]["exceptional_bar_quarters"],
                                  "phase_modulo14": rows[i]["phase_modulo14"]}
                                 for i in order[:5]] for name, order in rankings.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase-root", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--beatthis0", type=Path, required=True)
    parser.add_argument("--beatthis1", type=Path, required=True)
    parser.add_argument("--aio-activations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    all_runs = {}
    for manifest_path in sorted(args.phrase_root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("reference_used") is not False:
            raise ValueError("source-only phrase features required")
        all_runs[manifest_path.parent.name] = strong_14_runs(read_bound(manifest["features"]))
    if len(all_runs) != 11:
        raise ValueError("eleven source-only phrase feature sets required")
    track_id = args.grid.stem
    if track_id not in all_runs or not all_runs[track_id]:
        raise ValueError("grid track has no sustained 14-quarter run")
    grid = json.loads(args.grid.read_text())
    phrase = json.loads((args.phrase_root/track_id/"manifest.json").read_text())
    if grid["map"]["source"]["sha256"] != phrase["audio"]["sha256"]:
        raise ValueError("grid and phrase features use different source audio")
    times = np.asarray(grid["beat_times_seconds"], dtype=float)
    views = {}
    for name, path in (("beatthis0", args.beatthis0), ("beatthis1", args.beatthis1)):
        with np.load(path) as arrays:
            views[name] = _sample(_probability(arrays["downbeat"]),
                                  float(arrays["fps"]), times)
    with np.load(args.aio_activations) as arrays:
        views["allinone"] = _sample(arrays["downbeat"], 100., times)
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_only": True, "reference_read": False,
              "selection_policy": "diagnostic only; no full-song map selected",
              "trigger": "lag14 > .65 and exceeds lag13/15 by .12 for >=5 adjacent positions",
              "all_eleven_strong_14_runs": all_runs, "selected_track_id": track_id,
              "input_sha256": {"grid": digest(args.grid),
                               "beatthis0": digest(args.beatthis0),
                               "beatthis1": digest(args.beatthis1),
                               "aio_activations": digest(args.aio_activations)},
              "regions": [rank_region(times, views, span)
                          for span in regions(all_runs[track_id], len(times))],
              "runner_sha256": digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot = args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    (args.output/"template-evidence.json").write_text(
        json.dumps(result, indent=2, allow_nan=False)+"\n")
    for region in result["regions"]:
        print(region["pulse_interval"], region["top_five"], flush=True)


if __name__ == "__main__":
    main()
