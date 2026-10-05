"""Two local workers; same frozen inference modules, resumable source jobs."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
from experiments.tempo_meter_v3.probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--parameters',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--reuse',type=Path);p.add_argument('--workers',type=int,default=2)
    p.add_argument('--resume',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=a.resume)
    inputs=json.loads(a.input.read_text());arms=['no_repeat','automatic_repeat']
    names=('observations.py','latent_clock.py','continuous.py','bar_structure.py','repetition.py','support.py','analyzer.py','run_cached.py','run_comparison.py','capacity_emissions.py','fast_structure.py','learned_support.py','capacity_fit.py','capacity_objective.py','capacity_vocabulary.py','capacity_support.py','run_capacity_comparison.py')
    sources={n:digest(Path(__file__).with_name(n)) for n in names}
    records={arm:{} for arm in arms}
    for base in ([a.reuse] if a.reuse else [])+([a.output] if a.resume else []):
        for arm in arms:
            path=base/arm/'manifest.json'
            if not path.exists():continue
            previous=json.loads(path.read_text())
            for key,expected in [('input_sha256',digest(a.input)),('parameters_sha256',digest(a.parameters)),('implementation_sha256',sources)]:
                if previous[key]!=expected:raise ValueError('reuse differs '+key)
            for row in previous['rows']:
                if digest(row['selected']['path'])!=row['selected']['sha256']:raise ValueError('reused prediction changed')
                records[arm][row['id']]=row
    def save(complete=False):
        for arm in arms:
            folder=a.output/arm;folder.mkdir(exist_ok=True)
            value=dict(complete=complete,references_available_to_runner=False,input_sha256=digest(a.input),parameters_sha256=digest(a.parameters),
                implementation_sha256=sources,execution_implementation_sha256=digest(__file__),requested_ids=[r['id'] for r in inputs['rows']],
                workers=a.workers,beam=32,rows=[records[arm][r['id']] for r in inputs['rows'] if r['id'] in records[arm]])
            target=folder/'manifest.json';temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps(value,indent=2)+'\n');os.replace(temporary,target)
    save()
    jobs=a.output/'jobs';jobs.mkdir(exist_ok=True)
    def execute(index,row):
        folder=jobs/f'{index:02d}';folder.mkdir(exist_ok=True)
        inp=folder/'input.json';value=dict(inputs,rows=[row]);inp.write_text(json.dumps(value,indent=2)+'\n')
        out=folder/'predictions'
        command=[sys.executable,'-m','experiments.tempo_meter_v4.run_capacity_comparison','--input',str(inp),'--parameters',str(a.parameters),'--output',str(out)]
        if out.exists():command.append('--resume')
        with (folder/'execution.log').open('a') as stream:
            result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f"source {row['id']} failed; see {folder/'execution.log'}")
        return {arm:json.loads((out/arm/'manifest.json').read_text())['rows'][0] for arm in arms}
    pending=[(i,r) for i,r in enumerate(inputs['rows']) if not all(r['id'] in records[arm] for arm in arms)]
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        futures={executor.submit(execute,i,row):row for i,row in pending}
        for future in as_completed(futures):
            row=futures[future];result=future.result()
            for arm in arms:records[arm][row['id']]=result[arm]
            save();print('completed',row['id'],'total',len(records['automatic_repeat']),flush=True)
    assert all(len(records[arm])==len(inputs['rows']) for arm in arms);save(True)
    print('complete',flush=True)


if __name__=='__main__':main()
