"""Run a single frozen analyzer on audio-only manifest rows; no reference reads."""
import argparse
import json
from pathlib import Path
from .analyzer import analyze
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--structure-checkpoint',type=Path,required=True);p.add_argument('--acoustic-checkpoint',type=Path,required=True);p.add_argument('--cache-root',type=Path,required=True)
    a=p.parse_args();inputs=json.loads(a.input.read_text())
    if not inputs.get('source_only') or a.output.exists():raise ValueError('audio-only manifest and fresh output required')
    if len({r['id'] for r in inputs['rows']})!=len(inputs['rows']):raise ValueError('duplicate rows')
    a.output.mkdir(parents=True)
    record=dict(complete=False,references_available_to_runner=False,input_sha256=digest(a.input),rows=[])
    for index,row in enumerate(inputs['rows']):
        if digest(row['audio'])!=row['audio_sha256']:raise ValueError('source changed')
        result=analyze(row['audio'],row.get('initial_bpm'),acoustic_checkpoint=a.acoustic_checkpoint,
            structure_checkpoint=a.structure_checkpoint,cache_root=a.cache_root,output=a.output/f'{index:02d}')
        record['rows'].append(dict(id=row['id'],title=row['title'],initial_bpm_source=row.get('initial_bpm_source'),**result))
        (a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    record['complete']=True;(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')

if __name__=='__main__':main()
