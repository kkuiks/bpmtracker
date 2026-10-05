"""Train a small supervised downbeat observation on other reviewed songs.

The held-out song's accepted map is never opened by this runner. This is a
cross-song diagnostic, not a complete BPM/meter map or an adopted model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np

from .constant_grid import _probability
from .run_constant_grid11 import digest, read_bound, save
from .tempo_segments import _sample


def design(features, model_downbeats):
    vector = np.asarray(features, dtype=float)
    p = np.asarray(model_downbeats, dtype=float)
    if (vector.ndim != 2 or len(vector) != len(p) or len(p) < 20 or
            not np.isfinite(vector).all() or not np.isfinite(p).all()):
        raise ValueError("finite beat-synchronous spectral and downbeat features required")
    median = np.median(vector, axis=0)
    scale = np.median(np.abs(vector-median), axis=0)*1.4826
    z = np.clip((vector-median)/np.maximum(scale, .05), -5, 5)
    before = z[np.maximum(np.arange(len(z))-1, 0)]
    after = z[np.minimum(np.arange(len(z))+1, len(z)-1)]
    norm = z/(np.linalg.norm(z, axis=1, keepdims=True)+1e-8)
    novelty = np.zeros((len(z), 3))
    for lag in (1, 2, 4):
        previous = norm[np.maximum(np.arange(len(z))-lag, 0)]
        novelty[:, (1,2,4).index(lag)] = 1-(norm*previous).sum(axis=1)
    pulses = np.arange(len(p))
    neural = np.stack([p[np.clip(pulses+d, 0, len(p)-1)]
                       for d in (-2,-1,0,1,2)], axis=1)
    return np.hstack((z, z-before, z-after, novelty, neural)).astype(np.float32)


def label_barlines(times, bars, tolerance=.07):
    bars = np.asarray(bars, dtype=float)
    times = np.asarray(times, dtype=float)
    if len(bars) == 0:
        raise ValueError("training map has no in-source bar starts")
    positions = np.searchsorted(bars, times)
    left = bars[np.clip(positions-1, 0, len(bars)-1)]
    right = bars[np.clip(positions, 0, len(bars)-1)]
    return (np.minimum(np.abs(times-left), np.abs(times-right)) <= tolerance).astype(np.int8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heldout-id", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--prediction-manifest", type=Path, required=True)
    parser.add_argument("--phrase-root", type=Path, required=True)
    parser.add_argument("--final1-manifest", type=Path, required=True)
    parser.add_argument("--deps-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    sys.path.append(str(args.deps_root.resolve()))
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    catalog = json.loads(args.catalog.read_text())
    predictions = json.loads(args.prediction_manifest.read_text())
    observed = json.loads(args.final1_manifest.read_text())
    if (catalog.get("track_count") != 11 or not predictions.get("complete") or
            predictions.get("references_available_to_runner") is not False or
            not observed.get("complete")):
        raise ValueError("complete eleven-song catalog and source observations required")
    by_id = {x["id"]: x for x in catalog["tracks"]}
    pred_by_id = {x["id"]: x for x in predictions["rows"]}
    obs_by_id = {x["id"]: x for x in observed["rows"]}
    if (set(by_id) != set(pred_by_id) or set(by_id) != set(obs_by_id) or
            args.heldout_id not in by_id):
        raise ValueError("eleven source identities differ")
    x_by_song, y_by_song, p_by_song = {}, {}, {}
    input_rows = []
    for track_id in sorted(by_id):
        record = json.loads((args.phrase_root/track_id/"manifest.json").read_text())
        if record.get("reference_used") is not False:
            raise ValueError("audio features must be source-only")
        source = pred_by_id[track_id]["source"]
        if not (source["sha256"] == record["audio"]["sha256"] ==
                obs_by_id[track_id]["source"]["sha256"]):
            raise ValueError("source WAV identity mismatch")
        feature_path = read_bound(record["features"])
        logit_path = read_bound(obs_by_id[track_id]["observations"][0]["logits"])
        with np.load(feature_path) as feature, np.load(logit_path) as logit:
            vector = feature["vectors"]
            grid = feature["beat_times_seconds"]
            n = min(len(vector), len(grid))
            grid = np.asarray(grid[:n], dtype=float)
            p = _sample(_probability(logit["downbeat"]), float(logit["fps"]), grid)
            x = design(vector[:n], p)
        item = {"id": track_id, "source_sha256": source["sha256"],
                "feature_sha256": digest(feature_path),
                "final1_logits_sha256": digest(logit_path),
                "beats": len(grid), "heldout": track_id == args.heldout_id}
        if track_id == args.heldout_id:
            # No read of by_id[track_id]['accepted_tempo_map'] here or later.
            heldout = {"id": track_id, "grid": grid, "x": x, "p": p}
        else:
            ref_binding = by_id[track_id]["accepted_tempo_map"]
            reference = json.loads(read_bound(ref_binding).read_text())
            bars = reference["downbeats_seconds"]
            y = label_barlines(grid, bars)
            first_change = next((e["time_seconds"] for e in reference["tempo_events"][1:]
                                 if e["time_seconds"] > 0), None)
            if first_change is not None:
                mask = grid < first_change-1.
                x, y, p = x[mask], y[mask], p[mask]
            if len(y) < 30 or y.sum() < 4:
                raise ValueError("insufficient safe training observations")
            x_by_song[track_id], y_by_song[track_id], p_by_song[track_id] = x,y,p
            item.update({"training_map_sha256": ref_binding["sha256"],
                         "training_beats": len(y), "training_barlines": int(y.sum()),
                         "first_tempo_change_cut_seconds": first_change})
        input_rows.append(item)
    candidate_C = (.1, 1., 10.)
    thresholds = (.4,.5,.6,.7)
    folds = {}
    for C in candidate_C:
        rows = []
        for validation in sorted(x_by_song):
            xtrain = np.vstack([x for name,x in x_by_song.items() if name != validation])
            ytrain = np.concatenate([y for name,y in y_by_song.items() if name != validation])
            model = make_pipeline(StandardScaler(), LogisticRegression(
                C=C, class_weight="balanced", max_iter=1000, random_state=0))
            model.fit(xtrain,ytrain)
            pred = model.predict_proba(x_by_song[validation])[:,1]
            rows.append({"id": validation,
                "f1_by_threshold": {str(t):float(f1_score(y_by_song[validation], pred>=t))
                                    for t in thresholds},
                "raw_final1_f1_by_threshold": {str(t):float(f1_score(
                    y_by_song[validation],p_by_song[validation]>=t))
                    for t in thresholds}})
        folds[str(C)] = rows
    rankings = []
    for C in candidate_C:
        for threshold in thresholds:
            score = float(np.mean([r["f1_by_threshold"][str(threshold)]
                                   for r in folds[str(C)]]))
            rankings.append((score,C,threshold))
    rankings.sort(key=lambda x:(-x[0],x[1],x[2]))
    cv_f1,C,threshold = rankings[0]
    final = make_pipeline(StandardScaler(), LogisticRegression(
        C=C, class_weight="balanced", max_iter=1000, random_state=0))
    final.fit(np.vstack(list(x_by_song.values())),np.concatenate(list(y_by_song.values())))
    heldout_p = final.predict_proba(heldout["x"])[:,1]
    output = args.output.resolve();output.mkdir(parents=True)
    snapshot = output/"source-snapshot";snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    np.savez_compressed(output/"heldout-prediction.npz",
                        quarter_times_seconds=heldout["grid"],
                        downbeat_probability=heldout_p,
                        frozen_threshold=np.array(threshold),
                        original_final1_probability=heldout["p"])
    report = {"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "heldout_song_id":args.heldout_id,
        "heldout_reference_read":False,
        "scope":"cross-song beat-synchronous downbeat observation, not a full meter map",
        "catalog_sha256":digest(args.catalog),
        "prediction_manifest_sha256":digest(args.prediction_manifest),
        "final1_manifest_sha256":digest(args.final1_manifest),
        "training_inputs":input_rows,
        "model":"StandardScaler plus class-balanced L2 LogisticRegression",
        "feature":"per-source robust log-spectrum, adjacent differences, cosine novelty, final1 downbeat local context",
        "hyperparameters_selected_by_group_cv":{"C":C,"threshold":threshold,
            "macro_song_f1":cv_f1,"candidate_C":candidate_C,"candidate_thresholds":thresholds,
            "all_cv_rankings":[{"macro_f1":a,"C":b,"threshold":c} for a,b,c in rankings]},
        "group_cv_folds":folds,
        "heldout_prediction_sha256":digest(output/"heldout-prediction.npz"),
        "runner_sha256":digest(__file__),"sklearn_version":sklearn.__version__}
    save(output/"manifest.json",report)
    print('heldout',args.heldout_id,'training songs',len(x_by_song),
          'CV F1',round(cv_f1,4),'C',C,'threshold',threshold,
          'prediction quarters',len(heldout_p))


if __name__ == "__main__":main()
