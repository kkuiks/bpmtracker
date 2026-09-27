"""Rank repeated-meter phase candidates against independent section boundaries.

The caller declares a source-observed quarter interval and a short-bar grammar.
This diagnostic never opens an approved meter map or uses it to choose phase.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

from .run_constant_grid11 import digest


def rank_phase(grid, section_starts, pulse_start, pulse_end, *, phrase_quarters=22):
    times=np.asarray(grid,dtype=float)
    starts=np.asarray(section_starts,dtype=float)
    if (pulse_start<0 or pulse_end>len(times) or pulse_end<=pulse_start or
            np.any(np.diff(times)<=0) or np.any(np.diff(starts)<=0)):
        raise ValueError("ordered full grid and section boundaries required")
    offset_candidates=(0,2,6,10,14,18)
    rows=[]
    for relationship in ("short_bar_start","first_full_bar_after_short"):
        offset=0 if relationship=="short_bar_start" else 2
        for phase in range(phrase_quarters):
            indices=[q for q in range(max(0,pulse_start-22),
                                      min(len(times),pulse_end+22))
                     if (q-phase)%phrase_quarters==offset]
            candidates=times[indices]
            errors=np.min(abs(starts[:,None]-candidates[None,:]),axis=1)
            rows.append({"relationship":relationship,"phase":phase,
                         "mean_absolute_section_distance_seconds":float(errors.mean()),
                         "matched_within_one_second":int(np.sum(errors<=1.)),
                         "section_distance_seconds":errors.tolist()})
    return rows,offset_candidates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid",type=Path,required=True)
    parser.add_argument("--structure",type=Path,required=True)
    parser.add_argument("--pulse-start",type=int,required=True)
    parser.add_argument("--pulse-end",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    prediction=json.loads(args.grid.read_text())
    structure=json.loads(args.structure.read_text())
    if structure.get("activation_fps")!=100.:
        raise ValueError("official 100 FPS structure observation required")
    grid=prediction["beat_times_seconds"]
    if not 0<=args.pulse_start<args.pulse_end<=len(grid):
        raise ValueError("invalid pulse interval")
    lo,hi=grid[args.pulse_start],grid[args.pulse_end-1]
    boundaries=[s["start"] for s in structure["segments"] if lo<=s["start"]<=hi]
    rows,bar_offsets=rank_phase(grid,boundaries,args.pulse_start,args.pulse_end)
    rankings={relationship:[r["phase"] for r in sorted(
        (x for x in rows if x["relationship"]==relationship),
        key=lambda x:x["mean_absolute_section_distance_seconds"])]
        for relationship in ("short_bar_start","first_full_bar_after_short")}
    result={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_only":True,"reference_read":False,
            "input_sha256":{"grid":digest(args.grid),"structure":digest(args.structure)},
            "pulse_interval":[args.pulse_start,args.pulse_end],
            "phrase_quarters":22,"hypothesized_bar_offsets":bar_offsets,
            "section_boundaries_seconds":boundaries,
            "hypothesized_structure_relationships":list(rankings),
            "candidate_scores":rows,"rankings":rankings,
            "selection_policy":"diagnostic only; no full-song meter map selected",
            "runner_sha256":digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot=args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    (args.output/"phase-evidence.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    for k,v in rankings.items():print(k,v[:8],flush=True)


if __name__=="__main__":main()
