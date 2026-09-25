"""Validate replay controls and measure candidate-selection headroom separately."""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay-dir',type=Path,required=True)
    args=p.parse_args();r=json.loads((args.replay_dir/'report.json').read_text())
    if not r['complete']:p.error('replay incomplete')
    config=r['configuration'];source=json.loads(Path(config['source_report']).read_text())
    old={row['id']:row for row in source['tracks']}
    catalog=json.loads(Path(config['catalog']).read_text());records={row['id']:row for row in catalog['tracks']}
    checks=0; mismatches=[];rows=[]
    snapshot=args.replay_dir/'source-snapshot';snapshot.mkdir(exist_ok=True)
    for name,digest in config['source_hashes'].items():
        path=Path(__file__).with_name(name)
        if sha256(path)!=digest:raise ValueError('frozen source changed: '+name)
        shutil.copyfile(path,snapshot/name)
    for row in r['tracks']:
        path=args.replay_dir/row['id']
        if sha256(path/'predictions.json')!=row['predictions_sha256']:raise ValueError('prediction changed')
        for name,previous in [('official_minimal','official_minimal'),('legacy_dbn','legacy_dbn'),('legacy_dbn_clock','clock_pipeline')]:
            for label,tol in [('10ms',.01),('20ms',.02),('30ms',.03),('70ms',.07)]:
                for key,prefix in [('beats_seconds','event'),('downbeats_seconds','downbeat')]:
                    scores=old[row['id']]['scores'][previous]['annotated_span'][key]
                    if scores is None:continue
                    current=row['methods'][name]['metrics'][prefix+'_'+label];checks+=1
                    if any(abs(current[k]-scores[str(tol)][k])>1e-12 for k in ('f1','precision','recall')):
                        mismatches.append([row['id'],name,key,label])
        record=records[row['id']]['reference']
        if sha256(record['path'])!=record['sha256']:raise ValueError('reference changed')
        reference=json.loads(Path(record['path']).read_text());lo,hi=reference['evaluation_support_seconds']
        truth=[t for t in reference['beats_seconds'] if lo<=t<=hi]
        candidates=json.loads((path/'candidates.json').read_text())['candidates'] if (path/'candidates.json').is_file() else []
        values=[]
        for c in candidates:
            pred=[e['source_seconds'] for e in c['indexed_grid'] if lo<=e['source_seconds']<=hi]
            values.append({'id':c['id'],**{label:nearest_event_diagnostics(truth,pred,tol)['f1'] for label,tol in [('20ms',.02),('70ms',.07)]}})
        selected=row['methods']['clock_candidates_selected'];entry={'id':row['id'],'genre':row['genre'],'candidate_count':len(values),
            'selected_candidate_id':selected.get('selected_candidate_id'),'prediction_empty':not selected['prediction']['beats_seconds']}
        for label in ('20ms','70ms'):
            best=max(values,key=lambda value:value[label]) if values else None
            entry['selected_'+label]=selected['metrics']['event_'+label]['f1']
            entry['oracle_'+label]=best[label] if best else 0.
            entry['oracle_candidate_'+label]=best['id'] if best else None
            entry['oracle_gain_'+label]=entry['oracle_'+label]-entry['selected_'+label]
        rows.append(entry)
    output={'schema_version':1,'diagnostic_only':True,'reference_used_for_candidate_choice':True,
        'does_not_modify_automatic_selection':True,'scope':'feature-only event selection headroom, not deployable or full-map accuracy',
        'replay_report_sha256':sha256(args.replay_dir/'report.json'),'runner_sha256':sha256(__file__),
        'validation':{'original_control_event_metric_cases':checks,'mismatches':mismatches,
                      'all_prediction_hashes_verified':True,'all_reference_hashes_verified':True,'frozen_sources_snapshotted':True},
        'summary':{'tracks':len(rows),'empty_candidate_tracks':sum(not row['candidate_count'] for row in rows),
            **{label:{'selected_macro_f1':float(np.mean([row['selected_'+label] for row in rows])),
                       'oracle_macro_f1_including_empty_zero':float(np.mean([row['oracle_'+label] for row in rows])),
                       'tracks_with_better_available_candidate':sum(row['oracle_gain_'+label]>1e-12 for row in rows)}
               for label in ('20ms','70ms')}},'rows':rows}
    (args.replay_dir/'candidate-selection-diagnostic.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'validation':output['validation'],'summary':output['summary']}))


if __name__=='__main__':main()
