"""Run the conservative repeated short-bar pilot on eleven source-only inputs.

All accepted maps remain inaccessible here. Existing source-only predictions
are reused unchanged when the acoustic gate abstains.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np

from .phrase_meter import phrase15_trigger, propose_repeated_short_bars
from .run_constant_grid11 import digest, read_bound, save


def _rows_by_id(manifest):
    if not manifest.get("complete") or manifest.get("references_available_to_runner") is not False:
        raise ValueError("complete source-only manifest required")
    rows = {row["id"]: row for row in manifest["rows"]}
    if len(rows) != len(manifest["rows"]):
        raise ValueError("duplicate track identity")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-manifest", type=Path, required=True)
    parser.add_argument("--final1-map-manifest", type=Path, required=True)
    parser.add_argument("--final1-observation-manifest", type=Path, required=True)
    parser.add_argument("--phrase-root", type=Path, required=True)
    parser.add_argument("--derived-stem-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("prediction output must be new")
    selected_path = args.selected_manifest.resolve()
    final1_path = args.final1_map_manifest.resolve()
    observation_path = args.final1_observation_manifest.resolve()
    stem_path = args.derived_stem_manifest.resolve()
    selected = json.loads(selected_path.read_text())
    alt_maps = json.loads(final1_path.read_text())
    observations = json.loads(observation_path.read_text())
    stems = json.loads(stem_path.read_text())
    selected_rows = _rows_by_id(selected)
    alt_rows = _rows_by_id(alt_maps)
    obs_rows = _rows_by_id(observations)
    if set(selected_rows) != set(alt_rows) or set(selected_rows) != set(obs_rows):
        raise ValueError("model and selected track identities differ")
    if len(selected_rows) != 11:
        raise ValueError("eleven source-only tracks required")
    if stems.get("scope", "").startswith("reference"):
        raise ValueError("source-derived stems required")
    output.mkdir(parents=True)
    snapshot = output / "source-snapshot"
    snapshot.mkdir()
    implementations = ("run_phrase_meter11.py", "phrase_meter.py",
                       "diagnose_short_bar_candidates.py")
    for name in implementations:
        shutil.copy2(Path(__file__).with_name(name), snapshot/name)
    ledger = {"schema_version":1,"complete":False,
              "references_available_to_runner":False,
              "input_manifest_sha256":{
                  "selected":digest(selected_path),"final1_maps":digest(final1_path),
                  "final1_observations":digest(observation_path),
                  "derived_stems":digest(stem_path)},
              "implementation_sha256":{name:digest(snapshot/name) for name in implementations},
              "started_at_utc":datetime.now(timezone.utc).isoformat(),"rows":[]}
    for track_id, row in selected_rows.items():
        source = row["source"]
        phrase_path = args.phrase_root / track_id / "manifest.json"
        phrase_manifest = json.loads(phrase_path.read_text())
        if (phrase_manifest.get("reference_used") is not False or
                phrase_manifest["audio"]["sha256"] != source["sha256"]):
            raise ValueError("phrase feature source or provenance differs")
        score_path = read_bound(phrase_manifest["features"])
        with np.load(score_path) as values:
            phrase_scores = {key:values[key] for key in ("lag14","lag15","lag16")}
        active, phrase = phrase15_trigger(phrase_scores)
        prediction = row["prediction"]
        decision = {"triggered":active,"phrase":phrase,"accepted":False,
                    "reason":"no_distinct_fifteen_quarter_phrase"}
        if active:
            if stems["source"]["sha256"] != source["sha256"]:
                decision["reason"] = "source_derived_stems_unavailable"
            else:
                model_row = alt_rows[track_id]
                observation = obs_rows[track_id]
                if (model_row["checkpoint"] != "final1" or
                        len(observation["observations"]) != 1 or
                        observation["observations"][0]["checkpoint"] != "final1" or
                        model_row["source"] != source or observation["source"] != source):
                    raise ValueError("final1 source or checkpoint differs")
                final1 = json.loads(read_bound(model_row["segmented"]).read_text())
                logit_binding = observation["observations"][0]["logits"]
                with np.load(read_bound(logit_binding)) as values:
                    downbeat, fps = values["downbeat"], float(values["fps"])
                mix = read_bound(observation["audio"])
                source_paths = {"mix":mix}
                for stem in stems["stems"]:
                    if stem["stem"] in ("drums","bass","other"):
                        if (stem["sample_rate"] != source["sample_rate"] or
                                stem["sample_frames"] != source["sample_frames"]):
                            raise ValueError("derived stem sample clock differs")
                        source_paths[stem["stem"]] = read_bound(stem)
                if set(source_paths) != {"mix","drums","bass","other"}:
                    raise ValueError("three derived instrumental families required")
                candidate, decision = propose_repeated_short_bars(
                    final1,downbeat,fps,phrase_scores,source_paths)
                if candidate is not None:
                    prediction = save(output/"predictions"/(track_id+".json"),candidate)
        ledger["rows"].append({"id":track_id,"source":source,
                               "prediction":prediction,
                               "selected_input":row["prediction"],
                               "phrase_manifest_sha256":digest(phrase_path),
                               "decision":decision})
        print(track_id,"trigger",active,"accepted",decision["accepted"],
              "reason",decision["reason"],flush=True)
        save(output/"prediction-manifest.json",ledger)
    ledger["complete"] = len(ledger["rows"]) == 11
    ledger["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output/"prediction-manifest.json",ledger)


if __name__ == "__main__":
    main()
