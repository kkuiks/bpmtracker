"""Whole-source predictions with validation-selected learned observations."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
import os
from pathlib import Path
import resource
import sys
import time
import torch
from .production_observations import observed
from .analyzer import analyze
from experiments.tempo_meter_v3.probe_resources import digest


# Keep the inference entry point independent of offline validation/reference code.
EXPECTED_DECODE_FAILURES=frozenset({
    'insufficient source events',
    'empty latent-coordinate beam',
    'no valid latent clock',
    'no coherent hypotheses',
    'no terminal bar paths',
})


def job(row,checkpoint,parameters,output):
    torch.set_num_threads(1)
    if parameters.get('downbeat_capacity',False):
        from .capacity_emissions import install
        install()
    selected_decoder=analyze
    if parameters.get('coordinate_refinement',False):
        from .coordinate_analyzer import install
        selected_decoder=install()
    package=torch.load(checkpoint,map_location='cpu',weights_only=False)
    feature=Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['source']['sha256']+'.npz')
    receipt=json.loads(feature.with_suffix('.json').read_text())
    if digest(row['audio'])!=row['source']['sha256'] or receipt['binding']!=row['feature_binding'] or digest(feature)!=receipt['feature_sha256']:raise ValueError('source/feature binding changed')
    tick=time.perf_counter();obs=observed(dict(features=str(feature)),package)
    try:
        predictions,_=selected_decoder(obs,row['source'],row['initial_bpm'],parameters=parameters,repetition='none',beam=32)
    except ValueError as exc:
        if str(exc) not in EXPECTED_DECODE_FAILURES:raise
        predictions=dict(status='decode_failed',error=str(exc),map=None,source_only=True,
            reference_read=False,observed_events=len(obs['events']),fallback_used=False)
    folder=Path(output)/row['id'];folder.mkdir(exist_ok=False);path=folder/'selected.json'
    path.write_text(json.dumps(predictions,indent=2,allow_nan=False)+'\n')
    result={key:row[key] for key in ['id','title','audio','source','initial_bpm','initial_bpm_source','feature_binding']}
    result.update(selected=dict(path=str(path.resolve()),sha256=digest(path)),runtime_seconds=time.perf_counter()-tick,
        max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,checkpoint_sha256=digest(checkpoint),
        references_available_to_runner=False,decoder_changed=False,encoder_changed=False,
        prediction_status='decode_failed' if predictions.get('status')=='decode_failed' else 'rendered',
        observed_events=len(obs['events']),fallback_used=False)
    (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--selection',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=2);p.add_argument('--resume',action='store_true');a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    source=json.loads(a.input.read_text());selection=json.loads(a.selection.read_text());params=json.loads(a.parameters.read_text())
    assert source['complete'] and not source['references_available_to_runner'] and selection['complete']
    checkpoint=selection['selected']['selected']
    if digest(checkpoint)!=selection['selected']['sha256']:raise ValueError('checkpoint changed')
    a.output.mkdir(parents=True,exist_ok=a.resume)
    names=['observations.py','latent_clock.py','continuous.py','bar_structure.py','repetition.py','support.py','analyzer.py','production_observations.py','run_learned.py']
    if params['selected'].get('downbeat_capacity',False):names+=['capacity_emissions.py','fast_structure.py','learned_support.py','capacity_fit.py','capacity_objective.py','capacity_vocabulary.py','capacity_support.py']
    if params['selected'].get('coordinate_refinement',False):names.append('coordinate_analyzer.py')
    bindings=dict(input_sha256=digest(a.input),selection_sha256=digest(a.selection),parameters_sha256=digest(a.parameters),checkpoint_sha256=digest(checkpoint),
        implementation_sha256={n:digest(Path(__file__).with_name(n)) for n in names})
    previous=a.output/'manifest.json';rows={}
    if previous.exists():
        old=json.loads(previous.read_text())
        for key,value in bindings.items():
            if old[key]!=value:raise ValueError('resume binding differs '+key)
        for row in old['rows']:
            if digest(row['selected']['path'])!=row['selected']['sha256']:raise ValueError('reused map changed')
            rows[row['id']]=row
    def save(complete=False):
        record=dict(bindings,complete=complete,references_available_to_runner=False,known_development_material=True,
            rows=[rows[r['id']] for r in source['rows'] if r['id'] in rows],workers=a.workers,
            expected_source_count=len(source['rows']),attempted_source_count=len(rows),
            successful_map_count=sum(r.get('prediction_status','rendered')=='rendered' for r in rows.values()),
            failure_count=sum(r.get('prediction_status')=='decode_failed' for r in rows.values()),
            completion_contract='All bound sources attempted; complete does not imply all maps decoded',
            failure_policy='Expected search failures have map=null receipts; no fallback; failures remain in evaluation denominator')
        temp=previous.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');os.replace(temp,previous)
    save()
    with ProcessPoolExecutor(max_workers=a.workers) as executor:
        futures={executor.submit(job,row,checkpoint,params['selected'],a.output):row for row in source['rows'] if row['id'] not in rows}
        for future in as_completed(futures):
            row=future.result();rows[row['id']]=row;save();print('learned',row['id'],len(rows),round(row['runtime_seconds'],2),'s',flush=True)
    assert len(rows)==len(source['rows']);save(True)


if __name__=='__main__':main()
