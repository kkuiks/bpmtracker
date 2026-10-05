"""Actual-training-prefix gate; physical event fit is not held generalization."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import torch

from services.analysis.observer import predict
from services.analysis.timeline import decode, event_peaks
from services.analysis.legacy_export import export_map


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);torch.set_num_threads(1)
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
    package=torch.load(a.checkpoint,map_location='cpu',weights_only=False);manifest=json.loads(a.manifest.read_text());results=[]
    if package['manifest_sha256']!=hashlib.sha256(a.manifest.read_bytes()).hexdigest():raise ValueError('tiny supervision manifest differs')
    for row in manifest['rows']:
        if row['id'] not in package['train_ids']:continue
        with np.load(row['features']) as z:f,b,e=z['features'][:2400].copy(),z['logits'][:2400].copy(),z['energy'][:2400].copy()
        with np.load(row['targets']) as z:target={k:z[k][:2400].copy() for k in z.files}
        fields=predict(f,b,e,package);metrics={}
        for key,channel in [('quarter',0),('bar',1)]:
            expected,_=event_peaks(target['y'][:,channel]);observed,_=event_peaks(fields[key]);metrics[key]=nearest_event_diagnostics(expected.tolist(),observed.tolist(),.07)
        # Prefix observations retain the full original source binding. Their
        # support remains the observed first48s; no fictitious cropped hash.
        source=dict(row['source'])
        timeline=decode(fields,source);m,export=export_map(timeline)
        path=a.output/(row['id']+'-timeline.json');path.write_text(json.dumps(dict(timeline=timeline,map=m,export=export),indent=2)+'\n')
        musical=target['musical_mask']>.5
        denominator_accuracy=float(np.mean(fields['denominator'].argmax(1)[musical]==target['denominator'][musical]))
        results.append(dict(id=row['id'],event_metrics=metrics,denominator_frame_accuracy=denominator_accuracy,passed=all(metrics[k]['f1']>=.95 for k in metrics) and denominator_accuracy>=.95,export=export))
    record=dict(rows=results,passed=all(r['passed'] for r in results),scope='Known TRAINING first48s event/note-unit fit only; not full-song, holdout or authored-meter success',checkpoint_sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest())
    (a.output/'results.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))


if __name__=='__main__':main()
