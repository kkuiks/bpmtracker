"""Trainability diagnostic on two qualified actual excerpts; not validation."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import torch
from .train_production import load
from .production_observations import predict_values
from .observations import sigmoid,local_peaks,refined_times
from .validate_production import prepare_cases,evaluate
from experiments.tempo_meter_v3.probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True);p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'));torch.set_num_threads(1)
    from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
    rows=[r for r in json.loads(a.manifest.read_text())['rows'] if r['id'] in ['ntm_archspire_liminal-cypher','forrester-savell-karnivool']]
    assert len(rows)==2 and all(r['split']=='train' for r in rows)
    training=json.loads((a.training/'training.json').read_text());assert training['tiny_fit']
    checkpoint=max(training['rows'][0]['checkpoints'],key=lambda p:int(Path(p).stem.split('-')[-1]))
    package=torch.load(checkpoint,map_location='cpu',weights_only=False);a.output.mkdir(parents=True,exist_ok=False);results=[]
    for row in rows:
        x,base,y,mask=[v[:2400] for v in load(row)];logits=predict_values(x,base,package)
        for channel,label in enumerate(['quarter','bar']):
            truth=refined_times(y[:,channel],local_peaks(y[:,channel],.2),50)
            probabilities=sigmoid(logits[:,channel]);pred=refined_times(probabilities,local_peaks(probabilities,.2),50)
            # Keep qualified frames; silence/no-grid labels remain valid negatives.
            truth=truth[np.interp(truth,np.arange(len(mask))/50,mask)>.5]
            pred=pred[np.interp(pred,np.arange(len(mask))/50,mask)>.5]
            score=nearest_event_diagnostics(truth,pred,.07)
            results.append(dict(id=row['id'],field=label,counts={k:score[k] for k in ['true_positives','false_positives','false_negatives']},f1_70ms=score['f1']))
    passed=all(r['f1_70ms'] is not None and r['f1_70ms']>=.9 for r in results)
    result=dict(rows=results,passed=passed,role='fit the same actual training excerpts, not generalization or product accuracy',
        checkpoint=str(Path(checkpoint).resolve()),checkpoint_sha256=digest(checkpoint),held_groups_used=False,
        acceptance='both quarter and bar event F1 >=90% on both 48-second fit excerpts',raw_integer_BPM_regression=False)
    (a.output/'trainability.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
    cases=prepare_cases(rows,a.output/'map-cases',prefix_seconds=48.,include_change_excerpts=False)
    diagnostic=evaluate(checkpoint,cases,json.loads(a.parameters.read_text())['selected'],a.output/'maps')
    diagnostic['role']='same training-excerpt map diagnostic; not held-group validation'
    (a.output/'map-diagnostic.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
    result.update(map_diagnostic_path=str((a.output/'map-diagnostic.json').resolve()),
        map_decode_failures=diagnostic['decode_failures'],
        trainability_gate='Event fit only; map decode failures remain explicit separate diagnostics')
    (a.output/'trainability.json').write_text(json.dumps(result,indent=2)+'\n')
    if not passed:raise SystemExit('Tiny actual fit failed: inspect labels/loss/model before main training')


if __name__=='__main__':main()
