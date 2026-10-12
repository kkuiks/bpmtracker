"""Source-only extension and unchanged latest correction arms."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import time
import numpy as np
import soundfile as sf

from experiments.variable_clock_composition_v1.sensors import source_array, event_peaks, pcm_flux, final_bank
from experiments.variable_clock_composition_v1.proposals import generate
from experiments.variable_clock_composition_v1.evidence import table, refine_episodes
from experiments.variable_clock_composition_v1.compose import source_initial_unit, predict
from experiments.octave_fold_confirmation_v1.correct import apply
from .common import ROOT, METHODS, read, write, guard, digest


def paths(run, row):
    ident = row['id']
    if row['reused_composition']:
        return Path(row['old_bank_path']), Path(row['old_table_path'])
    return run / 'banks' / f'{ident}.json', run / 'tables' / f'{ident}.npz'


def prepare_one(run, row, tracker):
    ident = row['id']; started = time.perf_counter()
    if row['reused_composition']:
        write(run / 'source-unit' / f'{ident}.json', read(row['old_unit_path']))
        write(run / 'source-receipts' / f'{ident}.json', {'id': ident, 'cached_composition': True, 'fresh_neural_inference': False})
        return
    signal, rate = sf.read(row['audio_path'], dtype='float32', always_2d=True)
    if rate != row['sample_rate'] or signal.shape != (row['sample_frames'], row['channels']):
        raise RuntimeError('Audio source geometry mismatch')
    if row.get('cache_path'):
        data = source_array(row['cache_path'])
    else:
        beat, down = tracker(signal, rate)
        data = {'beat_logits': beat.cpu().numpy(), 'downbeat_logits': down.cpu().numpy(),
                'fps': np.array(50), 'duration_seconds': np.array(len(signal)/rate)}
    if abs(float(data['duration_seconds']) - row['duration_seconds']) > .08:
        raise RuntimeError('Cached observation duration mismatch')
    t, w = event_peaks(data['beat_logits']); dt, dw = event_peaks(data['downbeat_logits'])
    pt, pw = pcm_flux(signal, rate, row['duration_seconds'])
    events = {'times': t, 'weights': w, 'downbeat_times': dt, 'downbeat_weights': dw,
              'pcm_times': pt, 'pcm_weights': pw, 'duration': row['duration_seconds']}
    for directory in ('source-evidence', 'events', 'tables'):
        (run / directory).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run / 'source-evidence' / f'{ident}.npz', **data)
    np.savez_compressed(run / 'events' / f'{ident}.npz', **events)
    final = final_bank(data, run, ident)['pools']['final']
    banks = generate(events, final); initial_table = table(events, banks['expanded'])
    banks['expanded'], extra = refine_episodes(events, initial_table)
    tab = table(events, banks['expanded'])
    write(run / 'banks' / f'{ident}.json', banks)
    np.savez_compressed(run / 'tables' / f'{ident}.npz', **{key: value for key,value in tab.items() if key != 'clocks'})
    write(run / 'source-unit' / f'{ident}.json', source_initial_unit(tab))
    write(run / 'source-receipts' / f'{ident}.json', {'id': ident, 'cached_composition': False,
          'fresh_neural_inference': not bool(row.get('cache_path')), 'clock_count': len(banks['expanded']),
          'episode_refit_count': len(extra), 'elapsed_seconds': time.perf_counter()-started})
    print('SOURCE', ident, 'CACHE' if row.get('cache_path') else 'FRESH', round(time.perf_counter()-started, 2), flush=True)


def predict_one(run, row):
    started = time.perf_counter(); ident = row['id']; bank_path, table_path = paths(run, row)
    with np.load(table_path, allow_pickle=False) as arrays:
        tab = {name: arrays[name].copy() for name in arrays.files}
    tab['duration'] = float(tab['duration']); tab['clocks'] = read(bank_path)['expanded']
    packet = read(run / 'encoded-units/proxy100' / f'{ident}.json')
    reuse = row['reused_composition'] and packet == read(row['old_packet_path'])
    raw_maps = {}
    for policy in ('none', 'proxy100'):
        raw_maps[policy] = (read(row['old_raw_paths'][policy]) if reuse else
                            predict(tab, 'M3_REGION_HOLD', {}, None if policy == 'none' else packet))
        raw_maps[policy]['policy'] = policy
        write(run / 'raw-maps' / policy / f'{ident}.json', raw_maps[policy])
    for policy in ('proxy97', 'proxy103'):
        other = read(run / 'encoded-units' / policy / f'{ident}.json')
        raw_maps[policy] = raw_maps['proxy100'] if other == packet else predict(tab, 'M3_REGION_HOLD', {}, other)
        write(run / 'raw-maps' / policy / f'{ident}.json', raw_maps[policy])
    for method, options in METHODS.items():
        policies = ['none', 'proxy100'] + (['proxy97', 'proxy103'] if method == 'F1_FOLD05' else [])
        for policy in policies:
            output = apply(raw_maps[policy], tab, method, options); output['policy'] = policy
            write(run / 'predictions' / method / policy / f'{ident}.json', output)
    write(run / 'prediction-receipts' / f'{ident}.json', {'id': ident, 'old_raw_predictions_reused': bool(reuse),
          'elapsed_seconds': time.perf_counter()-started})
    print('PREDICT', ident, round(time.perf_counter()-started, 2), flush=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--stage', choices=['prepare','predict'], required=True)
    parser.add_argument('--shard', type=int, default=0); parser.add_argument('--shards', type=int, default=1)
    args = parser.parse_args(); guard(args.run)
    rows = read(args.run / 'source-inputs.json')['samples'][args.shard::args.shards]
    tracker = None
    if args.stage == 'prepare' and any(not row['reused_composition'] and not row.get('cache_path') for row in rows):
        import torch
        from beat_this.inference import Audio2Frames
        torch.set_num_threads(4); torch.set_num_interop_threads(1)
        tracker = Audio2Frames(str(ROOT / 'data/models/final0.ckpt'), device='cpu', float16=False)
    opened, forbidden = [], []; active = [False]
    def audit(event, arguments):
        if event != 'open' or not active[0] or not isinstance(arguments[0], (str, bytes)):
            return
        value = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        mode = arguments[1] if isinstance(arguments[1], str) else ''
        if any(c in mode for c in 'wax+'):
            return
        if Path(value).suffix in ('.json', '.npz', '.wav', '.ckpt'):
            opened.append(value)
            if any(token in value.lower() for token in ('/references/', 'evaluation-index', 'catalog.json', 'raw-proxies', 'acceptance.json')):
                forbidden.append(value); raise RuntimeError('Forbidden source-worker reference read')
    sys.addaudithook(audit); active[0] = True
    try:
        for row in rows:
            if args.stage == 'prepare':
                prepare_one(args.run, row, tracker)
            else:
                predict_one(args.run, row)
    finally:
        active[0] = False
    write(args.run / 'worker-audit' / f'{args.stage}-{args.shard}.json', {
        'actual_read_hook': True, 'ids': [row['id'] for row in rows], 'opened_data_paths': sorted(set(opened)),
        'forbidden_reads': forbidden, 'not_an_OS_sandbox_claim': True})
    guard(args.run)


if __name__ == '__main__':
    main()
