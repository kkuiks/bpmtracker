"""Try phase-switch short bars on eleven frozen, source-only predictions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from .constant_grid import _probability
from .phase_switch_meter import propose_phase_switch_meter, stable_phase_switches
from .run_constant_grid11 import digest, read_bound, save
from .tempo_segments import _sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--final1-manifest", type=Path, required=True)
    parser.add_argument("--final0-logits", type=Path, required=True)
    parser.add_argument("--final0-result", type=Path, required=True)
    parser.add_argument("--allinone-manifest", type=Path, required=True)
    parser.add_argument("--demix-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be a new run")
    incoming = json.loads(args.input_manifest.read_text())
    observations = json.loads(args.final1_manifest.read_text())
    aio = json.loads(args.allinone_manifest.read_text())
    demix = json.loads(args.demix_manifest.read_text())
    if (not incoming.get("complete") or len(incoming.get("rows", [])) != 11 or
            incoming.get("references_available_to_runner") is not False or
            not observations.get("complete") or len(observations.get("rows", [])) != 11 or
            aio.get("reference_read_by_inference") is not False or
            demix.get("reference_read") is not False):
        raise ValueError("complete source-only eleven-song inputs required")
    by_id = {row["id"]: row for row in observations["rows"]}
    if set(by_id) != {row["id"] for row in incoming["rows"]}:
        raise ValueError("observation identities differ from predictions")
    scans = []
    triggered = []
    for row in incoming["rows"]:
        prediction = json.loads(read_bound(row["prediction"]).read_text())
        observation = by_id[row["id"]]
        if (prediction["map"]["source"] != row["source"] or
                observation["source"] != row["source"]):
            raise ValueError("prediction and observation source clocks differ")
        logit_path = read_bound(observation["observations"][0]["logits"])
        with np.load(logit_path) as arrays:
            signal = _sample(_probability(arrays["downbeat"]),
                             float(arrays["fps"]),
                             np.asarray(prediction["beat_times_seconds"]))
        runs, phase = stable_phase_switches(signal)
        scans.append({"id": row["id"], "source_sha256": row["source"]["sha256"],
                      "final1_logits_sha256": digest(logit_path),
                      "phase": phase})
        if runs is not None:
            triggered.append((row, prediction, logit_path))
    if len(triggered) != 1:
        raise ValueError(f"expected one independently triggered song, found {len(triggered)}")
    row, prediction, final1_path = triggered[0]
    if (row["source"]["sha256"] != aio["source"]["sha256"] or
            any(row["source"][key] != demix["source"][key]
                for key in ("sha256", "sample_rate", "sample_frames"))):
        raise ValueError("independent model and stem are not for triggered source")
    final0_result = json.loads(args.final0_result.read_text())
    if (args.final0_result.parent.resolve() != args.final0_logits.parent.resolve() or
            final0_result.get("input_sha256") != row["source"]["sha256"]):
        raise ValueError("final0 logits are not bound to triggered finished mix")
    if not prediction["diagnostics"].get("structural_tempo", {}).get("accepted"):
        raise ValueError("triggered source must have a source-only tempo map")
    drum = next(item for item in demix["stems"] if item["stem"] == "drums")
    drum_path = read_bound(drum)
    with sf.SoundFile(drum_path) as stem:
        if (stem.samplerate, stem.frames) != (row["source"]["sample_rate"],
                                               row["source"]["sample_frames"]):
            raise ValueError("drum stem source clock differs")
    with (np.load(args.final0_logits) as a0,
          np.load(final1_path) as a1,
          np.load(read_bound(aio["output"]["activations"])) as independent):
        result, decision = propose_phase_switch_meter(
            prediction, a0["downbeat"], float(a0["fps"]),
            a1["downbeat"], float(a1["fps"]),
            independent["downbeat"], drum_path)
    if result is None:
        raise ValueError(f"phase-switch proposal abstained: {decision['reason']}")
    output = args.output.resolve(); output.mkdir(parents=True)
    snapshot = output/"source-snapshot"; snapshot.mkdir()
    for path in (Path(__file__), Path(__file__).with_name("phase_switch_meter.py")):
        shutil.copy2(path, snapshot/path.name)
    binding = save(output/"predictions"/(row["id"]+".json"), result)
    ledger = {"schema_version": 1, "complete": True,
              "references_available_to_runner": False,
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "inputs_sha256": {"input_manifest": digest(args.input_manifest),
                  "final1_manifest": digest(args.final1_manifest),
                  "final0_logits": digest(args.final0_logits),
                  "final0_result": digest(args.final0_result),
                  "allinone_manifest": digest(args.allinone_manifest),
                  "demix_manifest": digest(args.demix_manifest),
                  "drum_stem": digest(drum_path)},
              "implementation_sha256": {name: digest(snapshot/name)
                  for name in (Path(__file__).name, "phase_switch_meter.py")},
              "rows": [{"id": original["id"], "source": original["source"],
                        "prediction": binding if original["id"] == row["id"] else original["prediction"],
                        "selected_input": original["prediction"]}
                       for original in incoming["rows"]]}
    save(output/"prediction-manifest.json", ledger)
    save(output/"selection-evidence.json", {"source_only": True, "reference_read": False,
        "all_eleven_phase_scans": scans, "triggered_song": row["id"],
        "decision": decision})
    print(row["id"], "accepted", [(x["start_pulse"], x["split_pulse"],
                                   x["end_pulse"]) for x in decision["transition_decisions"]])


if __name__ == "__main__":
    main()
