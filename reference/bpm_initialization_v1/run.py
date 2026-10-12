"""Reference-denying source workers, pre-score freeze, and deterministic files."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import json
import multiprocessing
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from experiments.variable_tempo_interval_consensus_v0.io import source_array
from experiments.bpm_continuity_v1.evidence import Evidence
from experiments.bpm_continuity_v1.core import source_base
from experiments.bpm_continuity_v1.run import table_hash, adapt_inputs
from .common import ROOT, METHODS, POLICIES, read, write, digest, object_hash, code_files, guard
from .core import initialize, render, seed_diagnostics


def install_guard(run):
    run = Path(run).resolve(); denied = []; opened = []
    def hook(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes)):
            return
        p = Path(args[0]).resolve()
        forbidden = (p.name in ('catalog.json', 'evaluation-manifest.json') or
                     'current-references' in p.parts or 'baseline-comparison' in p.parts or
                     'reference' in p.name.lower() or 'marker' in p.name.lower() or
                     ('initial-inputs' in p.parts and 'encoded' not in p.parts))
        if forbidden:
            denied.append(str(p)); raise PermissionError(f'Source worker forbidden read: {p}')
        if p.is_relative_to(run) and not str(p).endswith('.partial'):
            opened.append(str(p.relative_to(run)))
    sys.addaudithook(hook)
    return denied, opened


def build_evidence(row, cfg):
    data = source_array(row['evidence_path']); bank = read(row['bank_path'])['pools']['final']
    return {str(int(window)): Evidence(data, bank, dict(cfg, window=window)) for window in (6., 12., 24.)}


def source_worker(argument):
    row, run, stage = argument; run = Path(run); started = time.perf_counter()
    if set(row) != {'id', 'evidence_path', 'bank_path', 'family_path', 'duration_seconds', 'fps'}:
        raise ValueError('Source-only worker schema violated')
    denied, opened = install_guard(run)
    cfg = read(run / 'config.json'); evs = build_evidence(row, cfg)
    hashes = {window: table_hash(ev) for window, ev in evs.items()}; ev6 = evs['6']
    if stage == 'build':
        for window, ev in evs.items():
            target = run / ('evidence-tables' if window == '6' else 'initial-evidence-tables/' + window) / (row['id'] + '.npz')
            target.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(target, time=ev.time, S=ev.S, G=ev.G, count=ev.count, freshness=ev.fresh)
        write(run / 'source-bootstrap' / (row['id'] + '.json'), source_base(ev6))
        receipt = {'id': row['id'], 'common_evidence_hash': hashes['6'], 'evidence_hashes': hashes,
                   'bank_count': len(ev6.bank), 'source_only': True}
    else:
        expected = read(run / 'receipts' / ('build-' + row['id'] + '.json'))['evidence_hashes']
        if hashes != expected:
            raise ValueError('Source evidence changed after preparation')
        inputs = read(run / 'initial-inputs/encoded' / (row['id'] + '.json'))
        family = read(row['family_path']); cache = {}; output_hashes = {}
        for method in METHODS:
            ev_seed = evs['12'] if method == 'I2_LOCAL12' else evs['24'] if method == 'I3_LOCAL24' else ev6
            for policy in POLICIES:
                initial = inputs[policy]; key = (method, object_hash(initial))
                if key not in cache:
                    boot = initialize(ev6, ev_seed, family, initial, method)
                    prediction, traces = render(ev6, boot)
                    prediction.update(id=row['id'], arm='C_HOLD', common_evidence_hash=hashes['6'])
                    diagnostic = seed_diagnostics(ev6, ev_seed, boot, initial)
                    cache[key] = (boot, prediction, traces, diagnostic)
                boot, prediction, traces, diagnostic = cache[key]
                write(run / 'bootstrap' / method / policy / (row['id'] + '.json'), boot)
                write(run / 'seed-diagnostics' / method / policy / (row['id'] + '.json'), diagnostic)
                dest = run / 'predictions' / method / policy / (row['id'] + '.json')
                write(dest, prediction)
                trace_path = run / 'decision-traces' / method / policy / (row['id'] + '.jsonl.gz')
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                with trace_path.open('wb') as raw:
                    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
                        for trace in traces:
                            stream.write((json.dumps(trace, sort_keys=True, allow_nan=False,
                                                     separators=(',', ':')) + '\n').encode())
                output_hashes[method + '/' + policy] = {
                    'prediction': digest(dest), 'trace': digest(trace_path), 'bootstrap': object_hash(boot),
                    'seed_diagnostic': object_hash(diagnostic)}
        receipt = {'id': row['id'], 'common_evidence_hash': hashes['6'], 'evidence_hashes': hashes,
                   'prediction_count': len(METHODS) * len(POLICIES), 'hashes': output_hashes,
                   'reference_fields_read': False}
    receipt.update(seconds=time.perf_counter() - started, denied_reads=denied,
                   opened_run_paths=sorted(set(opened)))
    write(run / 'receipts' / (stage + '-' + row['id'] + '.json'), receipt)
    return receipt


def freeze(run):
    if not read(run / 'controls.json')['passed']:
        raise RuntimeError('Logical controls failed')
    if (run / 'frozen.json').exists() or (run / 'predictions').exists():
        raise FileExistsError('Already frozen or already predicted')
    files = ['config.json', 'protocol.json', 'controls.json', 'source-worker-inputs.json',
             'source-manifest.json', 'evaluation-manifest.json']
    for directory in ['source-evidence', 'candidate-banks', 'source-families', 'current-references',
                      'initial-inputs', 'source-bootstrap', 'evidence-tables', 'initial-evidence-tables',
                      'baseline-comparison']:
        files.extend(str(p.relative_to(run)) for p in sorted((run / directory).rglob('*')) if p.is_file())
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in code_files()}
    for p in code_files():
        dest = run / 'code-config-snapshot' / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
    write(run / 'frozen.json', {'code_hashes': hashes, 'run_file_hashes': {p: digest(run / p) for p in files},
                               'target_predictions_exist': False, 'configuration_selected_before_target_scores': True})


def execute(run, stage, workers):
    if stage == 'freeze':
        freeze(run); print('FROZEN', run, flush=True); return
    if stage == 'predict':
        guard(run)
        if (run / 'predictions').exists():
            raise FileExistsError('No silent prediction overwrite')
    rows = read(run / 'source-worker-inputs.json')['samples']; results = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as executor:
        futures = {executor.submit(source_worker, (row, run, stage)): row['id'] for row in rows}
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            print(stage.upper(), result['id'], round(result['seconds'], 2), 's', flush=True)
    if stage == 'build':
        adapt_inputs(run)
    write(run / 'receipts' / (stage + '.json'), {'completed': True, 'workers': workers, 'rows': results})


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--stage', choices=['build', 'freeze', 'predict'], required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(); execute(args.run.resolve(), args.stage, args.workers)


if __name__ == '__main__':
    main()
