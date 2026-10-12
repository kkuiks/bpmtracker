"""Requested reference-isolation and execution-determinism audit."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
import shutil

from .common import ARMS,POLICIES,read,write,digest,frozen_guard
from .run import source_worker


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve();frozen_guard(run)
    row=next(r for r in read(run/'source-worker-inputs.json')['samples'] if r['id']=='src0095')
    roots=[]
    for case,bpm,phase,scope in [('A',41.,.013,[0.,30.]),('B',299.,.333,[50.,180.])]:
        root=run/'isolation-audit'/case;root.mkdir(parents=True,exist_ok=False);roots.append(root)
        shutil.copy2(run/'config.json',root/'config.json')
        write(root/'evaluation-manifest.json',{'samples':[{'id':row['id'],'future_bpm':bpm,'phase':phase,'support':scope}]})
        write(root/'current-references/sentinel.json',{'future_bpm':bpm,'phase':phase,'scope':scope,'meter':7 if case=='A' else 3})
        target=root/'initial-inputs/encoded'/f"{row['id']}.json";target.parent.mkdir(parents=True)
        shutil.copy2(run/'initial-inputs/encoded'/f"{row['id']}.json",target)
        target=root/'receipts'/f"build-{row['id']}.json";target.parent.mkdir()
        shutil.copy2(run/'receipts'/f"build-{row['id']}.json",target)
    with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn')) as pool:
        receipts=[pool.submit(source_worker,(row,r,'predict')).result() for r in roots]
    checks=[]
    for arm in ARMS:
        for policy in POLICIES:
            for relative in [f'predictions/{arm}/{policy}/{row["id"]}.json',
                             f'decision-traces/{arm}/{policy}/{row["id"]}.jsonl.gz']:
                values=[digest(root/relative) for root in roots]+[digest(run/relative)]
                checks.append({'path':relative,'identical_under_different_references_and_worker_count':len(set(values))==1,'sha256':values})
    same_unit=[]
    for source in read(run/'source-worker-inputs.json')['samples']:
        encoded=read(run/'initial-inputs/encoded'/f"{source['id']}.json")
        for a in POLICIES[1:]:
            for b in POLICIES[1:]:
                if a>=b or encoded[a]!=encoded[b]: continue
                for arm in ARMS:
                    paths=[run/'predictions'/arm/p/f"{source['id']}.json" for p in (a,b)]
                    traces=[run/'decision-traces'/arm/p/f"{source['id']}.jsonl.gz" for p in (a,b)]
                    same_unit.append({'id':source['id'],'arm':arm,'policies':[a,b],
                                      'identical':digest(paths[0])==digest(paths[1]) and digest(traces[0])==digest(traces[1])})
    passed=all(c['identical_under_different_references_and_worker_count'] for c in checks) and all(c['identical'] for c in same_unit)
    passed&=all(not r['denied_reads'] for r in receipts)
    write(run/'source-isolation-audit.json',{'passed':passed,'checks':checks,'same_unit_checks':same_unit,
                                          'incompatible_dummy_evaluations':2,'source_workers':receipts,
                                          'main_worker_count':2,'audit_worker_count':1,
                                          'initial_scalar_or_power_held_fixed':True,'forbidden_reads':sum(len(r['denied_reads']) for r in receipts)})
    print('SOURCE_ISOLATION_AUDIT', 'PASS' if passed else 'FAIL',len(checks),'execution checks',len(same_unit),'same-unit checks')
    if not passed: raise SystemExit(2)


if __name__=='__main__': main()
