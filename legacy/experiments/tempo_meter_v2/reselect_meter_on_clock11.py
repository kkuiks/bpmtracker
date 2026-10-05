"""Rerank constant bar size and phase after a source-only tempo-map change.

A changed quarter clock invalidates the old constant-bar score. This control
reruns the same acoustic candidate ranking on the new grid, with two bound
Beat This downbeat views, then leaves all other eleven-song rows unchanged.
No owner reference is read before outputs are frozen.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np

from .constant_grid import select_bar_grid
from .run_constant_grid11 import digest, read_bound, save

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis_legacy"))
from music_map_contract import prepare_map, render_bars


def observations(logit_path, event_path):
    with np.load(logit_path) as values:
        down=values["downbeat"]
        fps=float(values["fps"])
    events=json.loads(event_path.read_text())
    if "methods" in events:
        downbeats=events["methods"]["official"]["prediction"]["downbeats_seconds"]
    else:
        downbeats=events["downbeats_seconds"]
    return down,fps,downbeats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-manifest",type=Path,required=True)
    parser.add_argument("--target-prediction",type=Path,required=True)
    parser.add_argument("--final0-logits",type=Path,required=True)
    parser.add_argument("--final0-events",type=Path,required=True)
    parser.add_argument("--final1-logits",type=Path,required=True)
    parser.add_argument("--final1-events",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    source=json.loads(args.target_prediction.read_text())
    if source["status"]!="proposed_map" or not source["diagnostics"].get("structural_tempo",{}).get("accepted"):
        raise ValueError("accepted source-only structural tempo proposal required")
    manifest=json.loads(args.selected_manifest.read_text())
    if not manifest.get("complete") or manifest.get("references_available_to_runner") is not False or len(manifest["rows"])!=11:
        raise ValueError("eleven source-only predictions required")
    target_sha=source["map"]["source"]["sha256"]
    target=[row for row in manifest["rows"] if row["source"]["sha256"]==target_sha]
    if len(target)!=1 or digest(args.target_prediction)!=target[0]["prediction"]["sha256"]:
        raise ValueError("target must be the bound eleven-song prediction")
    grid=np.asarray(source["beat_times_seconds"],dtype=float)
    by_seed={}
    for name,logit_path,event_path in (("final0",args.final0_logits,args.final0_events),
                                       ("final1",args.final1_logits,args.final1_events)):
        down,fps,events=observations(logit_path,event_path)
        by_seed[name]=select_bar_grid(grid,down,fps,events)
    by_key={name:{(item["beats_per_bar"],item["first_bar_beat_index"]):item
                  for item in candidates} for name,candidates in by_seed.items()}
    if set(by_key["final0"])!=set(by_key["final1"]):
        raise ValueError("same constant bar hypotheses required")
    rows=[]
    for size,offset in by_key["final0"]:
        scores={name:by_key[name][(size,offset)]["score"] for name in by_key}
        rows.append({"beats_per_bar":size,"first_bar_beat_index":offset,
                     "source_scores":scores,"mean_source_score":float(np.mean(list(scores.values())))})
    rows.sort(key=lambda item:(-item["mean_source_score"],
                               abs(item["beats_per_bar"]-4),item["first_bar_beat_index"]))
    winner=rows[0]
    result=deepcopy(source)
    size=winner["beats_per_bar"]
    result["map"]["bar_anchor_pulse"]=float(winner["first_bar_beat_index"])
    result["map"]["meter_events"]=[{"pulse":0.,"numerator":size,
                                     "denominator":4,"grouping":[1]*size,
                                     "bar_action":"continue"}]
    rendered=render_bars(prepare_map(result["map"]))
    if rendered["status"]!="rendered":raise ValueError("reranked map cannot render")
    result["bar_starts_seconds"]=rendered["bar_events_seconds"]
    result["diagnostics"]["fixed_meter_reselect"]={"source_only":True,
        "winner":winner,"candidate_count":len(rows),
        "source_logit_sha256":{name:digest(path) for name,path in
            (("final0",args.final0_logits),("final1",args.final1_logits))}}
    output=args.output.resolve();output.mkdir(parents=True)
    snapshot=output/"source-snapshot";snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    binding=save(output/"predictions"/(target[0]["id"]+".json"),result)
    ledger={"schema_version":1,"complete":True,
            "references_available_to_runner":False,
            "input_manifest_sha256":digest(args.selected_manifest),
            "target_prediction_sha256":digest(args.target_prediction),
            "implementation_sha256":digest(__file__),
            "observations_sha256":{name:digest(path) for name,path in (
                ("final0_logits",args.final0_logits),("final0_events",args.final0_events),
                ("final1_logits",args.final1_logits),("final1_events",args.final1_events))},
            "created_at_utc":datetime.now(timezone.utc).isoformat(),
            "rows":[{"id":row["id"],"source":row["source"],
                     "prediction":binding if row["source"]["sha256"]==target_sha else row["prediction"],
                     "selected_input":row["prediction"]} for row in manifest["rows"]]}
    save(output/"prediction-manifest.json",ledger)
    save(output/"candidate-ranking.json",{"source_only":True,"reference_read":False,
                                           "candidates":rows,"selected":winner})
    print(target[0]["id"],"selected",size,"/4 phase",winner["first_bar_beat_index"],
          "mean score",winner["mean_source_score"])


if __name__=="__main__":main()
