"""Run unchanged v2 reconstruction on the same fresh observation cache."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from beat_this.model.postprocessor import Postprocessor
from experiments.tempo_meter_v2.constant_grid import infer_constant_map
from experiments.tempo_meter_v2.tempo_segments import infer_tempo_segments
from experiments.tempo_meter_v2.barwise_tempo import propose_barwise_tempo
from experiments.tempo_meter_v2.compound_meter import propose_compound_6_8
from experiments.tempo_meter_v2.tail_support import propose_tail_stop
from experiments.tempo_meter_v2.plausible_bpm import snap_prediction
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    source=json.loads(a.manifest.read_text());rows=[];a.output.mkdir(parents=True)
    for i,row in enumerate(source['rows']):
        with np.load(a.cache_root/(row['source']['sha256']+'.npz')) as z:beat,down=z['logits'].T
        beats,bars=Postprocessor(type='minimal',fps=50)(torch.from_numpy(beat),torch.from_numpy(down))
        constant=infer_constant_map(beat,down,50,bars,row['source'])
        bounded=infer_tempo_segments(constant,beat,down,50,beats)
        barwise,decision=propose_barwise_tempo(constant,beats,bars)
        compound,other=propose_compound_6_8(constant,beats)
        chosen=bounded if bounded['diagnostics']['tempo_segments']['accepted'] else barwise if decision['accepted'] else compound if other['accepted'] else constant
        selected,tail=propose_tail_stop(chosen,constant,beats,bars);selected,snap=snap_prediction(selected)
        path=a.output/f'{i:02d}.json';path.write_text(json.dumps(selected,indent=2,allow_nan=False)+'\n')
        rows.append(dict(id=row['id'],title=row['title'],source=row['source'],selected=dict(path=str(path.resolve()),sha256=digest(path))))
        print('v2-control',row['id'],flush=True)
    (a.output/'manifest.json').write_text(json.dumps(dict(complete=True,references_available_to_runner=False,
        condition='unchanged_v2_reconstruction_on_fresh_v3_acoustic_observations_not_frozen13_rescore',rows=rows),indent=2)+'\n')

if __name__=='__main__':main()
