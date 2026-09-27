"""Freeze source-only section, motif and meter-grammar evidence for one mix.

The candidate vocabulary is a known-development hypothesis. This diagnostic
never reads the owner map, and its margins are not calibrated confidence.
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
from .run_early_phrase_prior11 import select_early_template
from .tempo_segments import _sample


def mean_log_likelihood(quarters, bar_mask, views):
    if not np.any(bar_mask) or np.all(bar_mask):
        raise ValueError("bar hypothesis must have positive and negative quarters")
    scores = []
    for name, values in views.items():
        p = np.clip(values[quarters], .05, .95)
        scores.append((name, float(np.mean(np.where(bar_mask, np.log(p), np.log(1-p))))))
    return float(np.mean([value for _, value in scores])), dict(scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--early-late-manifest", type=Path, required=True)
    parser.add_argument("--fourteen-evidence", type=Path, required=True)
    parser.add_argument("--public-audit", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--phrase-manifest", type=Path, required=True)
    parser.add_argument("--beatthis0", type=Path, required=True)
    parser.add_argument("--beatthis1", type=Path, required=True)
    parser.add_argument("--aio-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new output required")

    manifest = json.loads(args.early_late_manifest.read_text())
    evidence = json.loads(args.fourteen_evidence.read_text())
    audit = json.loads(args.public_audit.read_text())
    grid = json.loads(args.grid.read_text())
    phrase = json.loads(args.phrase_manifest.read_text())
    aio = json.loads(args.aio_manifest.read_text())
    if (manifest.get("complete") is not True or len(manifest.get("rows", [])) != 11 or
            manifest.get("references_available_to_runner") is not False or
            evidence["input_sha256"]["grid"] != digest(args.grid) or
            evidence["input_sha256"]["beatthis0"] != digest(args.beatthis0) or
            evidence["input_sha256"]["beatthis1"] != digest(args.beatthis1) or
            phrase.get("reference_used") is not False or
            phrase["audio"]["sha256"] != grid["map"]["source"]["sha256"] or
            aio.get("reference_read_by_inference") is not False or
            aio["source"]["sha256"] != grid["map"]["source"]["sha256"]):
        raise ValueError("source-only input identity or scope changed")
    track_id = evidence["selected_track_id"]
    selected = next(row for row in manifest["rows"] if row["id"] == track_id)
    prediction = json.loads(read_bound(selected["prediction"]).read_text())
    if (prediction["map"]["source"] != grid["map"]["source"] or
            prediction["beat_times_seconds"] != grid["beat_times_seconds"]):
        raise ValueError("early-late proposal uses another source grid")
    _, early_starts, early_details = select_early_template(evidence, audit)
    late_starts = prediction["diagnostics"]["public_meter_prior_pilot"]["exceptional_bar_start_pulses"]
    if prediction["diagnostics"]["early_phrase_prior"]["early_exceptional_starts"] != early_starts:
        raise ValueError("early trigger changed")
    times = np.asarray(grid["beat_times_seconds"], dtype=float)
    views = {}
    for name, path in (("beatthis0", args.beatthis0), ("beatthis1", args.beatthis1)):
        with np.load(path) as arrays:
            views[name] = _sample(_probability(arrays["downbeat"]),
                                  float(arrays["fps"]), times)
    aio_json_path = Path(aio["output"]["json"]["path"])
    aio_activ_path = Path(aio["output"]["activations"]["path"])
    if (digest(aio_json_path) != aio["output"]["json"]["sha256"] or
            digest(aio_activ_path) != aio["output"]["activations"]["sha256"]):
        raise ValueError("independent structure output changed")
    with np.load(aio_activ_path) as arrays:
        views["allinone"] = _sample(arrays["downbeat"], 100., times)
    segments = json.loads(aio_json_path.read_text())["segments"]
    boundaries = []
    for segment in segments:
        second = float(segment["start"])
        quarter = int(np.argmin(abs(times-second)))
        error = float(second-times[quarter])
        if abs(error) <= .07:
            boundaries.append({"quarter": quarter, "source_seconds": second,
                               "signed_grid_error_seconds": error})
    pairs = [(left, right) for left, right in zip(boundaries, boundaries[1:])
             if right["quarter"]-left["quarter"] == 46 and
             left["quarter"] > early_starts[-1]+2 and right["quarter"] < late_starts[0]]
    if len(pairs) != 1:
        raise ValueError("unique source-observed two-by-23-quarter section required")
    pair_start, pair_end = (item["quarter"] for item in pairs[0])
    q23 = np.arange(pair_start, pair_end)
    motif23 = []
    for phase in range(23):
        mask = np.isin((q23-phase) % 23, (0, 6, 12, 18))
        score, per_view = mean_log_likelihood(q23, mask, views)
        motif23.append({"family": "6+6+6+5", "phase_modulo23": phase,
                        "mean_log_likelihood": score, "views": per_view})
    regular_controls = []
    for size in range(2, 9):
        for phase in range(size):
            score, per_view = mean_log_likelihood(q23, (q23-phase) % size == 0, views)
            regular_controls.append({"family": f"regular_{size}", "phase": phase,
                                     "mean_log_likelihood": score, "views": per_view})
    motif23.sort(key=lambda row: -row["mean_log_likelihood"])
    regular_controls.sort(key=lambda row: -row["mean_log_likelihood"])
    if (motif23[0]["phase_modulo23"] != pair_start % 23 or
            motif23[0]["mean_log_likelihood"] <= regular_controls[0]["mean_log_likelihood"]):
        raise ValueError("source signal does not select section-anchored 23q motif")

    vectors_path = read_bound(phrase["features"])
    with np.load(vectors_path) as arrays:
        vectors = arrays["vectors"]
    template = np.mean([vectors[q:q+14] for q in early_starts], axis=0)
    region = evidence["regions"][-1]["pulse_interval"]
    early_phase = early_details["candidate"]["phase_modulo14"]
    motif_pairs = []
    for quarter in range(max(pair_end+14, region[0]), min(region[1], late_starts[0]-14)):
        if quarter % 14 != early_phase:
            continue
        first = float(np.mean(np.sum(template*vectors[quarter:quarter+14], axis=1)))
        second = float(np.mean(np.sum(template*vectors[quarter+14:quarter+28], axis=1)))
        motif_pairs.append({"start_quarter": quarter, "similarity": [first, second]})
    strong_motifs = [row for row in motif_pairs if min(row["similarity"]) > .4]
    if len(strong_motifs) != 1:
        raise ValueError("unique two-cycle opening-motif transfer required")
    motif_transition = strong_motifs[0]["start_quarter"]

    split_candidates = []
    q = np.arange(pair_end, motif_transition)
    for split in range(pair_end+28, motif_transition-27):
        if split % 14 != early_phase:
            continue
        mask = np.where(q < split, (q-pair_end) % 6 == 0,
                        np.isin((q-early_phase) % 14, (0, 2, 8)))
        score, per_view = mean_log_likelihood(q, mask, views)
        split_candidates.append({"split_quarter": split, "mean_log_likelihood": score,
                                 "views": per_view})
    split_candidates.sort(key=lambda row: -row["mean_log_likelihood"])
    if len(split_candidates) < 2:
        raise ValueError("insufficient source-only six-to-14 split candidates")
    split = split_candidates[0]["split_quarter"]
    q6 = np.arange(pair_end, split)
    six_contrast = {name: float(value[q6[q6 % 6 == pair_end % 6]].mean()-
                                value[q6[q6 % 6 != pair_end % 6]].mean())
                    for name, value in views.items()}
    if min(six_contrast["beatthis0"], six_contrast["beatthis1"]) <= .2:
        raise ValueError("six-quarter continuation lacks two-model support")
    q4 = np.arange(early_starts[-1]+2, pair_start)
    four_phase = q4[0] % 4
    four_contrast = {name: float(value[q4[q4 % 4 == four_phase]].mean()-
                                 value[q4[q4 % 4 != four_phase]].mean())
                     for name, value in views.items()}
    if min(four_contrast["beatthis0"], four_contrast["beatthis1"]) <= .1:
        raise ValueError("long four-quarter substrate lacks two-model support")

    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_only": True, "reference_read": False,
              "selected_track_id": track_id,
              "input_sha256": {"early_late_manifest": digest(args.early_late_manifest),
                               "fourteen_evidence": digest(args.fourteen_evidence),
                               "public_audit": digest(args.public_audit),
                               "grid": digest(args.grid),
                               "phrase_manifest": digest(args.phrase_manifest),
                               "beatthis0": digest(args.beatthis0),
                               "beatthis1": digest(args.beatthis1),
                               "aio_manifest": digest(args.aio_manifest)},
              "section_boundaries_within70ms": boundaries,
              "unique_46_quarter_pair": [pair_start, pair_end],
              "motif23_ranked": motif23,
              "regular_meter_controls_ranked": regular_controls,
              "early_motif_pair_scores": motif_pairs,
              "motif_transfer_start_quarter": motif_transition,
              "six_to_fourteen_split_ranked": split_candidates,
              "selected_split_quarter": split,
              "long_four_phase_contrast": four_contrast,
              "six_continuation_contrast": six_contrast,
              "early_short_starts": early_starts,
              "late_short_starts": late_starts,
              "limitation": "candidate grammar and thresholds developed on known material; no calibrated confidence",
              "runner_sha256": digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot = args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__, snapshot/Path(__file__).name)
    (args.output/"evidence.json").write_text(json.dumps(result, indent=2)+"\n")
    print(track_id, "23q", pair_start, pair_end, "split", split,
          "motif switch", motif_transition,
          "23q margin", round(motif23[0]["mean_log_likelihood"]-
                                motif23[1]["mean_log_likelihood"], 6),
          "split margin", round(split_candidates[0]["mean_log_likelihood"]-
                                  split_candidates[1]["mean_log_likelihood"], 6), flush=True)


if __name__ == "__main__":
    main()
