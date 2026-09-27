"""Freeze raw BeatNet+ beat/downbeat probabilities without its meter decoder."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
import torch
import torch.nn.functional as F

EXPECTED_COMMIT = "bb90eb0a9065b101a4b4c4cb2b2061950266cb4b"


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--feature-metadata",type=Path,required=True)
    p.add_argument("--upstream",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cuda")
    a=p.parse_args()
    if a.output.exists():raise FileExistsError("new observation directory required")
    upstream=a.upstream.resolve()
    if subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()!=EXPECTED_COMMIT:
        raise ValueError("BeatNet+ source commit differs")
    meta=json.loads(a.feature_metadata.read_text())
    if meta.get("reference_used") is not False or meta["frontend"]["upstream_commit"]!=EXPECTED_COMMIT:
        raise ValueError("source-only BeatNet+ features required")
    feature=Path(meta["features"]["path"])
    if digest(feature)!=meta["features"]["sha256"]:raise ValueError("feature hash changed")
    with np.load(feature) as arrays:
        x=arrays["features"].astype(np.float32,copy=False)
        fps=int(arrays["fps"])
    if x.ndim!=2 or x.shape[1]!=288 or fps!=50:
        raise ValueError("invalid BeatNet+ frontend geometry")
    if a.device=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    sys.path.insert(0,str(upstream/"src"))
    from BeatNetPlus.model import BeatNetPlusBranch
    device=torch.device(a.device)
    torch.set_num_threads(4)
    output=a.output.resolve();output.mkdir(parents=True)
    snapshot=output/"source-snapshot";snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    models=[]
    for name in ("generic_weights","generic_main_weights"):
        weight=upstream/f"src/BeatNetPlus/models/{name}.pt"
        model=BeatNetPlusBranch(288,150,4,a.device)
        model.load_state_dict(torch.load(weight,map_location=device,weights_only=True),strict=True)
        model.eval()
        with torch.inference_mode():
            logits=model.inference_forward(torch.from_numpy(x).unsqueeze(0).to(device))[0]
            probability=F.softmax(logits,dim=0).cpu().numpy()
        if probability.shape!=(3,len(x)) or not np.isfinite(probability).all() or not np.allclose(probability.sum(axis=0),1,atol=1e-5):
            raise ValueError("invalid BeatNet+ class probabilities")
        path=output/f"{name}.npz"
        np.savez_compressed(path,beat=probability[0],downbeat=probability[1],
                            other=probability[2],fps=np.array(fps))
        models.append({"name":name,"weights_sha256":digest(weight),
                       "probabilities":{"path":str(path),"sha256":digest(path)}})
        print(name,probability.shape,flush=True)
        del model
        if device.type=="cuda":torch.cuda.empty_cache()
    report={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "reference_used":False,"source":meta["audio"],
            "feature_metadata_sha256":digest(a.feature_metadata),
            "upstream_commit":EXPECTED_COMMIT,
            "model_sha256":digest(upstream/"src/BeatNetPlus/model.py"),
            "device":a.device,"torch":torch.__version__,
            "runner_sha256":digest(__file__),"models":models,
            "scope":"raw independent class observations; no meter map"}
    (output/"manifest.json").write_text(json.dumps(report,indent=2)+"\n")


if __name__=="__main__":main()
