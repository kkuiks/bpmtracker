"""Source-only local proposal study after observed whole-input candidate loss.

Original spectral proposals and the frozen Simple event-line comparison are
measured separately. Windows propose hypotheses, never change timestamps.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from experiments.metronome_benchmark_v1.simple_clock import prepare_family
from experiments.metronome_benchmark_v1.inference import validate_source
from experiments.metronome_reconstruction_v1.infer import broad_candidates, make_evidence
from .common import PACKAGE, ROOT, nearest_rate, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--stage", choices=["all", "prepare", "evaluate"], default="all")
    parser.add_argument("--output-name", default="local-proposal-v2")
    args = parser.parse_args()
    run = args.run.resolve()
    output = run / args.output_name
    if args.stage == "all":
        recovery = read_json(run / "candidate-recovery/results.json")
        if not recovery["summary"]["primary_real"]["loss_stages"]:
            raise ValueError("Local proposal study requires a recorded whole-input loss")
        output.mkdir(exist_ok=False)
        protocol = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                "trigger": recovery["summary"]["primary_real"],
                "window_seconds_sweep": [2, 4, 8, 16, 32], "stride_fraction": .5,
                "methods": ["unchanged_original_spectral_broad", "frozen_simple_event_line"],
                "simple_top_unique_rate_counts": [1, 5, 20],
                "reference_fields_used_for_proposal": False,
                "window_edges_are_not_change_timestamps": True,
                "simple_not_replacing_original": True, "neural_inference_repeated": False,
                "purpose": "rate recall, proposal burden and minority-duration diagnostic; no decoder",
                "prediction_and_evaluation_workers_separate": True}
        write_json(output / "protocol.json", protocol)
        command = [sys.executable, "-m", "experiments.variable_tempo_step0.proposal", "--run", str(run),
                   "--output-name", args.output_name, "--stage"]
        subprocess.run(command + ["prepare"], cwd=ROOT, check=True)
        subprocess.run(command + ["evaluate"], cwd=ROOT, check=True)
        return
    protocol = read_json(output / "protocol.json")
    model = read_json(run / "model-config.json")
    simple = read_json(ROOT / "experiments/metronome_benchmark_v1/simple-clock-v1.json")
    sources = read_json(run / "source-inputs.json")["samples"]
    validate_source(sources)
    if args.stage == "evaluate":
        recovery = read_json(run / "candidate-recovery/results.json")
        if not read_json(output / "source-receipt.json").get("completed"):
            raise ValueError("All source proposals must be saved before reference evaluation")
    receipt = []
    for source in sources if args.stage == "prepare" else []:
        ident = source["id"]
        started = time.perf_counter()
        with np.load(run / "original/evidence" / f"{ident}.npz", allow_pickle=False) as data:
            beat, down = data["beat_logits"].copy(), data["downbeat_logits"].copy()
            fps = int(data["fps"])
        count, failed = 0, 0
        with gzip.open(output / f"{ident}.jsonl.gz", "wt", encoding="utf-8", compresslevel=3) as stream:
            for span in protocol["window_seconds_sweep"]:
                starts = np.arange(0, max(source["duration_seconds"] - span, 0) + 1e-9, span / 2).tolist()
                last = max(0, source["duration_seconds"] - span)
                if not starts or abs(starts[-1] - last) > .1:
                    starts.append(last)
                for start in starts:
                    first = int(round(start * fps))
                    end = min(len(beat), int(round((start + span) * fps)))
                    duration = (end - first) / fps
                    row = {"window_start_seconds": first / fps, "window_end_seconds": end / fps,
                           "span_seconds": span, "source_reference_fields_used": False}
                    try:
                        evidence = make_evidence(beat[first:end], down[first:end], duration, model)
                        bpms, diagnostic = broad_candidates(evidence, model)
                        row["original_broad_rates"] = [float(value) for value in bpms]
                        row["original_broad_search"] = diagnostic
                        family = prepare_family(evidence, model, simple)
                        ranked = []
                        seen = set()
                        for candidate in family.get("candidates", []):
                            value = candidate["quarter_bpm"]
                            if value in seen:
                                continue
                            seen.add(value)
                            ranked.append({"bpm": value, "score": candidate["score"],
                                           "phase_seconds_on_original_axis": (candidate["offset_seconds"] + first / fps) % candidate["period_seconds"]})
                            if len(ranked) == 20:
                                break
                        row["simple_rates_ranked"] = ranked
                        row["simple_status"] = family["status"]
                    except Exception as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                        failed += 1
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    count += 1
        receipt.append({"id": ident, "windows": count, "failed_windows": failed, "seconds": time.perf_counter() - started})
        write_json(output / "source-receipt.json", {"rows": receipt, "reference_files_read": False,
                                                   "window_edges_used_as_boundaries": False, "completed": False})
        print(f"PROPOSE {ident}: {count} windows", flush=True)
    if args.stage == "prepare":
        write_json(output / "source-receipt.json", {"rows": receipt, "reference_files_read": False,
                   "window_edges_used_as_boundaries": False, "completed": True})
        return
    # Only after all source proposals are persisted do reference targets enter.
    evaluations = []
    for target in recovery["rows"]:
        ident, bpm = target["id"], target["nominal_target_bpm"]
        spans = {}
        with gzip.open(output / f"{ident}.jsonl.gz", "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                span = str(row["span_seconds"])
                info = spans.setdefault(span, {"window_count": 0, "original_broad_hits": 0,
                                              "simple_top1_hits": 0, "simple_top5_hits": 0, "simple_top20_hits": 0,
                                              "contained_window_count": 0, "contained_simple_top20_hits": 0,
                                              "best_simple_rank": None, "maximum_broad_proposal_count": 0})
                info["window_count"] += 1
                info["original_broad_hits"] += any(abs(value - bpm) < 1e-9 for value in row.get("original_broad_rates", []))
                info["maximum_broad_proposal_count"] = max(info["maximum_broad_proposal_count"], len(row.get("original_broad_rates", [])))
                rank = next((i for i, value in enumerate(row.get("simple_rates_ranked", []), 1) if abs(value["bpm"] - bpm) < 1e-9), None)
                for limit in (1, 5, 20):
                    info[f"simple_top{limit}_hits"] += rank is not None and rank <= limit
                if rank is not None:
                    info["best_simple_rank"] = min(info["best_simple_rank"] or rank, rank)
                contained = row["window_start_seconds"] >= target["start_seconds"] and row["window_end_seconds"] <= target["end_seconds"]
                info["contained_window_count"] += contained
                info["contained_simple_top20_hits"] += contained and rank is not None
        evaluations.append({"id": ident, "segment_index": target["segment_index"], "variant": target["variant"],
                            "reference_bpm": target["quarter_bpm"], "nominal_bpm": bpm,
                            "segment_duration_seconds": target["duration_seconds"], "spans": spans,
                            "window_membership_is_evaluation_only": True})
    summary = {}
    for name, targets in (("primary_real", [r for r in evaluations if r["variant"] == "real_variable"]),
                          ("constructed_variable", [r for r in evaluations if r["variant"] in {"step", "return", "large", "octave", "small", "short_bar", "silent_change"}])):
        summary[name] = {"segment_denominator": len(targets), "spans": {
            str(span): {"original_broad_recovered": sum(r["spans"][str(span)]["original_broad_hits"] > 0 for r in targets),
                        "simple_top1_recovered": sum(r["spans"][str(span)]["simple_top1_hits"] > 0 for r in targets),
                        "simple_top5_recovered": sum(r["spans"][str(span)]["simple_top5_hits"] > 0 for r in targets),
                        "simple_top20_recovered": sum(r["spans"][str(span)]["simple_top20_hits"] > 0 for r in targets)}
            for span in protocol["window_seconds_sweep"]}}
    write_json(output / "results.json", {"rows": evaluations, "summary": summary,
               "no_boundary_predictions_from_windows": True, "source_proposals_precede_reference_evaluation": True})
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
