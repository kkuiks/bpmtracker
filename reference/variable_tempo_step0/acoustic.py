"""Source-only strict digital-silence information; raw sensor logits stay intact."""

from __future__ import annotations

import argparse
from pathlib import Path
from tools.project_storage import resolve_path

import numpy as np
import soundfile as sf

from .common import read_json, write_json


def zero_frames(signal, rate, fps, frame_count):
    """A whole frame must contain exactly zero PCM on every channel."""
    hop = rate / fps
    silent = np.zeros(frame_count, dtype=bool)
    if hop.is_integer():
        hop = int(hop)
        complete = min(frame_count, len(signal) // hop)
        silent[:complete] = np.all(signal[:complete * hop].reshape(complete, hop, -1) == 0, axis=(1, 2))
        for frame in range(complete, frame_count):
            chunk = signal[frame * hop:(frame + 1) * hop]
            silent[frame] = len(chunk) == 0 or bool(np.all(chunk == 0))
    else:
        for frame in range(frame_count):
            chunk = signal[round(frame * hop):round((frame + 1) * hop)]
            silent[frame] = len(chunk) == 0 or bool(np.all(chunk == 0))
    return silent


def silent_intervals(silent, fps, duration):
    start = np.flatnonzero(silent & ~np.r_[False, silent[:-1]])
    end = np.flatnonzero(silent & ~np.r_[silent[1:], False])
    return np.asarray([[a / fps, min((b + 1) / fps, duration)] for a, b in zip(start, end)
                       if a / fps < duration], dtype=float).reshape(-1, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run, output = args.run.resolve(), args.run.resolve() / "acoustic-evidence"
    output.mkdir(exist_ok=False)
    receipt = []
    for source in read_json(run / "source-inputs.json")["samples"]:
        ident = source["id"]
        signal, rate = sf.read(resolve_path(source["audio_path"]), dtype="float32", always_2d=True)
        if rate != source["sample_rate"] or signal.shape != (source["sample_frames"], source["channels"]):
            raise ValueError("Source geometry differs from frozen manifest")
        with np.load(run / "original/evidence" / f"{ident}.npz", allow_pickle=False) as data:
            original = {key: data[key].copy() for key in data.files}
        fps, duration = int(original["fps"]), float(original["duration_seconds"])
        silent = zero_frames(signal, rate, fps, len(original["beat_logits"]))
        intervals = silent_intervals(silent, fps, duration)
        np.savez_compressed(output / f"{ident}.npz", **original, silent_frame_mask=silent,
                            silent_intervals_seconds=intervals)
        receipt.append({"id": ident, "strict_zero_frames": int(silent.sum()),
                        "longest_zero_interval_seconds": max((b - a for a, b in intervals), default=0),
                        "signal_source_only": True, "reference_file_read": False})
        del signal
    write_json(output / "receipt.json", {"rows": receipt, "original_sensor_logits_unchanged": True,
               "reference_fields_used": False, "amplitude_threshold": "exact PCM zero only",
               "not_general_silence_or_percussion_absence_detection": True,
               "normal_inter_beat_gaps_not_forced_unknown": "Only silent runs lasting at least one supplied-clock period force UNKNOWN."})


if __name__ == "__main__":
    main()
