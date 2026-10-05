"""Validate and freeze all native captures before opening any owner reference."""
import argparse
import json
from pathlib import Path

from .native import adapt
from .prepare import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    run=a.run.resolve();inputs=json.loads((run/'inputs.json').read_text());rows=[]
    if not inputs['complete'] or inputs['references_available_to_analyzer'] or len(inputs['rows'])!=21:
        raise ValueError('complete fixed21 source-only inputs required')
    output=run/'predictions'
    if output.exists():raise FileExistsError(output)
    # Validate the complete set first: a partial capture cannot become a scored
    # subset merely because its folders exist.
    staged=[]
    for row in inputs['rows']:
        n=Path(row['neutral_name']).stem;folder=run/'products/cubase-pro15'/n
        receipt_path=folder/'capture-receipt.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig'))
        if receipt['status']!='captured' or receipt['source']!=row['source']:
            raise ValueError('capture/source receipt mismatch')
        if digest(row['working_audio'])!=row['working_copy']['working_sha256']:
            raise ValueError('commercial input WAV changed')
        smt=folder/(n+'-raw.smt');track=folder/(n+'-track.xml');cpr=folder/(n+'-raw.cpr')
        hashes={Path(o['path'].replace('\\','/')).name:o['sha256'] for o in receipt['outputs']}
        for path in (smt,track):
            if digest(path)!=hashes[path.name]:raise ValueError('native musical export changed after capture')
        payload=adapt(smt,track,row,ticks_per_quarter=480)
        payload.update(product='Cubase Pro 15.0.30.287',raw_native_exports={
            kind:dict(path=str(path),sha256=digest(path)) for kind,path in [('project',cpr),('tempo',smt),('audio_track',track)]})
        payload['native_project_close_save']=dict(capture_sha256=hashes[cpr.name],final_sha256=digest(cpr),
            native_tempo_and_audio_track_exports_unchanged=True,
            note='Cubase may save project UI/selection state on close; frozen musical exports must remain byte-identical')
        staged.append((row,receipt,payload,folder))
    output.mkdir()
    for row,receipt,payload,folder in staged:
        n=Path(row['neutral_name']).stem;path=output/(n+'.json')
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        rows.append(dict(id=row['id'],title=row['title'],source=row['source'],audio=row['original_audio'],
                         working_audio=row['working_audio'],neutral_name=row['neutral_name'],
                         selected=dict(path=str(path),sha256=digest(path)),native_folder=str(folder),
                         native_analysis_seconds=receipt['native_analysis_observed_seconds'],
                         workflow_seconds=receipt['capture_workflow_seconds'],reference_available_to_runner=False))
    manifest=dict(complete=True,product='Cubase Pro 15.0.30.287',song_count=21,
                  references_available_to_runner=False,source_only=True,
                  input_manifest_sha256=digest(run/'inputs.json'),protocol_sha256=digest(run/'protocol.json'),rows=rows)
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('Frozen',len(rows),'native source-clock-validated captures')


if __name__=='__main__':main()
