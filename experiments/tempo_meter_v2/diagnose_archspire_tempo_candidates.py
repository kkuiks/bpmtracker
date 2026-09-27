"""Freeze source-only 190/150/190 tempo candidate rankings from model logits.

The supplied rates and broad windows come from acoustic local-rate proposals.
No approved tempo map or meter reference is opened by this diagnostic.
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
from .tempo_segments import _clock_times, _phase, _sample


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--mix0",type=Path,required=True)
    parser.add_argument("--mix1",type=Path,required=True)
    parser.add_argument("--mix2",type=Path,required=True)
    parser.add_argument("--drums",type=Path,required=True)
    parser.add_argument("--bass",type=Path,required=True)
    parser.add_argument("--other",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError("output must be new")
    info=sf.info(args.source)
    if not info.format.startswith("WAV"):
        raise ValueError("canonical source WAV required")
    duration=info.frames/info.samplerate
    paths={name:getattr(args,name) for name in ("mix0","mix1","mix2","drums","bass","other")}
    observations={}
    for name,path in paths.items():
        with np.load(path) as values:
            beat=values["beat"]
            fps=float(values["fps"])
        if abs(fps-50.)>1e-9 or len(beat)/fps<duration-.03:
            raise ValueError("source-wide 50 FPS logits required")
        observations[name]=(_probability(beat),beat,fps)
    phase=float(np.median([_phase(observations[name][1][:round(140*50)],50.,190.)
                           for name in ("mix0","mix1","mix2")]))
    periods=(60/190.,60/150.)
    pulses=np.arange(1200)
    rows=[]
    names=tuple(observations)
    for first in range(500,565):
        first_time=phase+first*periods[0]
        if not 160<=first_time<=178:continue
        for second in range(first+20,first+61):
            second_time=first_time+(second-first)*periods[1]
            if not 178<=second_time<=197:continue
            times=_clock_times(pulses,(first,second),periods,phase)
            times=times[times<=duration]
            scores={name:float(_sample(prob,fps,times).mean())
                    for name,(prob,_,fps) in observations.items()}
            rows.append({"first_change_pulse":first,"second_change_pulse":second,
                         "first_change_seconds":float(first_time),
                         "second_change_seconds":float(second_time),
                         "quarter_event_count":len(times),"mean_beat_probability":scores})
    if not rows:raise ValueError("no source-rate candidates")
    matrix=np.asarray([[row["mean_beat_probability"][name] for name in names]
                       for row in rows])
    z=(matrix-matrix.mean(axis=0))/(matrix.std(axis=0)+1e-12)
    methods={"mix_three_mean":matrix[:,:3].mean(axis=1),
             "six_source_raw_mean":matrix.mean(axis=1),
             "six_source_z_mean":z.mean(axis=1),
             "drums":matrix[:,3],"bass":matrix[:,4],"other":matrix[:,5]}
    rankings={name:[int(i) for i in np.argsort(-score)]
              for name,score in methods.items()}
    result={"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_only":True,"reference_read":False,
            "source":{"path":str(args.source.resolve()),"sha256":digest(args.source),
                      "sample_rate":info.samplerate,"sample_frames":info.frames},
            "logits":{name:{"path":str(path.resolve()),"sha256":digest(path)}
                      for name,path in paths.items()},
            "base_bpm":190.,"alternate_bpm":150.,"phase_seconds":phase,
            "first_change_search_seconds":[160.,178.],
            "second_change_search_seconds":[178.,197.],
            "minimum_segment_quarters":20,"maximum_segment_quarters":60,
            "candidate_count":len(rows),"candidates":rows,
            "rankings":rankings,"selection_policy":"diagnostic only; no map selected",
            "runner_sha256":digest(__file__)}
    args.output.mkdir(parents=True)
    snapshot=args.output/"source-snapshot"
    snapshot.mkdir()
    shutil.copy2(__file__,snapshot/Path(__file__).name)
    (args.output/"candidate-evidence.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    for name,order in rankings.items():
        print(name,[(rows[i]["first_change_pulse"],rows[i]["second_change_pulse"])
                    for i in order[:3]],flush=True)


if __name__=="__main__":main()
