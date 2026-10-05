"""Evaluation-only counterfactual for unobservable source-start meter notation.

The primary six-gate scorer and accepted references are unchanged. This probe
exempts a required meter change only if its preceding bar begins before source
support and removing that notation yields exactly the same in-source bar grid.
Every other predicted meter change remains a false positive unless it is an
exactly matching optional declaration, which is neutralized one-to-one.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from .score_primary11 import CATALOG, bar_f1_70ms, bound, change_gate, digest
from .score_primary8 import (_meter_changes, _source_geometry, read_bound,
                             reference_map)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis_legacy"))
from grid_metrics import meter_change_metrics, within_tolerance
from music_map_contract import (interpolate_clock, prepare_map, render_bars)


def observable_bars(value):
    bars = render_bars(prepare_map(value))
    if bars["status"] != "rendered":
        raise ValueError("map cannot render bars")
    lo, hi = value["support_seconds"][0][0], value["support_seconds"][-1][1]
    return [float(t) for t in bars["bar_events_seconds"]
            if lo - 1e-9 <= t < hi + 1e-9]


def optional_source_start_changes(reference):
    """Identify notation changes with a physically identical supported grid."""
    events = reference["meter_events"]
    support_start = reference["support_seconds"][0][0]
    bars = observable_bars(reference)
    optional = []
    for index in range(1, len(events)):
        before, current = events[index-1], events[index]
        old_time = interpolate_clock(reference["clock_knots"], before["pulse"])
        new_time = interpolate_clock(reference["clock_knots"], current["pulse"])
        if not (old_time < support_start <= new_time and
                new_time < reference["support_seconds"][-1][1] and
                not any(support_start <= bar < new_time - 1e-8 for bar in bars)):
            continue
        alternate = deepcopy(reference)
        alternate["bar_anchor_pulse"] = current["pulse"]
        alternate["meter_events"] = [
            {**before, "numerator": current["numerator"],
             "denominator": current["denominator"],
             "grouping": current.get("grouping"),
             "bar_action": current.get("bar_action", "continue")},
            *events[index+1:]]
        try:
            other_bars = observable_bars(alternate)
        except (ValueError, TypeError, KeyError):
            continue
        if len(bars) == len(other_bars) and all(
                abs(a-b) <= 1e-8 for a,b in zip(bars, other_bars)):
            optional.append({"source_seconds": float(new_time),
                "numerator": int(current["numerator"]),
                "denominator": int(current["denominator"]),
                "preceding_bar_start_seconds": float(old_time),
                "in_source_bar_count": len(bars),
                "maximum_bar_difference_seconds":
                    max((abs(a-b) for a,b in zip(bars, other_bars)),default=0.)})
    return optional


def revised_meter_metric(reference_events, predicted_events, optional):
    remaining_reference = list(reference_events)
    remaining_prediction = list(predicted_events)
    neutralized = []
    for item in optional:
        matching_reference = next((i for i,r in enumerate(remaining_reference)
            if (r["numerator"],r["denominator"]) ==
               (item["numerator"],item["denominator"]) and
               within_tolerance(r["source_seconds"],item["source_seconds"],1e-7)), None)
        if matching_reference is None:
            raise ValueError("optional declaration was not a strict reference change")
        remaining_reference.pop(matching_reference)
        predicted_match = next((i for i,p in enumerate(remaining_prediction)
            if (p["numerator"],p["denominator"]) ==
               (item["numerator"],item["denominator"]) and
               within_tolerance(p["source_seconds"],item["source_seconds"],.5)), None)
        if predicted_match is not None:
            neutralized.append(remaining_prediction.pop(predicted_match))
    counts = meter_change_metrics(remaining_reference,remaining_prediction,
                                   time_tolerance_seconds=.5)
    return counts, neutralized


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest",type=Path,required=True)
    parser.add_argument("--strict-per-track",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("new probe output required")
    manifest=json.loads(args.candidate_manifest.read_text())
    if (not manifest.get("complete") or
        manifest.get("references_available_to_runner") is not False or
        len(manifest.get("rows",[])) != 11):
        raise ValueError("frozen complete source-only predictions required")
    catalog=json.loads(CATALOG.read_text())
    strict=json.loads(args.strict_per_track.read_text())
    by_id={row["id"]:row for row in manifest["rows"]}
    scored={row["id"]:row for row in strict}
    if (set(by_id)!={row["id"] for row in catalog["tracks"]} or
        set(scored)!=set(by_id)):
        raise ValueError("eleven score/reference identities differ")
    rows=[]
    for track in catalog["tracks"]:
        name=track["id"]
        source=_source_geometry(track)
        if by_id[name]["source"] != source:
            raise ValueError("prediction source geometry changed")
        ref=reference_map(track,read_bound(track["accepted_tempo_map"]),source)
        pred=prepare_map(bound(Path(by_id[name]["prediction"]["path"]),
                               by_id[name]["prediction"]["sha256"])["map"])
        support=ref["support_seconds"]
        refs=_meter_changes(ref,support)
        preds=_meter_changes(pred,pred["support_seconds"])
        optional=optional_source_start_changes(ref)
        counts,neutral=revised_meter_metric(refs,preds,optional)
        old=scored[name]
        if old["prediction_sha256"] != by_id[name]["prediction"]["sha256"]:
            raise ValueError("strict result and candidate prediction differ")
        gates=dict(old["gates"])
        gates["meter_change_f1_or_no_false_positives_500ms"]=change_gate(counts)
        passed=all(v is not None and v>=.9 for v in gates.values())
        rows.append({"id":name,"strict_pass":old["all_six_at_least_90_percent"],
            "counterfactual_pass":passed,"strict_meter_change":old["meter_change_500ms"],
            "counterfactual_meter_change":counts,
            "optional_source_start_events":optional,
            "neutralized_predicted_events":neutral,
            "gates":gates})
    out=args.output.resolve();out.mkdir(parents=True)
    snapshot=out/"source-snapshot";snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    payload={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "counterfactual_only":True,"accepted_scoring_policy_changed":False,
        "strict_per_track_sha256":digest(args.strict_per_track),
        "candidate_manifest_sha256":digest(args.candidate_manifest),
        "catalog_sha256":digest(CATALOG),"runner_sha256":digest(__file__),
        "false_positive_policy":"Every nonneutral predicted change remains an FP; no-change songs fail on any FP. A single exact optional declaration can be neutralized one-to-one.",
        "strict_passed":sum(r["strict_pass"] for r in rows),
        "counterfactual_passed":sum(r["counterfactual_pass"] for r in rows),
        "rows":rows}
    (out/"counterfactual.json").write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    print('strict',payload['strict_passed'],'counterfactual',payload['counterfactual_passed'])
    print('optional',[(r['id'],len(r['optional_source_start_events'])) for r in rows if r['optional_source_start_events']])

if __name__=="__main__":main()
