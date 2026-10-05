"""One frozen scoring ablation; original predictions are never overwritten."""

import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil

import numpy as np

from .evaluate import reference_events, score_map
from .infer import make_evidence, optimize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    args = parser.parse_args()
    config = {**json.loads((args.run / "config.json").read_text()), "score_mode": "grid_only"}
    output = args.run / "ablation-grid-only"
    output.mkdir(exist_ok=False)
    shutil.copytree(Path(__file__).parent, output / "source-snapshot", ignore=shutil.ignore_patterns("__pycache__"))
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    source = json.loads((args.run / "inference-manifest.json").read_text())["samples"]
    # Complete all source-only predictions before opening evaluation metadata.
    for index, sample in enumerate(source, 1):
        with np.load(args.evidence / (sample["id"] + ".npz")) as arrays:
            evidence = make_evidence(arrays["beat_logits"], arrays["downbeat_logits"], float(arrays["duration_seconds"]), config)
        prediction = optimize(evidence, config)
        (output / (sample["id"] + ".json")).write_text(json.dumps(prediction, indent=2) + "\n")
        print(f"GRID_ONLY {index}/{len(source)} {sample['id']}", flush=True)
    metadata = json.loads((args.run / "evaluation-manifest.json").read_text())["samples"]
    rows = []
    for meta in metadata:
        prediction = json.loads((output / (meta["id"] + ".json")).read_text())
        reference = json.loads((args.samples_root / meta["reference"]["path"]).read_text())
        beats, downbeats = reference_events(reference, meta["reference_support_seconds"])
        metrics = score_map(prediction, beats, downbeats, meta, config)[0]
        nominal = Fraction(meta["reference_quarter_bpm_values_exact_as_stored"][0]).limit_denominator(config["denominator_max"])
        rows.append({"id": meta["id"], "quarter_bpm": prediction["quarter_bpm"],
                     "nominal_bpm_match": prediction["bpm_fraction"] == {"numerator": nominal.numerator,"denominator": nominal.denominator},
                     "metrics": metrics})
    macro = {channel:{str(int(tol*1000)):sum(r["metrics"][channel]["tolerances_ms"][str(int(tol*1000))]["f1"] for r in rows)/len(rows)
                      for tol in config["evaluation_tolerances_seconds"]}
             for channel in ("quarter_events","downbeat_events")}
    report = {"valid_denominator":len(rows),"diagnostic_only":True,
              "change":"Replace symmetric precision/recall F1 by grid-to-evidence precision only. All other config, evidence and sample membership unchanged.",
              "nominal_bpm_matches":sum(r["nominal_bpm_match"] for r in rows),
              "macro_event_f1_common_denominator":macro,"samples":rows}
    (output/"results.json").write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'}),flush=True)


if __name__ == "__main__":
    main()
