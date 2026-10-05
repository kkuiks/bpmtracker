"""Source-only attack-view sensitivity for the frozen phrase-chain choices."""
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


def rank_attacks(wav, times, begin, end, candidates):
    views, geometry = attack_views(wav, times, begin, end)
    scores = []
    winners = []
    for name, strength in views.items():
        raw = []
        for candidate in candidates:
            mask = candidate["mask"](np.arange(begin, end))
            raw.append(float(strength[np.flatnonzero(mask)].mean()))
        raw = np.asarray(raw)
        standardized = (raw-raw.mean())/(raw.std()+1e-12)
        scores.append(standardized)
        winners.append({"band_hz": list(name[0]), "radius_seconds": name[1],
                        "winner_index": int(np.argmax(raw)),
                        "raw_scores": raw.tolist(),
                        "standardized_scores": standardized.tolist()})
    aggregate = np.asarray(scores).mean(axis=0)
    return {"pulse_interval": [begin, end], "geometry": geometry,
            "candidate_labels": [row["label"] for row in candidates],
            "views": winners, "mean_z_scores": aggregate.tolist(),
            "ranking": [int(i) for i in np.argsort(-aggregate)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase-chain-evidence", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--finished-mix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")
    source = json.loads(args.phrase_chain_evidence.read_text())
    grid = json.loads(args.grid.read_text())
    if (source.get("source_only") is not True or source.get("reference_read") is not False or
            source["input_sha256"]["grid"] != digest(args.grid) or
            grid["map"]["source"]["sha256"] != digest(args.finished_mix)):
        raise ValueError("frozen source-only evidence and finished mix required")
    info = sf.info(args.finished_mix)
    if (info.samplerate, info.frames) != (grid["map"]["source"]["sample_rate"],
                                          grid["map"]["source"]["sample_frames"]):
        raise ValueError("finished mix sample clock changed")
    times = np.asarray(grid["beat_times_seconds"], dtype=float)
    start, end = source["unique_46_quarter_pair"]
    period_candidates = [{"label": f"6+6+6+5 phase {phase}",
                          "mask": lambda q, phase=phase: np.isin((q-phase)%23,(0,6,12,18))}
                         for phase in range(23)]
    period = rank_attacks(args.finished_mix, times, start, end, period_candidates)
    transition = source["motif_transfer_start_quarter"]
    split_candidates = [{"label": f"split {row['split_quarter']}",
                         "mask": lambda q, split=row["split_quarter"]:
                            np.where(q<split,(q-end)%6==0,np.isin(q%14,(0,2,8)))}
                        for row in source["six_to_fourteen_split_ranked"]]
    split = rank_attacks(args.finished_mix, times, end, transition, split_candidates)
    result = {"schema_version": 1,
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_only": True, "reference_read": False,
              "input_sha256": {"phrase_chain_evidence": digest(args.phrase_chain_evidence),
                               "grid": digest(args.grid),
                               "finished_mix": digest(args.finished_mix)},
              "period23": period, "six_to_fourteen_split": split,
              "limitation": "nine band/radius settings share the same mix and are correlated; no confidence calibration",
              "runner_sha256": digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot = args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    (args.output/"audit.json").write_text(json.dumps(result, indent=2)+"\n")
    print("23q", period["ranking"][:4],
          "split", [split["candidate_labels"][i] for i in split["ranking"]], flush=True)


if __name__ == "__main__":
    main()
