"""Score beat/downbeat events only against exact generated-fixture labels."""

import argparse
import json
from pathlib import Path

from inspect_inputs import sha256
from run_beat_this import validate_events
from synthetic_groove import event_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="inference result.json carrying audio provenance")
    parser.add_argument("--decoded", type=Path, required=True, help="decoder comparison.json carrying audio provenance")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new")
    truth = json.loads(args.truth.read_text())
    baseline = json.loads(args.baseline.read_text())
    decoded = json.loads(args.decoded.read_text())
    if truth.get("generator_seed") is None:
        parser.error("this scorer is restricted to explicitly generated fixtures")
    if baseline["audio"]["sha256"] != truth["audio_sha256"] or decoded["audio"]["sha256"] != truth["audio_sha256"]:
        parser.error("predictions and truth must refer to the identical source audio")
    if baseline["audio"]["source_frame_offset"] != 0 or baseline["audio"]["analyzed_frames"] != truth["sample_frames"]:
        parser.error("predictions must cover the full fixture from its original time zero")
    report = {"scope": "known generated-fixture labels only; no generalization claim",
              "truth_sha256": sha256(args.truth), "baseline_sha256": sha256(args.baseline),
              "decoded_sha256": sha256(args.decoded), "scorer_sha256": sha256(__file__),
              "octave_tolerance": False, "variants": {}}
    for name, prediction in decoded["variants"].items():
        scores = {}
        for key in ("beats_seconds", "downbeats_seconds"):
            reference = validate_events(truth[key])
            estimated = validate_events(prediction[key])
            scores[key] = [event_metrics(reference, estimated, tolerance) for tolerance in (.02, .07)]
        report["variants"][name] = scores
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
