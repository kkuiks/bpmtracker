"""Select a step-tempo map only when independent acoustic views agree.

The runner sees only SHA-bound source-only candidate pools and observations.
Owner maps and scores are opened later by the separate eleven-song scorer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np

from .run_constant_grid11 import digest, read_bound, save
from .tempo_segments import _clock_times, _sample

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis_legacy"))
from music_map_contract import prepare_map, render_bars


def rank_source_candidates(pool, structure, activations, duration):
    if pool.get("reference_read") is not False:
        raise ValueError("source-only candidate pool required")
    rows=pool["candidates"]
    if len(rows)<2 or structure["activation_fps"]!=100.:
        raise ValueError("complete pool and 100 FPS independent observation required")
    beat=np.asarray(activations["beat"],dtype=float)
    down=np.asarray(activations["downbeat"],dtype=float)
    if (len(beat)!=len(down) or len(beat)/100<duration-.03 or
            not np.isfinite(beat).all() or not np.isfinite(down).all()):
        raise ValueError("finite full-source independent activations required")
    lo=pool["first_change_search_seconds"][0]-20.
    hi=pool["second_change_search_seconds"][1]+20.
    sections=np.asarray([s["start"] for s in structure["segments"]
                         if lo<=s["start"]<=hi],dtype=float)
    if len(sections)<2:
        raise ValueError("independent structural boundaries unavailable")
    period=(60/pool["base_bpm"],60/pool["alternate_bpm"])
    phase=pool["phase_seconds"]
    pulse=np.arange(math.ceil(duration/min(period))+16)
    matrix=[]
    for row in rows:
        changes=(row["first_change_pulse"],row["second_change_pulse"])
        grid=_clock_times(pulse,changes,period,phase)
        grid=grid[grid<=duration]
        mix=np.mean([row["mean_beat_probability"][key]
                     for key in ("mix0","mix1","mix2")])
        distance=float(np.min(abs(sections-row["first_change_seconds"])))
        aio_beat=float(_sample(beat,100.,grid).mean())
        aio_down=float(_sample(down,100.,grid).mean())
        matrix.append([mix,-distance,aio_beat,aio_down])
    matrix=np.asarray(matrix)
    z=(matrix-matrix.mean(axis=0))/(matrix.std(axis=0)+1e-12)
    joint=z.mean(axis=1)
    orders={"mix_three":[int(i) for i in np.argsort(-matrix[:,0])],
            "independent_beat":[int(i) for i in np.argsort(-matrix[:,2])],
            "independent_downbeat":[int(i) for i in np.argsort(-matrix[:,3])],
            "joint":[int(i) for i in np.argsort(-joint)]}
    first,second=orders["joint"][:2]
    margin=float(joint[first]-joint[second])
    decision={"accepted":bool(
        first==orders["independent_beat"][0]==orders["independent_downbeat"][0]
        and orders["mix_three"].index(first)<3
        and -matrix[first,1]<=1.0 and margin>=.05),
        "selected_candidate_index":first,
        "selected_change_pulses":[rows[first]["first_change_pulse"],
                                  rows[first]["second_change_pulse"]],
        "selected_change_seconds":[rows[first]["first_change_seconds"],
                                   rows[first]["second_change_seconds"]],
        "joint_top_to_second_margin_z":margin,
        "mix_three_rank":orders["mix_three"].index(first)+1,
        "independent_beat_rank":orders["independent_beat"].index(first)+1,
        "independent_downbeat_rank":orders["independent_downbeat"].index(first)+1,
        "nearest_structure_boundary_seconds":-float(matrix[first,1]),
        "acceptance_requirements":"Both independent beat/downbeat views rank the same candidate first; three-mix rank <=3; first change within 1s of independent section boundary; joint z margin >=.05.",
        "column_names":["mix_three_mean_beat","negative_section_distance_seconds",
                        "independent_beat","independent_downbeat"],
        "columns":matrix.tolist(),"standardized_columns":z.tolist(),
        "orders":orders,"independent_section_starts_seconds":sections.tolist()}
    return decision


def apply_clock(base, pool, decision):
    selected=pool["candidates"][decision["selected_candidate_index"]]
    first,second=selected["first_change_pulse"],selected["second_change_pulse"]
    first_time,second_time=selected["first_change_seconds"],selected["second_change_seconds"]
    duration=base["map"]["source"]["sample_frames"]/base["map"]["source"]["sample_rate"]
    base_period=60/pool["base_bpm"]
    end_pulse=second+(duration-second_time)/base_period
    result=deepcopy(base)
    result["map"]["clock_knots"]=[
        {"pulse":0.,"source_seconds":pool["phase_seconds"]},
        {"pulse":float(first),"source_seconds":float(first_time)},
        {"pulse":float(second),"source_seconds":float(second_time)},
        {"pulse":float(end_pulse),"source_seconds":float(duration)}]
    result["map"]["support_seconds"]=[[float(pool["phase_seconds"]),float(duration)]]
    prepared=prepare_map(result["map"])
    bars=render_bars(prepared)
    if bars["status"]!="rendered":
        raise ValueError("selected tempo map cannot render bars")
    pulse=np.arange(math.ceil(end_pulse)+1)
    times=_clock_times(pulse,(first,second),
                       (60/pool["base_bpm"],60/pool["alternate_bpm"]),
                       pool["phase_seconds"])
    result["beat_times_seconds"]=times[times<=duration].tolist()
    result["bar_starts_seconds"]=bars["bar_events_seconds"]
    result["diagnostics"]["constant_grid_only"]=False
    result["diagnostics"]["structural_tempo"]={k:decision[k] for k in (
        "accepted","selected_change_pulses","selected_change_seconds",
        "joint_top_to_second_margin_z","mix_three_rank","independent_beat_rank",
        "independent_downbeat_rank","nearest_structure_boundary_seconds")}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-manifest",type=Path,required=True)
    parser.add_argument("--candidate-pool",type=Path,required=True)
    parser.add_argument("--independent-manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    selected_path=args.selected_manifest.resolve()
    pool_path=args.candidate_pool.resolve()
    independent_path=args.independent_manifest.resolve()
    selected=json.loads(selected_path.read_text())
    pool=json.loads(pool_path.read_text())
    independent=json.loads(independent_path.read_text())
    if (not selected.get("complete") or len(selected.get("rows",[]))!=11 or
            selected.get("references_available_to_runner") is not False or
            independent.get("reference_read_by_inference") is not False):
        raise ValueError("eleven source-only predictions and independent model required")
    target_hash=pool["source"]["sha256"]
    matched=[r for r in selected["rows"] if r["source"]["sha256"]==target_hash]
    if len(matched)!=1 or independent["source"]["sha256"]!=target_hash:
        raise ValueError("exactly one source-bound candidate pool required")
    target=matched[0]
    base=json.loads(read_bound(target["prediction"]).read_text())
    if base["map"]["source"]!=target["source"]:
        raise ValueError("selected source geometry differs")
    structure=json.loads(read_bound(independent["output"]["json"]).read_text())
    with np.load(read_bound(independent["output"]["activations"])) as arrays:
        activation={name:arrays[name] for name in ("beat","downbeat")}
    duration=target["source"]["sample_frames"]/target["source"]["sample_rate"]
    decision=rank_source_candidates(pool,structure,activation,duration)
    output=args.output.resolve()
    output.mkdir(parents=True)
    snapshot=output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    (output/"selection-evidence.json").write_text(json.dumps({
        "schema_version":1,"source_only":True,"reference_read":False,
        "candidate_pool_sha256":digest(pool_path),
        "independent_manifest_sha256":digest(independent_path),
        "selected_manifest_sha256":digest(selected_path),
        "decision":decision,"runner_sha256":digest(__file__)},indent=2,allow_nan=False)+"\n")
    prediction=target["prediction"]
    if decision["accepted"]:
        candidate=apply_clock(base,pool,decision)
        prediction=save(output/"predictions"/(target["id"]+".json"),candidate)
    ledger={"schema_version":1,"complete":False,
            "references_available_to_runner":False,
            "input_manifest_sha256":{"selected":digest(selected_path),
                                     "candidate_pool":digest(pool_path),
                                     "independent_model":digest(independent_path)},
            "implementation_sha256":digest(__file__),"started_at_utc":datetime.now(timezone.utc).isoformat(),
            "rows":[]}
    for row in selected["rows"]:
        update=row["source"]["sha256"]==target_hash and decision["accepted"]
        ledger["rows"].append({"id":row["id"],"source":row["source"],
                               "prediction":prediction if update else row["prediction"],
                               "selected_input":row["prediction"],
                               "structural_tempo_accepted":bool(update)})
    ledger["complete"]=len(ledger["rows"])==11
    ledger["ended_at_utc"]=datetime.now(timezone.utc).isoformat()
    save(output/"prediction-manifest.json",ledger)
    print(target["id"],"accepted",decision["accepted"],
          "change pulses",decision["selected_change_pulses"],
          "margin",decision["joint_top_to_second_margin_z"])


if __name__=="__main__":main()
