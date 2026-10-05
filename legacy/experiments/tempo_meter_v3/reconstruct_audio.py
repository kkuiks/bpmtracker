"""Callable new-audio route for the bounded meter-score intervention.

Accepts one mix and optional initial pulse-family hint. No song catalog,
reference map, saved song route or evaluated score is opened here.
"""
import argparse
import json
from pathlib import Path
import sys
from . import analyzer
from .meter_duration import decode_meter
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--initial-bpm',type=float)
    p.add_argument('--acoustic-checkpoint',type=Path,required=True)
    p.add_argument('--structure-checkpoint',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    from experiments.analysis_legacy.music_map_contract import prepare_map,render_bars
    old=analyzer.decode_meter
    analyzer.decode_meter=decode_meter
    try:
        record=analyzer.analyze(a.audio,a.initial_bpm,
            acoustic_checkpoint=a.acoustic_checkpoint,structure_checkpoint=a.structure_checkpoint,
            cache_root=a.cache_root,output=a.output)
    finally:
        analyzer.decode_meter=old
    rejected=[]
    candidates=json.loads((a.output/'candidate-bank.json').read_text())
    for rank,candidate in enumerate(candidates):
        try:
            if render_bars(prepare_map(candidate['prediction']['map']))['status']!='rendered':
                raise ValueError('bar map cannot render')
        except (ValueError,TypeError,KeyError) as error:
            rejected.append(dict(rank=rank,name=candidate['name'],reason=str(error)));continue
        if rank:
            path=a.output/'selected-valid.json';path.write_text(json.dumps(candidate['prediction'],indent=2)+'\n')
            record['unvalidated_selection']=record['selected']
            record['selected']=dict(path=str(path.resolve()),sha256=digest(path))
        record['validity_guard']=dict(selected_rank=rank,rejected_before_selection=rejected)
        break
    else:
        raise ValueError('No valid candidate')
    record['intervention']='robust_duration_normalized_meter_score'
    (a.output/'run-validated.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':
    main()
