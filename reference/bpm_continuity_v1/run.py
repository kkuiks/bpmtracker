"""Source-only worker stages, initial scalar adapter, and frozen prediction runs."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import multiprocessing
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from experiments.variable_tempo_interval_consensus_v0.io import source_array
from experiments.metronome_reconstruction_v1.hinted import encode_tap_level
from .common import ROOT, ARMS, POLICIES, read, write, digest, object_hash, code_hashes, code_files, frozen_guard
from .core import source_base, bootstrap, predict
from .evidence import Evidence


def table_hash(ev):
    h=hashlib.sha256()
    for value in (ev.time,ev.S,ev.G,ev.count,ev.fresh):
        h.update(str((value.shape,str(value.dtype))).encode());h.update(value.tobytes())
    h.update(json.dumps(ev.bank,sort_keys=True).encode())
    return h.hexdigest()


def install_guard(run, stage):
    denied=[];opened=[];run=Path(run).resolve()
    def hook(event,args):
        if event!='open' or not isinstance(args[0],(str,bytes)): return
        path=str(args[0]);p=Path(path).resolve()
        relative=str(p.relative_to(run)) if p.is_relative_to(run) else path
        forbidden=(p.name=='catalog.json' or p.name=='evaluation-manifest.json' or
                   'current-references' in p.parts or 'legacy-predictions' in p.parts or
                   'reference' in p.name.lower() or 'marker' in p.name.lower() or
                   ('initial-inputs' in p.parts and 'encoded' not in p.parts))
        if forbidden:
            denied.append(path);raise PermissionError(f'Source worker forbidden read: {path}')
        if p.is_relative_to(run) and not path.endswith('.partial'): opened.append(relative)
    sys.addaudithook(hook)
    return denied,opened


def source_worker(argument):
    row,run,stage=argument;run=Path(run);start=time.perf_counter()
    allowed={'id','evidence_path','bank_path','duration_seconds','fps'}
    if set(row)!=allowed: raise ValueError('Source-only schema violated')
    denied,opened=install_guard(run,stage)
    cfg=read(run/'config.json')
    ev=Evidence(source_array(row['evidence_path']),read(row['bank_path'])['pools']['final'],cfg)
    common_hash=table_hash(ev)
    if stage=='build':
        target=run/'evidence-tables'/f"{row['id']}.npz";target.parent.mkdir(exist_ok=True)
        np.savez_compressed(target,time=ev.time,S=ev.S,G=ev.G,count=ev.count,freshness=ev.fresh)
        write(run/'source-bootstrap'/f"{row['id']}.json",source_base(ev))
        receipt={'id':row['id'],'common_evidence_hash':common_hash,'seconds':time.perf_counter()-start,
                 'bank_count':len(ev.bank),'steps':len(ev.time),'denied_reads':denied,
                 'opened_run_paths':sorted(set(opened)),'source_only':True}
    else:
        expected=read(run/'receipts'/f"build-{row['id']}.json")['common_evidence_hash']
        if common_hash!=expected: raise ValueError('Prepared source-only score tables changed')
        inputs=read(run/'initial-inputs/encoded'/f"{row['id']}.json")
        boot_cache={};output_cache={};hashes={}
        for policy in POLICIES:
            initial=inputs[policy];key=object_hash(initial)
            if key not in boot_cache: boot_cache[key]=bootstrap(ev,initial)
            boot=boot_cache[key]
            write(run/'bootstrap'/policy/f"{row['id']}.json",boot)
            for arm in ARMS:
                cache_key=(key,arm)
                if cache_key not in output_cache:
                    prediction,traces=predict(ev,boot,arm)
                    prediction.update(id=row['id'],arm=arm,common_evidence_hash=common_hash)
                    output_cache[cache_key]=(prediction,traces)
                prediction,traces=output_cache[cache_key]
                dest=run/'predictions'/arm/policy/f"{row['id']}.json"
                trace_dest=run/'decision-traces'/arm/policy/f"{row['id']}.jsonl.gz"
                write(dest,prediction);trace_dest.parent.mkdir(parents=True,exist_ok=True)
                with trace_dest.open('wb') as raw:
                    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as stream:
                        for trace in traces:
                            stream.write((json.dumps(trace,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode())
                hashes[f'{arm}/{policy}']={'prediction':digest(dest),'trace':digest(trace_dest),'bootstrap':object_hash(boot)}
        receipt={'id':row['id'],'common_evidence_hash':common_hash,'seconds':time.perf_counter()-start,
                 'prediction_count':len(ARMS)*len(POLICIES),'hashes':hashes,'denied_reads':denied,
                 'opened_run_paths':sorted(set(opened)),'reference_fields_read':False}
    write(run/'receipts'/f"{stage}-{row['id']}.json",receipt)
    return receipt


def adapt_inputs(run):
    # Reference adapter runs after source-only candidate scores are prepared.
    rows=read(run/'evaluation-manifest.json')['samples']
    ratios={'proxy_unit_minus5':.95,'proxy_unit_zero':1.,'proxy_unit_plus5':1.05}
    receipts=[]
    for row in rows:
        ident=row['id'];reference=read(row['reference_path'])
        bpm=reference['initial_bpm'];base=read(run/'source-bootstrap'/f'{ident}.json')['audio_base_bpm']
        encoded={'oracle_start':{'kind':'oracle','initial_bpm':bpm}};raw=[]
        for policy,ratio in ratios.items():
            value=bpm*ratio
            decision=encode_tap_level(base,value) if base is not None else {'power':None,'status':'no_audio_base'}
            encoded[policy]={'kind':'proxy','power':decision['power']} if decision['power'] is not None else {'kind':'unavailable','reason':decision['status']}
            raw.append({'policy':policy,'ratio':ratio,'adapter_bpm':value,'nominal_initial_reference_bpm':bpm,
                        'audio_base_bpm':base,'encoder':decision,'actual_human_taps_collected':False,
                        'provenance':'reference-derived perturbed-unit diagnostic'})
        write(run/'initial-inputs'/f'{ident}.json',{'oracle_initial_bpm':bpm,'proxy_receipts':raw})
        write(run/'initial-inputs/encoded'/f'{ident}.json',encoded)
        receipts.append({'id':ident,'same_proxy_power':len({object_hash(encoded[p]) for p in ratios})==1,
                         'source_scores_prepared_before_initial_assistance':True})
    write(run/'receipts/adapter.json',{'rows':receipts,'actual_human_taps_collected':False,
                                     'source_predictor_gets_no_proxy_bpm_number':True})


def freeze(run):
    if not read(run/'controls.json')['passed']: raise RuntimeError('Logical controls failed; do not score targets')
    if (run/'frozen.json').exists(): raise FileExistsError('Run already frozen')
    files=['config.json','protocol.json','source-worker-inputs.json','source-manifest.json','evaluation-manifest.json','controls.json']
    for directory in ['source-evidence','candidate-banks','current-references','initial-inputs','source-bootstrap']:
        files += [str(p.relative_to(run)) for p in sorted((run/directory).rglob('*')) if p.is_file()]
    hashes={str(path.relative_to(ROOT)):digest(path) for path in code_files()}
    for path in code_files():
        dest=run/'code-config-snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    write(run/'code-config-snapshot/config.json',read(run/'config.json'))
    write(run/'frozen.json',{'code_hashes':hashes,'run_file_hashes':{p:digest(run/p) for p in files},
                           'config_sha256':digest(run/'config.json'),'target_predictions_exist':False})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--stage',choices=['build','freeze','predict'],required=True)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();run=args.run.resolve()
    if args.stage=='freeze': freeze(run);print('FROZEN',run);return
    if args.stage=='predict':
        frozen_guard(run)
        if (run/'predictions').exists(): raise FileExistsError('Predictions already exist; no silent rerun')
    source_rows=read(run/'source-worker-inputs.json')['samples']
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as executor:
        futures={executor.submit(source_worker,(row,run,args.stage)):row['id'] for row in source_rows}
        for future in as_completed(futures):
            ident=futures[future]
            try:
                result=future.result();results.append(result)
                print(args.stage.upper(),ident,'seconds',round(result['seconds'],2),flush=True)
            except Exception as exc:
                write(run/'receipts'/f'{args.stage}-{ident}-failure.json',{'id':ident,'error':repr(exc)})
                print('WORKER_FAILURE',ident,repr(exc),flush=True)
                raise
    if args.stage=='build': adapt_inputs(run)
    write(run/'receipts'/f'{args.stage}.json',{'completed':True,'workers':args.workers,'rows':results})


if __name__=='__main__': main()
