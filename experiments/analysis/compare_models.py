"""Compare saved model seeds and a probability ensemble at identical source time."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
from beat_this.model.postprocessor import Postprocessor

from compare_decoders import diagnostics
from fit_clock import fit_clock
from inspect_inputs import sha256
from legacy_dbn import decode_dbn_from_logits


def aligned_inputs(directories):
    reports = [json.loads((p / "result.json").read_text()) for p in directories]
    arrays = [np.load(p / "logits.npz") for p in directories]
    keys = ("sha256", "source_frame_offset", "analyzed_frames", "sample_rate")
    for report, logits in zip(reports, arrays):
        if any(report["audio"][key] != reports[0]["audio"][key] for key in keys):
            raise ValueError("ensemble inputs must share audio hash, origin, frame count and sample rate")
        if float(logits["fps"]) != float(arrays[0]["fps"]):
            raise ValueError("ensemble frame rates differ")
        for channel in ("beat", "downbeat"):
            if logits[channel].shape != arrays[0]["beat"].shape or not np.isfinite(logits[channel]).all():
                raise ValueError("ensemble arrays must have equal finite shapes")
    return reports, arrays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    reports, arrays = aligned_inputs(args.runs)
    torch.set_num_threads(4)
    fps = float(arrays[0]["fps"])
    duration = reports[0]["audio"]["duration_seconds"]
    variants = [(p.name, a["beat"], a["downbeat"]) for p,a in zip(args.runs, arrays)]
    mean_logits = []
    for channel in ("beat", "downbeat"):
        probs = [1 / (1 + np.exp(-np.clip(a[channel].astype(float), -60, 60))) for a in arrays]
        mean = np.clip(np.mean(probs, axis=0), 1e-7, 1-1e-7)
        mean_logits.append(np.log(mean / (1-mean)).astype(np.float32))
    variants.append(("probability_mean", *mean_logits))
    report = {"audio": reports[0]["audio"], "reference_used": False, "reference_alignment": "unverified",
              "input_runs": [{"name": p.name, "result_sha256": sha256(p / "result.json"),
                              "logits_sha256": sha256(p / "logits.npz")} for p in args.runs],
              "runner_sha256": sha256(__file__), "decoder_sha256": sha256(Path(__file__).with_name("legacy_dbn.py")),
              "fitter_sha256": sha256(Path(__file__).with_name("fit_clock.py")),
              "ensemble_method": "equal arithmetic mean of per-frame sigmoid activations; no reference-based weights",
              "variants": {}}
    args.output_dir.mkdir(parents=True)
    for name, beat, downbeat in variants:
        target = args.output_dir / name
        target.mkdir()
        np.savez_compressed(target / "logits.npz", beat=beat, downbeat=downbeat, fps=np.array(fps))
        minimal_b, minimal_d = Postprocessor(type="minimal", fps=fps)(torch.tensor(beat), torch.tensor(downbeat))
        start = time.perf_counter()
        dbn_b, dbn_d, numbers = decode_dbn_from_logits(beat, downbeat, fps=fps)
        elapsed = time.perf_counter() - start
        proposal = fit_clock(dbn_b)
        minimal = {"audio": reports[0]["audio"], "beats_seconds": minimal_b.tolist(), "downbeats_seconds": minimal_d.tolist(),
                   "diagnostics": diagnostics(minimal_b, minimal_d, duration)}
        dbn = {"audio": reports[0]["audio"], "beats_seconds": dbn_b.tolist(), "downbeats_seconds": dbn_d.tolist(),
               "beat_numbers": numbers.tolist(), "decoding_seconds": elapsed,
               "diagnostics": diagnostics(dbn_b, dbn_d, duration)}
        (target / "minimal.json").write_text(json.dumps(minimal, indent=2) + "\n")
        (target / "dbn.json").write_text(json.dumps(dbn, indent=2) + "\n")
        (target / "clock.json").write_text(json.dumps(proposal, indent=2) + "\n")
        report["variants"][name] = {"minimal": minimal, "dbn": dbn, "clock": proposal}
        print(name, len(minimal_b), len(dbn_b), [round(s["pulse_rate_per_minute"], 4) for s in proposal["segments"]], flush=True)
    (args.output_dir / "comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
