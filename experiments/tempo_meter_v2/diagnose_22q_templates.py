"""Source-only 22-quarter repeated-bar template competition.

This diagnostic ranks 2/4+five-4/4 versus 6/4+four-4/4 with beat-synchronous
recurrence, two Beat This streams and independent All-In-One observations.
No owner map is read; no full-song proposal is selected.
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


def strong_22_runs(path):
    with np.load(path) as arrays:
        count=min(*(len(arrays[f"lag{lag}"]) for lag in (21,22,23)))
        main=arrays["lag22"][:count]
        contrast=main-np.maximum(arrays["lag21"][:count],
                                 arrays["lag23"][:count])
    hits=np.flatnonzero((main>.65)&(contrast>.15))
    runs=[]
    for index in hits:
        if not runs or index>runs[-1][-1]+1:runs.append([int(index)])
        else:runs[-1].append(int(index))
    return [[r[0],r[-1],len(r)] for r in runs if len(r)>=6]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase-root",type=Path,required=True)
    parser.add_argument("--grid",type=Path,required=True)
    parser.add_argument("--beatthis0",type=Path,required=True)
    parser.add_argument("--beatthis1",type=Path,required=True)
    parser.add_argument("--aio-json",type=Path,required=True)
    parser.add_argument("--aio-activations",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    all_runs={}
    for manifest_path in sorted(args.phrase_root.glob('*/manifest.json')):
        manifest=json.loads(manifest_path.read_text())
        if manifest.get("reference_used") is not False:
            raise ValueError("source-only phrase feature required")
        feature=read_bound(manifest["features"])
        all_runs[manifest_path.parent.name]=strong_22_runs(feature)
    if len(all_runs)!=11:
        raise ValueError("eleven source-only phrase feature sets required")
    grid_value=json.loads(args.grid.read_text())
    track_id=args.grid.stem
    if track_id not in all_runs or not all_runs[track_id]:
        raise ValueError("no sustained source-only 22-quarter run")
    phrase_manifest=json.loads((args.phrase_root/track_id/'manifest.json').read_text())
    if phrase_manifest["audio"]["sha256"]!=grid_value["map"]["source"]["sha256"]:
        raise ValueError("phrase and grid source differ")
    times=np.asarray(grid_value["beat_times_seconds"],dtype=float)
    runs=all_runs[track_id]
    begin=max(0,min(r[0] for r in runs)-22)
    end=min(len(times),max(r[1] for r in runs)+44)
    views={}
    for name,path in (("beatthis0",args.beatthis0),("beatthis1",args.beatthis1)):
        with np.load(path) as arrays:
            views[name]=_sample(_probability(arrays["downbeat"]),
                                float(arrays["fps"]),times)
    with np.load(args.aio_activations) as arrays:
        views["allinone"]=_sample(arrays["downbeat"],100.,times)
    aio=json.loads(args.aio_json.read_text())
    if aio["activation_fps"]!=100.:
        raise ValueError("All-In-One 100 FPS result required")
    boundaries=np.asarray([item["start"] for item in aio["segments"]
                           if times[begin]<=item["start"]<=times[end-1]])
    if len(boundaries)<2:
        raise ValueError("independent section boundaries unavailable")
    rows=[]
    for exceptional in (2,6):
        offsets=tuple([0]+[exceptional+4*i for i in range((22-exceptional)//4)])
        if offsets[-1]>=22:raise AssertionError("invalid bar partition")
        for phase in range(22):
            bar_indices=np.asarray([q for q in range(begin,end)
                                    if (q-phase)%22 in offsets],dtype=int)
            full_after=np.asarray([q for q in range(max(0,begin-22),
                                         min(len(times),end+22))
                                   if (q-phase)%22==exceptional],dtype=int)
            source_scores={name:float(value[bar_indices].mean())
                           for name,value in views.items()}
            section_error=np.min(abs(boundaries[:,None]-times[full_after][None,:]),axis=1)
            rows.append({"exceptional_bar_quarters":exceptional,
                         "normal_bar_quarters":4,"phase_modulo22":phase,
                         "bar_offsets_within_phrase":list(offsets),
                         "mean_downbeat_observations":source_scores,
                         "mean_section_distance_after_exception_seconds":float(section_error.mean()),
                         "section_distance_seconds":section_error.tolist()})
    columns=np.asarray([[row["mean_downbeat_observations"][key]
                         for key in ("beatthis0","beatthis1","allinone")]
                        +[-row["mean_section_distance_after_exception_seconds"]]
                        for row in rows])
    z=(columns-columns.mean(axis=0))/(columns.std(axis=0)+1e-12)
    rankings={name:[int(i) for i in np.argsort(-z[:,indices].mean(axis=1))]
              for name,indices in (("beatthis_two",(0,1)),
                                   ("beatthis_two_plus_sections",(0,1,3)),
                                   ("all_four",(0,1,2,3)))}
    result={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_only":True,"reference_read":False,"selection_policy":"diagnostic only",
            "input_sha256":{name:digest(path) for name,path in (
                ("grid",args.grid),("beatthis0",args.beatthis0),
                ("beatthis1",args.beatthis1),("aio_json",args.aio_json),
                ("aio_activations",args.aio_activations))},
            "all_eleven_strong_22_runs":all_runs,
            "trigger":"lag22 > .65 and exceeds both lag21/23 by .15 for >=6 consecutive positions",
            "selected_track_id":track_id,"source_detected_pulse_region":[begin,end],
            "section_boundaries_seconds":boundaries.tolist(),
            "section_relation_hypothesis":"section starts near first full 4/4 bar after exceptional bar",
            "candidates":rows,"rankings":rankings,"standardized_columns":z.tolist(),
            "runner_sha256":digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot=args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    (args.output/"template-evidence.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print('source region',begin,end)
    for name,order in rankings.items():
        print(name,[(rows[i]["exceptional_bar_quarters"],
                     rows[i]["phase_modulo22"]) for i in order[:5]])


if __name__=="__main__":main()
