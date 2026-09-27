"""Official Beat Transformer demo frontend/DBN in an isolated Spleeter environment.

This reproduces the author's linked Colab, rather than the broken archived
preprocessing.py script. It never uses MIDI/reference stems or shifts time to
match annotations. Provision local Spleeter weights before invoking prepare.
"""

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import time

import numpy as np


FPS = 44100 / 1024


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def prepare(args):
    # CPU separation is deliberate: TensorFlow and PyTorch do not compete for
    # the small GPU, and the source/model outputs remain deterministic float32.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["TF_NUM_INTRAOP_THREADS"] = str(args.threads)
    os.environ["TF_NUM_INTEROP_THREADS"] = "1"
    os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
    os.environ["MODEL_PATH"] = str(args.model_root.resolve())
    import soundfile as sf
    import librosa
    from spleeter.audio import STFTBackend
    from spleeter.separator import Separator

    if args.output.exists():
        raise ValueError("feature output must be new")
    required = args.model_root / "5stems"
    if not (required / "checkpoint").is_file():
        raise ValueError("Spleeter weights must be provisioned locally first")
    info = sf.info(args.audio)
    if not info.format.startswith("WAV"):
        raise ValueError("use a canonical decoded WAV")
    count = info.frames if args.max_seconds is None else min(info.frames, round(args.max_seconds*info.samplerate))
    if count <= 0:
        raise ValueError("audio prefix must be positive")
    # The official demo uses Spleeter's ffmpeg AudioAdapter at 44100 Hz.
    # Decode the canonical WAV through the same adapter; duration is explicit.
    from spleeter.audio.adapter import AudioAdapter
    started = time.perf_counter()
    waveform, sr = AudioAdapter.default().load(
        str(args.audio), sample_rate=44100,
        duration=None if args.max_seconds is None else count/info.samplerate,
    )
    if sr != 44100 or waveform.ndim != 2 or waveform.shape[1] not in (1, 2):
        raise ValueError("unexpected frontend waveform layout")
    if not np.isfinite(waveform).all():
        raise ValueError("non-finite source audio")
    separator = Separator("spleeter:5stems", stft_backend=STFTBackend.LIBROSA, multiprocess=False)
    stems = separator.separate(waveform)
    separated = time.perf_counter()
    # Preserve the official separator order, never substitute original stems.
    expected = {"vocals", "drums", "bass", "piano", "other"}
    if set(stems) != expected or len(stems) != 5:
        raise ValueError("unexpected five-stem separator output")
    mel = librosa.filters.mel(sr=44100, n_fft=4096, n_mels=128, fmin=30, fmax=11000).T
    specs = []
    for name, stem in stems.items():
        # Spleeter legitimately expands mono input to stereo before its five
        # real source estimates. Only the sample count/time origin is shared.
        if stem.ndim != 2 or stem.shape[0] != waveform.shape[0] or stem.shape[1] != 2:
            raise ValueError("separation changed the source sample origin/length")
        spectrum = separator._stft(stem)
        power = np.abs(np.mean(spectrum, axis=-1)) ** 2
        specs.append(np.dot(power, mel))
    x = np.stack(specs).transpose(0, 2, 1)
    x = np.stack([librosa.power_to_db(v, ref=np.max) for v in x]).transpose(0, 2, 1)
    if not np.isfinite(x).all():
        raise ValueError("non-finite mel features")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, features=x.astype(np.float32), fps=np.array(FPS))
    model_files = {p.name: digest(p) for p in sorted(required.iterdir()) if p.is_file()}
    report = {
        "frontend": "official linked Colab Spleeter2.3.2 five-stem waveform + separator._stft + mel power",
        "separation_backend": "official LIBROSA CPU backend, explicit rather than device-dependent AUTO",
        "audio_sha256": digest(args.audio), "source_sample_rate": info.samplerate,
        "source_frames": info.frames, "analyzed_source_frames": count,
        "resampled_frames": len(waveform), "resampled_sample_rate": sr,
        "resampled_input_channels": waveform.shape[1], "separated_stem_channels": 2,
        "source_frame_offset": 0, "frame_time_offset_seconds": 0,
        "frame_time_mapping": "i * 1024 / 44100 seconds, official demo convention; no annotation-derived adjustment",
        "stft": {"frame_length": 4096, "hop_length": 1024, "center": False,
                 "zero_padding_samples_each_side": 4096,
                 "physical_window_center_seconds": "(i * 1024 - 2048) / 44100",
                 "prediction_mapping": "official model output uses i * 1024 / 44100; do not independently undo frontend padding"},
        "fps": FPS, "stem_order": list(stems), "feature_shape": list(x.shape),
        "feature_sha256": digest(args.output), "spleeter_weight_hashes": model_files,
        "versions": {name: metadata.version(name) for name in ("spleeter", "tensorflow", "numpy", "scipy", "librosa", "soundfile")},
        "timing_seconds": {"load_and_separate": separated-started, "mel_features": time.perf_counter()-separated},
        "runner_sha256": digest(__file__), "max_seconds": args.max_seconds,
    }
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"features": str(args.output), "shape": list(x.shape), "timing_seconds": report["timing_seconds"]}), flush=True)


def decode(args):
    from madmom.features.beats import DBNBeatTrackingProcessor
    from madmom.features.downbeats import DBNDownBeatTrackingProcessor
    from scipy.special import expit
    if args.output.exists():
        raise ValueError("decoder output must be new")
    with np.load(args.logits, allow_pickle=False) as value:
        beat, downbeat = expit(value["beat"]), expit(value["downbeat"])
        fps = float(value["fps"])
    if beat.shape != downbeat.shape or beat.ndim != 1 or not np.isfinite(beat).all() or not np.isfinite(downbeat).all():
        raise ValueError("invalid activation arrays")
    config = dict(min_bpm=55., max_bpm=215., fps=fps, transition_lambda=100,
                  observation_lambda=6, num_tempi=None, threshold=.2)
    started = time.perf_counter()
    beats = DBNBeatTrackingProcessor(**config)(beat)
    combined = np.stack([np.maximum(beat-downbeat, 0), downbeat], axis=-1)
    bars = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], **config)(combined)
    args.output.write_text(json.dumps({
        "beats_seconds": beats.tolist(), "downbeats_seconds": bars[bars[:, 1] == 1, 0].tolist(),
        "bar_tracking_pulses": bars.tolist(), "decoder": "official_demo_madmom_separate_beat_and_downbeat_dbns",
        "config": config, "beats_per_bar": [3, 4], "madmom_version": metadata.version("madmom"),
        "elapsed_seconds": time.perf_counter()-started,
    }, indent=2, allow_nan=False)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--max-seconds", type=float)
    p.add_argument("--threads", type=int, default=2)
    d = commands.add_parser("decode")
    d.add_argument("--logits", type=Path, required=True)
    d.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.threads <= 0 or (args.max_seconds is not None and (not np.isfinite(args.max_seconds) or args.max_seconds <= 0)):
            parser.error("threads and duration must be positive")
        prepare(args)
    else:
        decode(args)


if __name__ == "__main__":
    main()
