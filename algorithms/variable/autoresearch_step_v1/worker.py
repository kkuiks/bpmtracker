"""Source-only process. No reference, evaluation score, role or song ID inputs."""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from .common import CONSTANT, HELD, digest, guard, read, stamp, write
from .core import constant_map, fit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    freeze = guard(run)
    directory = run / "source-inputs" / args.key
    permitted = {str((directory / name).resolve()) for name in
                 ("source.json", "prepared.json", "pinned.json")}
    source = read(directory / "source.json")
    permitted.add(str(Path(source["events_path"]).resolve()))
    opened, forbidden = [], []
    active = [True]

    def hook(event, arguments):
        if event != "open" or not active[0] or not isinstance(arguments[0], (str, bytes)):
            return
        path = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        mode = arguments[1] if isinstance(arguments[1], str) else ""
        if any(c in mode for c in "wax+"):
            return
        resolved = str(Path(path).resolve())
        if Path(path).suffix in (".json", ".npz", ".npy"):
            opened.append(resolved)
            if resolved not in permitted:
                forbidden.append(resolved)
                raise RuntimeError("Unpermitted source input: " + resolved)

    sys.addaudithook(hook)
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    stage = {}
    outputs = []
    error = None
    try:
        start = time.perf_counter()
        # Reread under the data-read audit. The schema has no reference fields.
        source = read(directory / "source.json")
        if set(source) != {"events_path", "duration_seconds"}:
            raise RuntimeError("Unexpected source input fields")
        with np.load(source["events_path"], allow_pickle=False) as data:
            events = {name: data[name].copy() for name in data.files}
        if abs(float(events["duration"]) - source["duration_seconds"]) > 1e-7:
            raise RuntimeError("Source duration changed")
        prepared = read(directory / "prepared.json")
        pinned = read(directory / "pinned.json")
        stage["load_frozen_observations_and_candidates_seconds"] = time.perf_counter() - start
        for method in (CONSTANT, HELD):
            start, cpu = time.perf_counter(), time.process_time()
            detail = {}

            def progress(depth, children, best_events):
                print("SEARCH", args.key, "depth", depth, "children", children,
                      "events", best_events, "seconds", round(time.perf_counter() - start, 3),
                      flush=True)

            result = (constant_map(pinned, source["duration_seconds"]) if method == CONSTANT
                      else fit(events, prepared, pinned, progress=progress, timings=detail))
            detail.update(fit_wall_seconds=time.perf_counter() - start,
                          fit_cpu_seconds=time.process_time() - cpu)
            serialize_start = time.perf_counter()
            target = run / "predictions" / method / (args.key + ".json")
            write(target, result)
            detail["serialize_seconds"] = time.perf_counter() - serialize_start
            detail["output_path"] = str(target)
            detail["source_map_status"] = result.get("status")
            detail["declarations"] = len(result.get("events", []))
            stage[method] = detail
            outputs.append(str(target))
            print("MAP", args.key, method, "events", detail["declarations"],
                  "seconds", round(detail["fit_wall_seconds"], 3), flush=True)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc),
                 "traceback": traceback.format_exc()}
        for method in (CONSTANT, HELD):
            target = run / "predictions" / method / (args.key + ".json")
            if not target.exists():
                write(target, {"status": "preparation_inference_failed", "events": [],
                               "duration_seconds": source["duration_seconds"], "error": error})
                outputs.append(str(target))
    finally:
        active[0] = False
        audit = {"at_utc": stamp(), "opaque_input_key": args.key,
                 "actual_read_hook": True, "opened_data_paths": sorted(set(opened)),
                 "allowed_data_paths": sorted(permitted), "forbidden_reads": forbidden,
                 "reference_and_roles_passed_to_fit": False, "stage_timings": stage,
                 "worker_wall_seconds": time.perf_counter() - wall_start,
                 "worker_cpu_seconds": time.process_time() - cpu_start, "error": error,
                 "neural_and_PCM_observations_recomputed": False,
                 "candidate_preparation_reused_not_newly_timed": True,
                 "new_optimizer_iterations": 0}
        write(run / "worker-audit" / (args.key + ".json"), audit)
        write(run / "output-receipts" / (args.key + ".json"),
              {"files": {path: digest(path) for path in outputs}})
    guard(run)
    if error or forbidden:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
