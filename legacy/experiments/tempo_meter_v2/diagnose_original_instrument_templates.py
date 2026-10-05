"""Compare source-aligned original instrument renders on frozen meter templates.

Only acoustic candidate evidence and audio are read. This is a diagnostic,
not an independent-finished-mix route or an accepted map proposal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from .diagnose_late_meter_phase import attack_views
from .run_constant_grid11 import digest


def rank_views(path: Path, times, evidence: dict, expected_source: dict) -> dict:
    info = sf.info(path)
    if (info.samplerate, info.frames) != (expected_source["sample_rate"],
                                         expected_source["sample_frames"]):
        raise ValueError(f"instrument render has a different sample clock: {path}")
    candidates = evidence["candidates"]
    begin, end = evidence["source_detected_pulse_region"] if "source_detected_pulse_region" in evidence else evidence["regions"][0]["pulse_interval"]
    views, geometry = attack_views(path, times, begin, end)
    scores = []
    for candidate in candidates:
        period = 22 if "phase_modulo22" in candidate else 14
        phase = candidate[f"phase_modulo{period}"]
        offsets = candidate.get("bar_offsets_within_phrase", candidate.get("bar_offsets"))
        indices = [q-begin for q in range(begin, end) if (q-phase) % period in offsets]
        scores.append([float(view[indices].mean()) for view in views.values()])
    matrix = np.asarray(scores)
    standardized = (matrix-matrix.mean(axis=0))/(matrix.std(axis=0)+1e-12)
    aggregate = standardized.mean(axis=1)
    order = np.argsort(-aggregate)
    return {"audio": {"path": str(path.resolve()), "sha256": digest(path)},
            "geometry": geometry, "candidate_count": len(candidates),
            "region": [begin, end],
            "mean_z_scores": aggregate.tolist(),
            "ranking": [int(i) for i in order]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--twentytwo-grid", type=Path, required=True)
    parser.add_argument("--fourteen-evidence", type=Path, required=True)
    parser.add_argument("--twentytwo-evidence", type=Path, required=True)
    parser.add_argument("--instrument-wav", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    prediction = json.loads(args.grid.read_text())
    twenty_two_grid = json.loads(args.twentytwo_grid.read_text())
    source = prediction["map"]["source"]
    times = np.asarray(prediction["beat_times_seconds"])
    fourteen = json.loads(args.fourteen_evidence.read_text())
    twenty_two = json.loads(args.twentytwo_evidence.read_text())
    if (fourteen.get("source_only") is not True or fourteen.get("reference_read") is not False or
            twenty_two.get("source_only") is not True or twenty_two.get("reference_read") is not False or
            fourteen["input_sha256"]["grid"] != digest(args.grid) or
            twenty_two["input_sha256"]["grid"] != digest(args.twentytwo_grid) or
            twenty_two_grid["map"]["source"] != source or
            not np.array_equal(twenty_two_grid["beat_times_seconds"], times)):
        raise ValueError("frozen source-only template evidence required")
    target_id = args.grid.stem
    if (fourteen["selected_track_id"] != target_id or
            twenty_two["selected_track_id"] != target_id):
        raise ValueError("template evidence is for another track")
    # The merged middle 14-quarter region is derived from overlapping runs.
    merged = fourteen["regions"][-1]
    if merged["pulse_interval"] != [444, 552]:
        raise ValueError("expected source-derived merged middle region changed")
    fourteen = {"candidates": merged["candidates"],
                "source_detected_pulse_region": merged["pulse_interval"]}
    rows = []
    for path in args.instrument_wav:
        rows.append({"name": path.name,
                     "fourteen": rank_views(path, times, fourteen, source),
                     "twentytwo": rank_views(path, times, twenty_two, source)})
    output = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_only": True, "reference_read": False,
              "selection_policy": "diagnostic only; no map selected",
              "clock_equality_is_not_proof_of_original_render_alignment": True,
              "inputs": {"grid": {"path": str(args.grid.resolve()), "sha256": digest(args.grid)},
                         "twentytwo_grid_sha256": digest(args.twentytwo_grid),
                         "fourteen_evidence_sha256": digest(args.fourteen_evidence),
                         "twentytwo_evidence_sha256": digest(args.twentytwo_evidence)},
              "instrument_rows": rows, "runner_sha256": digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot = args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    (args.output/"ranking.json").write_text(json.dumps(output, indent=2)+"\n")
    for row in rows:
        print(row["name"], "14q top", row["fourteen"]["ranking"][0],
              "22q top", row["twentytwo"]["ranking"][0], flush=True)


if __name__ == "__main__":
    main()
