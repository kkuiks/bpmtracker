"""Run one fixed source-only BPM/meter proposal path on arbitrary input rows.

Rows contain only audio and frozen Beat This observations. No reference catalog,
track-name case distinction, approved offset or model score is read here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .barwise_tempo import propose_barwise_tempo
from .compound_meter import propose_compound_6_8
from .tail_support import propose_tail_stop
from .constant_grid import infer_constant_map
from .plausible_bpm import snap_prediction
from .tempo_segments import infer_tempo_segments


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def bound(binding: dict) -> Path:
    path = Path(binding['path'])
    if digest(path) != binding['sha256']:
        raise ValueError(f'input hash changed: {path}')
    return path


def save(path: Path, value: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return {'path':str(path.resolve()),'sha256':digest(path)}


def observe(result: dict, source: dict) -> tuple[list[float],list[float]]:
    if 'methods' in result:
        if result['source']['sha256'] != source['sha256']:
            raise ValueError('official nested observation source differs')
        payload = result['methods']['official']['prediction']
    else:
        if (result['audio']['sha256'] != source['sha256'] or
                result['audio']['sample_rate'] != source['sample_rate'] or
                result['audio']['analyzed_frames'] != source['sample_frames']):
            raise ValueError('official observation source differs')
        payload = result
    return payload['beats_seconds'],payload['downbeats_seconds']


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-manifest',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists():
        raise FileExistsError('fresh output required')
    inputs=json.loads(args.input_manifest.read_text())
    if (inputs.get('source_only') is not True or inputs.get('reference_read') is not False or
            not inputs.get('rows') or len({r['id'] for r in inputs['rows']})!=len(inputs['rows'])):
        raise ValueError('complete unique source-only observations required')
    root=Path(__file__).resolve().parent
    record={
        'schema_version':1,'complete':False,'references_available_to_runner':False,
        'input_manifest_sha256':digest(args.input_manifest),
        'implementation_sha256':{name:digest(root/name) for name in
                                  ('run_generic_map.py','constant_grid.py','tempo_segments.py',
                                   'barwise_tempo.py','compound_meter.py',
                                   'tail_support.py','plausible_bpm.py')},
        'selection_policy':'old bounded tempo if accepted; else source-event barwise; else compound 6/8; else constant. Then joint tail disruption and unchanged guarded BPM cleanup',
        'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'rows':[],
    }
    for row in inputs['rows']:
        audio_path=bound(row['audio'])
        logits_path=bound(row['logits'])
        official=json.loads(bound(row['official_result']).read_text())
        info=sf.info(audio_path)
        source={'sha256':row['audio']['sha256'],'sample_rate':info.samplerate,
                'sample_frames':info.frames}
        if 'source' in row and row['source'] != source:
            raise ValueError('source geometry changed')
        raw_beats,raw_bars=observe(official,source)
        with np.load(logits_path) as arrays:
            beat,down,fps=arrays['beat'],arrays['downbeat'],float(arrays['fps'])
        constant=infer_constant_map(beat,down,fps,raw_bars,source)
        bounded=infer_tempo_segments(constant,beat,down,fps,raw_beats)
        barwise,barwise_decision=propose_barwise_tempo(constant,raw_beats,raw_bars)
        compound,compound_decision=propose_compound_6_8(constant,raw_beats)
        if bounded['diagnostics']['tempo_segments']['accepted']:
            selected_preclean=bounded
            branch='bounded_tempo'
        elif barwise_decision['accepted']:
            selected_preclean=barwise
            branch='barwise_tempo'
        elif compound_decision['accepted']:
            selected_preclean=compound
            branch='compound_6_8'
        else:
            selected_preclean=constant
            branch='constant'
        with_tail,tail_decision=propose_tail_stop(selected_preclean,constant,raw_beats,raw_bars)
        selected,snap_decision=snap_prediction(with_tail)
        predictions={name:save(output/'predictions'/row['id']/(name+'.json'),value)
                     for name,value in [('constant',constant),('bounded_tempo',bounded),
                                        ('barwise_tempo',barwise),('compound_6_8',compound),
                                        ('with_tail',with_tail),('selected',selected)]}
        record['rows'].append({
            'id':row['id'],'source':source,'audio':row['audio'],
            'logits':row['logits'],'official_result':row['official_result'],
            'predictions':predictions,'selected_branch':branch,
            'bounded_tempo_decision':bounded['diagnostics']['tempo_segments'],
            'barwise_decision':barwise_decision,'compound_decision':compound_decision,
            'tail_decision':tail_decision,'plausible_bpm_decision':snap_decision,
        })
        save(output/'prediction-manifest.json',record)
        print(row['id'],branch,'base',round(constant['diagnostics']['period']['quarter_bpm'],3),
              'bars',constant['map']['meter_events'][0]['numerator'],
              'barwise_changes',barwise_decision.get('change_count',0),
              'reason',barwise_decision['reason'],
              'compound',compound_decision['accepted'],'tail',tail_decision['accepted'],flush=True)
    record['complete']=True
    record['ended_at_utc']=datetime.now(timezone.utc).isoformat()
    save(output/'prediction-manifest.json',record)


if __name__=='__main__':
    main()
