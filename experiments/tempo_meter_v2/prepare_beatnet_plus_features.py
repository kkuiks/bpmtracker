"""Extract BeatNet+'s original 80 ms madmom features for one source WAV.

Run with the isolated Python 3.10 frontend. This never reads a tempo/meter map.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import librosa
import madmom
import soundfile as sf

EXPECTED_COMMIT = "bb90eb0a9065b101a4b4c4cb2b2061950266cb4b"


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio",type=Path,required=True)
    p.add_argument("--upstream",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError("new feature directory required")
    upstream=a.upstream.resolve()
    if subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()!=EXPECTED_COMMIT:
        raise ValueError("BeatNet+ source commit differs")
    info=sf.info(a.audio)
    if not info.format.startswith("WAV") or info.frames<=0:
        raise ValueError("canonical WAV required")
    y,sr=librosa.load(str(a.audio),sr=22050,mono=True)
    if sr!=22050 or abs(len(y)/sr-info.frames/info.samplerate)>.001:
        raise ValueError("source time geometry differs")
    sys.path.insert(0,str(upstream/"src"))
    from BeatNetPlus.log_spect import LOG_SPECT
    extractor=LOG_SPECT(sample_rate=22050,win_length=1764,
                        hop_size=441,n_bands=[24],mode="offline")
    features=np.ascontiguousarray(extractor.process_audio(y).T,dtype="<f4")
    if features.ndim!=2 or features.shape[1]!=288 or not np.isfinite(features).all():
        raise ValueError("BeatNet+ feature geometry differs")
    output=a.output.resolve();output.mkdir(parents=True)
    np.savez_compressed(output/"features.npz",features=features,
                        fps=np.array(50),source_frame_offset=np.array(0))
    source=upstream/"src/BeatNetPlus/log_spect.py"
    meta={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
          "reference_used":False,
          "audio":{"path":str(a.audio.resolve()),"sha256":digest(a.audio),
                   "sample_rate":info.samplerate,"sample_frames":info.frames},
          "frontend":{"upstream_commit":EXPECTED_COMMIT,
                      "log_spect_sha256":digest(source),
                      "python":sys.version.split()[0],"madmom":madmom.__version__,
                      "librosa":librosa.__version__,"numpy":np.__version__,
                      "decoded_sample_rate":sr,"window_samples":1764,
                      "hop_samples":441,"feature_shape":list(features.shape),"fps":50},
          "features":{"path":str(output/"features.npz"),
                      "sha256":digest(output/"features.npz")},
          "runner_sha256":digest(__file__)}
    (output/"metadata.json").write_text(json.dumps(meta,indent=2)+"\n")
    print(features.shape,output/"metadata.json",flush=True)


if __name__=="__main__":main()
