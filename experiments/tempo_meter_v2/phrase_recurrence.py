"""Source-only beat-synchronous audio self-similarity for recurring bar patterns.

This experiment proposes phrase lengths, not meter labels or accepted maps.
Reference annotations are never opened by this module.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr


ANALYSIS_RATE = 22050
FFT_SIZE = 4096
HOP_SAMPLES = 512
BAND_EDGES_HZ = np.geomspace(70, 9000, 49)
LAGS = tuple(range(10, 33))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def beat_synchronous_bands(audio_path, beat_grid):
    info = sf.info(audio_path)
    if not info.format.startswith("WAV") or info.frames <= 0:
        raise ValueError("canonical source WAV required")
    audio, rate = sf.read(audio_path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != ANALYSIS_RATE:
        mono = soxr.resample(mono, rate, ANALYSIS_RATE)
    padded = np.pad(mono, (FFT_SIZE//2, FFT_SIZE//2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, FFT_SIZE)[::HOP_SAMPLES]
    freq = np.fft.rfftfreq(FFT_SIZE, 1/ANALYSIS_RATE)
    masks = [(freq>=a)&(freq<b) for a,b in zip(BAND_EDGES_HZ[:-1],BAND_EDGES_HZ[1:])]
    bands = np.empty((len(frames), len(masks)), dtype="float32")
    window = np.hanning(FFT_SIZE).astype("float32")
    for begin in range(0, len(frames), 512):
        end = min(begin+512, len(frames))
        spectrum = np.log1p(np.abs(np.fft.rfft(frames[begin:end]*window, axis=1)))
        for col, mask in enumerate(masks):
            bands[begin:end,col] = spectrum[:,mask].mean(axis=1) if mask.any() else 0
    frame_times = np.arange(len(bands))*HOP_SAMPLES/ANALYSIS_RATE
    grid = np.asarray(beat_grid, dtype="float64")
    if (grid.ndim != 1 or len(grid) < 80 or np.any(np.diff(grid)<=0) or
            not np.isfinite(grid).all() or grid[0]<0 or grid[-1]>info.frames/info.samplerate+.001):
        raise ValueError("finite complete source-time beat grid required")
    vectors = []
    for start,stop in zip(grid,grid[1:]):
        left = np.searchsorted(frame_times,start+.03)
        right = np.searchsorted(frame_times,stop-.03)
        if right<=left:
            raise ValueError("beat interval too short for spectral evidence")
        vectors.append(bands[left:right].mean(axis=0))
    vectors = np.asarray(vectors,dtype="float64")
    vectors = (vectors-vectors.mean(axis=0))/(vectors.std(axis=0)+.05)
    vectors /= np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
    return vectors.astype("float32"), {"source_sample_rate": info.samplerate,
        "source_frames": info.frames, "analysis_sample_rate": ANALYSIS_RATE,
        "fft_size": FFT_SIZE, "hop_samples": HOP_SAMPLES,
        "band_edges_hz": BAND_EDGES_HZ.tolist(),
        "beat_intervals": len(vectors)}


def phrase_scores(vectors, lags=LAGS):
    """Average beat-synchronous cosine similarity over adjacent phrases."""
    vectors = np.asarray(vectors,dtype="float32")
    if vectors.ndim != 2 or not np.isfinite(vectors).all():
        raise ValueError("finite two-dimensional feature sequence required")
    scores = {}
    for lag in lags:
        if lag < 2 or 2*lag>len(vectors):
            continue
        adjacent = np.sum(vectors[:-lag]*vectors[lag:],axis=1)
        # score[start] compares beat starts [start,start+lag) and
        # [start+lag,start+2*lag) without shifting time or annotations.
        cumulative = np.r_[0,np.cumsum(adjacent,dtype="float64")]
        scores[lag] = ((cumulative[lag:]-cumulative[:-lag])/lag).astype("float32")
    return scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio",type=Path,required=True)
    parser.add_argument("--constant-grid",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("phrase output must be new")
    grid = json.loads(args.constant_grid.read_text())
    audio_hash = digest(args.audio)
    if grid["map"]["source"]["sha256"] != audio_hash:
        raise ValueError("grid and audio source hashes differ")
    vectors, geometry = beat_synchronous_bands(args.audio,grid["beat_times_seconds"])
    scores = phrase_scores(vectors)
    args.output.mkdir(parents=True)
    array_path=args.output/"scores.npz"
    np.savez_compressed(array_path,vectors=vectors,
                        beat_times_seconds=np.asarray(grid["beat_times_seconds"]),
                        **{f"lag{lag}":value for lag,value in scores.items()})
    summary={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "reference_used":False,"audio":{"path":str(args.audio.resolve()),"sha256":audio_hash},
        "constant_grid":{"path":str(args.constant_grid.resolve()),
                         "sha256":digest(args.constant_grid)},
        "geometry":geometry,"lag_quarters":list(scores),
        "score_definition":"mean cosine of aligned beat-synchronous log-spectral vectors over two adjacent lag-length phrases",
        "features":{"path":str(array_path.resolve()),"sha256":digest(array_path)},
        "runner_sha256":digest(Path(__file__))}
    (args.output/"manifest.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({"beat_intervals":len(vectors),"lags":len(scores),
                      "output":str(args.output/"manifest.json")}),flush=True)


if __name__=="__main__":
    main()
