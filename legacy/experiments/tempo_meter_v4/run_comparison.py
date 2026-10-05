"""Paired source-only no-repeat/automatic-repeat comparison on frozen evidence."""
import argparse
import json
from pathlib import Path
import sys
import time
import resource
import os
from .run_cached import load
from .analyzer import analyze
from experiments.tempo_meter_v3.probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,default=Path('data/cache/tempo-meter-v3/acoustic-v1'))
    p.add_argument('--resume',action='store_true')
    p.add_argument('--beam',type=int,default=32);p.add_argument('--limit',type=int);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    inputs=json.loads(a.input.read_text());params=json.loads(a.parameters.read_text())
    assert inputs['complete'] and not inputs['references_available_to_runner'] and params['validation_pass']
    selected_inputs=inputs['rows'][:a.limit]
    requested_ids=[row['id'] for row in selected_inputs]
    if len(requested_ids)!=len(set(requested_ids)):raise ValueError('duplicate source id')
    a.output.mkdir(parents=True,exist_ok=a.resume)
    names=('observations.py','latent_clock.py','continuous.py','bar_structure.py','repetition.py','support.py','analyzer.py','run_cached.py','run_comparison.py')
    sources={n:digest(Path(__file__).with_name(n)) for n in names}
    manifests={arm:dict(complete=False,references_available_to_runner=False,input_sha256=digest(a.input),
        parameters_sha256=digest(a.parameters),implementation_sha256=sources,beam=a.beam,requested_ids=requested_ids,rows=[]) for arm in ('no_repeat','automatic_repeat')}
    for arm in manifests:
        folder=a.output/arm;folder.mkdir(exist_ok=a.resume)
        previous=folder/'manifest.json'
        if a.resume and previous.exists():
            saved=json.loads(previous.read_text())
            for k in ('input_sha256','parameters_sha256','implementation_sha256','beam','requested_ids'):
                if saved[k]!=manifests[arm][k]:raise ValueError('resume binding differs: '+k)
            manifests[arm]=saved
        manifests[arm]['complete']=False
    def save(arm):
        target=a.output/arm/'manifest.json';temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifests[arm],indent=2)+'\n');os.replace(temporary,target)
    for arm in manifests:save(arm)
    finished={arm:{r['id']:r for r in m['rows']} for arm,m in manifests.items()}
    for i,row in enumerate(selected_inputs):
        if digest(row['audio'])!=row['source']['sha256']:raise ValueError('source changed')
        for arm in manifests:
            if row['id'] in finished[arm]:
                old=finished[arm][row['id']]
                if old['source']!=row['source'] or old['feature_binding']!=row['feature_binding'] or digest(old['selected']['path'])!=old['selected']['sha256']:
                    raise ValueError('reused prediction/source binding changed')
        if all(row['id'] in finished[arm] for arm in manifests):continue
        started=time.perf_counter()
        if digest(row['audio'])!=row['source']['sha256']:raise ValueError('source changed')
        obs=load(row,a.cache_root);cache={}
        for arm,mode in [('no_repeat','none'),('automatic_repeat','automatic')]:
            if row['id'] in finished[arm]:
                old=finished[arm][row['id']]
                if digest(old['selected']['path'])!=old['selected']['sha256']:raise ValueError('reused prediction changed')
                continue
            tick=time.perf_counter()
            selected,alternatives=analyze(obs,row['source'],row.get('initial_bpm'),parameters=params['selected'],repetition=mode,beam=a.beam,cache=cache)
            folder=a.output/arm/f'{i:02d}'
            attempt=0
            while folder.exists():
                attempt+=1;folder=a.output/arm/f'{i:02d}-attempt{attempt}'
            folder.mkdir();path=folder/'selected.json'
            path.write_text(json.dumps(selected,indent=2,allow_nan=False)+'\n')
            (folder/'alternatives.json').write_text(json.dumps(alternatives,indent=2,allow_nan=False)+'\n')
            result={k:row[k] for k in ('id','title','audio','source','initial_bpm','initial_bpm_source','feature_binding')}
            result.update(selected=dict(path=str(path.resolve()),sha256=digest(path)),runtime_seconds=time.perf_counter()-tick,
                runtime_scope='cached acoustic evidence; paired arms may reuse identical source-only base hypotheses',
                max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                original_v3_clock_bank_used=False,references_available_to_runner=False)
            manifests[arm]['rows'].append(result)
            save(arm)
            print(arm,row['id'],round(result['runtime_seconds'],2),'s',len(selected['map']['meter_events']),'meters',len(selected['map']['clock_knots'])-1,'tempo spans',flush=True)
        print('source-total',row['id'],round(time.perf_counter()-started,2),'s',flush=True)
    for arm in manifests:
        assert [r['id'] for r in manifests[arm]['rows']]==requested_ids
        manifests[arm]['complete']=True
        save(arm)


if __name__=='__main__':main()
