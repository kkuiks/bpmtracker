"""Source-only phase ranking for a repeated 22-quarter bar pattern.

This is a bounded transfer diagnostic, not an automatic full-song decoder.
It applies the same three mid-frequency bands and three radii used by the
15-quarter pilot; caller declares a source-observed pulse interval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from .phrase_meter import BANDS_HZ, RADII_SECONDS
from .run_constant_grid11 import digest


def attack_views(path, times, start, end):
    info = sf.info(path)
    if not info.format.startswith("WAV"):
        raise ValueError("canonical WAV required")
    rate = info.samplerate
    left = max(0., float(times[start]-1.))
    right = min(info.frames/rate,float(times[end-1]+1.))
    with sf.SoundFile(path) as audio:
        audio.seek(round(left*rate))
        mono = audio.read(round((right-left)*rate),dtype="float32",always_2d=True).mean(axis=1)
    size,hop = 2048,240
    frames = np.lib.stride_tricks.sliding_window_view(
        np.pad(mono,(size//2,size//2)),size)[::hop]
    window=np.hanning(size).astype("float32")
    freq=np.fft.rfftfreq(size,1/rate)
    masks=[(freq>=a)&(freq<=b) for a,b in BANDS_HZ]
    power=np.empty((len(frames),len(masks)),dtype="float32")
    for begin in range(0,len(frames),512):
        spectrum=np.log1p(np.abs(np.fft.rfft(frames[begin:begin+512]*window,axis=1)))
        for col,mask in enumerate(masks):
            power[begin:begin+512,col]=spectrum[:,mask].mean(axis=1)
    flux=np.maximum(np.diff(power,axis=0,prepend=power[:1]),0)
    frame_times=left+np.arange(len(flux))*hop/rate
    views={}
    for col,band in enumerate(BANDS_HZ):
        for radius in RADII_SECONDS:
            attacks=[]
            for t in times[start:end]:
                lo,hi=np.searchsorted(frame_times,(t-radius,t+radius))
                attacks.append(float(np.max(flux[lo:hi,col])) if hi>lo else 0.)
            views[(band,radius)]=np.asarray(attacks)
    return views,{"sample_rate":rate,"sample_frames":info.frames,
                  "analysis_window_seconds":[left,right],"fft_size":size,"hop_samples":hop}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid",type=Path,required=True)
    parser.add_argument("--stems",type=Path,required=True)
    parser.add_argument("--pulse-start",type=int,required=True)
    parser.add_argument("--pulse-end",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    map_value=json.loads(args.grid.read_text())
    times=np.asarray(map_value["beat_times_seconds"],dtype=float)
    if not 0<=args.pulse_start<args.pulse_end<=len(times):
        raise ValueError("invalid quarter interval")
    manifest=json.loads(args.stems.read_text())
    if manifest.get("reference_read") is not False or manifest["source"]["sha256"]!=map_value["map"]["source"]["sha256"]:
        raise ValueError("source-only derived stems must match grid")
    sources={"mix":manifest["source"]}
    sources.update({row["stem"]:row for row in manifest["stems"] if row["stem"] in ("drums","bass","other")})
    if set(sources)!={"mix","drums","bass","other"}:
        raise ValueError("all source-derived instrument families required")
    pattern=(0,2,6,10,14,18)
    phases=list(range(22))
    indices=[np.asarray([q-args.pulse_start for q in range(args.pulse_start,args.pulse_end)
                         if (q-phase)%22 in pattern],dtype=int) for phase in phases]
    views=[]
    geometry={}
    for stem,binding in sources.items():
        path=Path(binding["path"])
        if digest(path)!=binding["sha256"]:
            raise ValueError("source-derived audio hash changed")
        stem_views,details=attack_views(path,times,args.pulse_start,args.pulse_end)
        if (details["sample_rate"],details["sample_frames"])!=(manifest["source"]["sample_rate"],manifest["source"]["sample_frames"]):
            raise ValueError("derived stem sample clock changed")
        geometry[stem]=details
        for (band,radius),strength in stem_views.items():
            scores=np.asarray([float(strength[idx].mean()) for idx in indices])
            standardized=(scores-scores.mean())/(scores.std()+1e-12)
            views.append({"stem":stem,"band_hz":list(band),"radius_seconds":radius,
                          "scores":scores.tolist(),"standardized":standardized.tolist(),
                          "winner":int(np.argmax(scores))})
    consensus=np.mean([row["standardized"] for row in views],axis=0)
    result={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_only":True,"reference_read":False,"selection_policy":"diagnostic only",
            "input_sha256":{"grid":digest(args.grid),"stem_manifest":digest(args.stems),
                            **{k:v["sha256"] for k,v in sources.items()}},
            "pulse_interval":[args.pulse_start,args.pulse_end],
            "candidate_pattern_quarters":list(pattern),
            "candidate_phase_modulo22":phases,"bands_hz":BANDS_HZ,
            "radii_seconds":RADII_SECONDS,"geometry":geometry,
            "views":views,"view_count":len(views),
            "mean_standardized_scores":consensus.tolist(),
            "phase_ranking":[int(x) for x in np.argsort(-consensus)],
            "runner_sha256":digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot=args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    (args.output/"phase-evidence.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("top phases",result["phase_ranking"][:8],"views",len(views),flush=True)


if __name__=="__main__":main()
