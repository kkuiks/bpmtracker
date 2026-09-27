"""Plot baseline evidence without modifying its beat sequence or tempo level."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from run_beat_this import span_pulse_rate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--reference-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new")
    result = json.loads(args.result.read_text())
    duration = result["audio"]["duration_seconds"]
    times, rates = span_pulse_rate(result["beats_seconds"])
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    axes[0].plot(times, rates, color="#176c9c", linewidth=1.1, label="Predicted pulse rate (16-interval span)")
    if args.reference_report:
        reference = json.loads(args.reference_report.read_text())["reference"]
        events = reference["events"]
        x = [float(event["time_seconds"]) for event in events]
        y = [float(event["bpm"]) for event in events]
        if x[-1] <= duration:
            x.append(duration)
            y.append(y[-1])
        axes[0].step(x, y, where="post", color="#ce7329", linestyle="--", label="Historical tempo reference (audio origin unverified)")
    axes[0].set(xlim=(0, duration), ylabel="Pulses / minute", xlabel="Source time (seconds)")
    axes[0].legend(loc="best", fontsize=9)
    axes[0].grid(alpha=0.25)
    logits = np.load(args.result.parent / "logits.npz")
    stop = min(len(logits["beat"]), 15 * int(logits["fps"]))
    x = np.arange(stop) / int(logits["fps"])
    for name, color in [("beat", "#176c9c"), ("downbeat", "#bb4160")]:
        probability = 1 / (1 + np.exp(-np.clip(logits[name][:stop], -80, 80)))
        axes[1].plot(x, probability, color=color, label=f"{name} activation", linewidth=1)
    axes[1].set(xlim=(0, min(15, duration)), ylim=(-0.02, 1.02), ylabel="Activation (not calibrated confidence)", xlabel="Source time (seconds)")
    axes[1].legend(loc="best", fontsize=9)
    axes[1].grid(alpha=0.25)
    fig.suptitle("Official Beat This baseline — no octave correction or tempo-map fitting", fontsize=13)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)
    print(args.output)


if __name__ == "__main__":
    main()
