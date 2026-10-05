"""Compare constrained two-short-bar candidates from source-only observations.

This is a diagnostic of acoustic separability, not a general meter decoder.
Neither references nor owner maps are opened by this module.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from .constant_grid import _probability
from .run_constant_grid11 import digest
from .tempo_segments import _sample


def low_frequency_attacks(audio_path: Path, times, *, seconds=16, low=30, high=160,
                          radius=.05):
    info = sf.info(audio_path)
    if not info.format.startswith("WAV") or info.samplerate <= 0:
        raise ValueError("canonical WAV required")
    audio, rate = sf.read(audio_path, frames=min(info.frames, round(seconds*info.samplerate)),
                          dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    size = 2048
    hop = 240
    frames = np.lib.stride_tricks.sliding_window_view(
        np.pad(mono, (size//2, size//2)), size)[::hop]
    frequencies = np.fft.rfftfreq(size, 1/rate)
    band = (frequencies >= low) & (frequencies <= high)
    if not band.any():
        raise ValueError("empty low-frequency band")
    magnitude = np.abs(np.fft.rfft(frames*np.hanning(size), axis=1))
    power = np.log1p(magnitude[:,band]).mean(axis=1)
    flux = np.maximum(np.diff(power, prepend=power[0]), 0)
    frame_times = np.arange(len(flux))*hop/rate
    attacks = []
    for t in times:
        left, right = np.searchsorted(frame_times, (t-radius, t+radius))
        attacks.append(float(np.max(flux[left:right])) if right > left else 0.)
    return np.asarray(attacks), {"sample_rate":rate,"sample_frames":info.frames,
        "analysis_seconds":len(audio)/rate,"fft_size":size,"hop_samples":hop,
        "band_hz":[low,high],"attack_radius_seconds":radius}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument("--drums", type=Path, required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--final0-logits", type=Path, required=True)
    parser.add_argument("--final1-logits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("output must be new")
    grid = json.loads(args.grid.read_text())
    if grid["map"]["source"]["sha256"] != digest(args.mix):
        raise ValueError("grid and mix source differ")
    times = np.asarray(grid["beat_times_seconds"][:44], dtype=float)
    if len(times) < 44 or np.any(np.diff(times) <= 0):
        raise ValueError("44 ordered quarter beats required")
    probabilities = {}
    for name, path in (("final0",args.final0_logits),("final1",args.final1_logits)):
        with np.load(path) as values:
            fps = float(values["fps"])
            probabilities[name] = _sample(_probability(values["downbeat"]), fps, times)
    mix, mix_geometry = low_frequency_attacks(args.mix, times)
    drums, drum_geometry = low_frequency_attacks(args.drums, times)
    if (mix_geometry["sample_rate"],mix_geometry["sample_frames"]) != (
            drum_geometry["sample_rate"],drum_geometry["sample_frames"]):
        raise ValueError("derived drums must share the canonical source sample clock")
    views = {**probabilities,"mix_30_160hz":mix,"drums_30_160hz":drums}
    rows = []
    for first_short in range(1,7):
        starts = [0]
        position = 0
        for bar in range(11):
            position += 3 if bar in (first_short,first_short+4) else 4
            starts.append(position)
        indices = np.asarray([i for i in starts if i < len(times)],dtype=int)
        rows.append({"first_short_bar_index":first_short,
                     "second_short_bar_index":first_short+4,
                     "candidate_bar_start_pulse_indices":indices.tolist(),
                     "mean_evidence":{name:float(value[indices].mean())
                                      for name,value in views.items()}})
    rankings = {name:[row["first_short_bar_index"] for row in sorted(
                    rows,key=lambda row:-row["mean_evidence"][name])]
                for name in views}
    args.output.mkdir(parents=True)
    snapshot = args.output / "source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    result = {"schema_version":1,"source_only":True,"reference_read":False,
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "input_sha256":{name:digest(path) for name,path in (
            ("mix",args.mix),("drums",args.drums),("grid",args.grid),
            ("final0_logits",args.final0_logits),("final1_logits",args.final1_logits))},
        "input_paths":{name:str(path.resolve()) for name,path in (
            ("mix",args.mix),("drums",args.drums),("grid",args.grid),
            ("final0_logits",args.final0_logits),("final1_logits",args.final1_logits))},
        "feature_geometry":{"mix":mix_geometry,"drums":drum_geometry},
        "vocabulary":"two 3/4 bars four bar indices apart among otherwise 4/4 bars; first_short_bar_index 1..6; first grid beat is bar zero",
        "selection_policy":"none; diagnostics only",
        "candidate_scores":rows,"rankings":rankings,
        "runner_sha256":digest(__file__)}
    (args.output/"candidate-evidence.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(rankings))


if __name__ == "__main__":
    main()
