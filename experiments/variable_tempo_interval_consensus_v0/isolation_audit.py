"""Requested post-freeze source-I/O audit on an identical source and two dummy evaluators."""
import argparse
from pathlib import Path
import shutil
import sys
from .io import read,write,digest
from .core import DEFAULT
from .worker import frozen_one


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    source=next(r for r in read(a.run/'source-inputs.json')['samples'] if r['id']=='src0503')
    cfg={**DEFAULT,**read(a.run/'selected-config.json')['configuration']}
    roots=[]
    for name,content in [('a',{'reference_path':'/does/not/exist','BPM':9999}),('b',{'reference_path':'/unavailable','BPM':1,'phase':777})]:
        root=a.run/'source-isolation-audit'/name;root.mkdir(parents=True,exist_ok=False)
        shutil.copyfile(a.run/'candidate-banks'/f"{source['id']}.json",root/'bank.json')
        (root/'candidate-banks').mkdir();(root/'bank.json').rename(root/'candidate-banks'/f"{source['id']}.json")
        write(root/'evaluation-index.json',content);roots.append(root)
    accesses=[];blocked=[];active=[False]
    def audit(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        path=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
        text=str(path).lower()
        if path.suffix in ('.json','.npz','.gz'):
            accesses.append(text)
            if any(token in text for token in ('evaluation','reference','catalog','transport-marker','music-with-click')):
                blocked.append(text);raise RuntimeError('Source worker attempted forbidden evaluation/marker I/O')
    sys.addaudithook(audit)
    for root in roots:
        active[0]=True
        try:frozen_one((source,str(root),cfg,None))
        finally:active[0]=False
    files=list((roots[0]/'frozen-predictions').rglob('*.json'))
    matches=all(digest(path)==digest(roots[1]/path.relative_to(roots[0])) for path in files)
    result=dict(prediction_files_per_dummy=len(files),all_predictions_identical=matches,
                forbidden_read_attempts=blocked,opened_data_paths=sorted(set(accesses)),
                actual_read_hook_used=True,no_OS_sandbox_claim=True,assistance_not_used_for_this_isolation_case=True)
    write(a.run/'source-isolation-audit.json',result)
    print('SOURCE_ISOLATION',len(files),'identical',matches,'forbidden_reads',len(blocked),flush=True)
    if not matches or blocked:raise SystemExit(1)


if __name__=='__main__':main()
