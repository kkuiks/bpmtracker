"""Generate a deterministic, original drum/bass fixture with exact clock labels.

This tests plumbing and controlled failures, not performance on recorded music.
Tempo is in quarter notes per minute; each generated bar declares its numerator.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from inspect_inputs import sha256


def generate(style, sample_rate=22050):
    if style not in ("eighths", "sixteenths"):
        raise ValueError("unknown groove style")
    rng = np.random.default_rng(824)
    sections = [(205., 4, 16), (210., 3, 12), (205., 4, 16)]
    event_specs, beats, downbeats, meter_events, tempo_events = [], [], [], [], []
    time = 2.
    for tempo, numerator, bars in sections:
        tempo_events.append({"time_seconds": time, "bpm_quarter": tempo})
        meter_events.append({"time_seconds": time, "numerator": numerator, "denominator": 4})
        interval = 60/tempo
        for bar in range(bars):
            downbeats.append(time)
            root_frequency = [82.4069, 65.4064, 73.4162, 61.7354][(bar//4)%4]
            for pulse in range(numerator):
                beats.append(time)
                event_specs.append((time, "kick" if pulse%2 == 0 else "snare", root_frequency))
                event_specs.append((time, "bass", root_frequency))
                subdivisions = 2 if style == "eighths" else 4
                for division in range(subdivisions):
                    event_specs.append((time+division*interval/subdivisions, "hat", root_frequency))
                time += interval
    duration = time+2.5
    audio = np.zeros(round(duration*sample_rate), dtype=np.float64)
    for event, instrument, frequency in event_specs:
        length = .22 if instrument in ("kick", "bass") else .13 if instrument == "snare" else .025
        t = np.arange(round(length*sample_rate))/sample_rate
        if instrument == "kick":
            phase = 2*np.pi*(45*t + 80*.025*(1-np.exp(-t/.025)))
            sound = .65*np.sin(phase)*np.exp(-t*22)
        elif instrument == "snare":
            noise = rng.normal(0, 1, len(t)+1)
            sound = (.20*np.diff(noise)+.18*np.sin(2*np.pi*180*t))*np.exp(-t*35)
        elif instrument == "hat":
            noise = rng.normal(0, 1, len(t)+1)
            sound = .065*np.diff(noise)*np.exp(-t*180)
        else:
            sound = .16*(np.sin(2*np.pi*frequency*t)+.25*np.sin(4*np.pi*frequency*t))*np.exp(-t*9)*np.minimum(1,t*1000)
        start = round(event*sample_rate)
        audio[start:start+len(sound)] += sound
    gain = min(1., .95/np.max(np.abs(audio)))
    audio *= gain
    quantize = lambda values: (np.rint(np.asarray(values)*sample_rate)/sample_rate).tolist()
    return audio.astype(np.float32), {"scope": "synthetic only; no real-song accuracy claim", "style": style,
                                      "sample_rate": sample_rate, "sample_frames": len(audio), "master_gain": gain,
                                      "beats_seconds": quantize(beats), "downbeats_seconds": quantize(downbeats),
                                      "tempo_events": tempo_events, "meter_events": meter_events,
                                      "first_event_sample": round(2*sample_rate), "generator_seed": 824}


def event_metrics(reference, estimated, tolerance):
    reference, estimated = np.asarray(reference), np.asarray(estimated)
    i = j = 0
    errors = []
    while i < len(reference) and j < len(estimated):
        delta = estimated[j]-reference[i]
        if abs(delta) <= tolerance:
            errors.append(delta)
            i += 1
            j += 1
        elif delta < 0:
            j += 1
        else:
            i += 1
    precision = len(errors)/len(estimated) if len(estimated) else 0.
    recall = len(errors)/len(reference) if len(reference) else 0.
    return {"tolerance_seconds": tolerance, "reference_count": len(reference), "estimated_count": len(estimated),
            "matched_count": len(errors), "precision": precision, "recall": recall,
            "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.,
            "matched_absolute_error_ms_p50_p95": (1000*np.quantile(np.abs(errors), [.5,.95])).tolist() if errors else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", choices=["eighths", "sixteenths"], default="eighths")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory must be new")
    audio, report = generate(args.style)
    args.output_dir.mkdir(parents=True)
    sf.write(args.output_dir / "audio.wav", audio, report["sample_rate"], subtype="FLOAT")
    report["audio_sha256"] = sha256(args.output_dir / "audio.wav")
    report["generator_sha256"] = sha256(__file__)
    (args.output_dir / "truth.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(f"{args.style}: {len(audio)/report['sample_rate']:.3f}s, {len(report['beats_seconds'])} beats")


if __name__ == "__main__":
    main()
