"""Sequential subprocess driver; evaluation is never loaded by source workers."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from .common import ROOT, guard, read, stamp, write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    guard(run)
    guard(run, evaluation=True)
    keys = [p.name for p in sorted((run / "source-inputs").iterdir()) if p.is_dir()]
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    records = []
    for key in keys:
        audit = run / "worker-audit" / (key + ".json")
        if audit.exists():
            print("PRESERVED", key, flush=True)
            records.append({"key": key, "previous_receipt_reused_for_resume": True,
                            "error": read(audit).get("error")})
            continue
        cmd = [sys.executable, "-m", "algorithms.variable.autoresearch_step_v1.worker",
               "--run", str(run), "--key", key]
        start = time.perf_counter()
        completed = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
        records.append({"key": key, "command": cmd, "returncode": completed.returncode,
                        "subprocess_wall_seconds": time.perf_counter() - start})
        write(run / "status.json", {"at_utc": stamp(), "state": "preparation_inference_running",
            "completed_keys": [r["key"] for r in records], "planned_keys": keys,
            "new_optimizer_iterations": 0}, replace=True)
    write(run / "driver-receipts.json", {"at_utc": stamp(), "rows": records}, replace=True)
    write(run / "status.json", {"at_utc": stamp(), "state": "preparation_inference_finished_evaluation_pending",
        "completed_keys": keys, "new_optimizer_iterations": 0,
        "next_command": "python -m algorithms.variable.autoresearch_step_v1.evaluate --run " + str(run)}, replace=True)
    guard(run)
    guard(run, evaluation=True)
    print("FINISHED_SOURCE_WORKERS", len(keys), flush=True)


if __name__ == "__main__":
    main()
