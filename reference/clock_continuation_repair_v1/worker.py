from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import numpy as np

from .common import POLICIES, METHODS, read, write, guard
from .repair import predict


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shard', type=int, default=0); parser.add_argument('--shards', type=int, default=1)
    args = parser.parse_args(); guard(args.run)
    rows = read(args.run/'source-inputs.json')['samples'][args.shard::args.shards]
    opened, forbidden, active = [], [], [False]
    def hook(event, arguments):
        if event != 'open' or not active[0] or not isinstance(arguments[0], (str, bytes)): return
        value = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        mode = arguments[1] if isinstance(arguments[1], str) else ''
        if any(c in mode for c in 'wax+'): return
        if Path(value).suffix in ['.json', '.npz']:
            opened.append(value)
            if any(x in value for x in ['/references/', 'evaluation-index', 'catalog.json', 'raw-proxies']):
                forbidden.append(value); raise RuntimeError('Reference read in source repair')
    sys.addaudithook(hook); active[0] = True
    for row in rows:
        started = time.perf_counter(); ident = row['id']
        with np.load(row['table_path'], allow_pickle=False) as arrays:
            tab = {name: arrays[name].copy() for name in arrays.files}
        tab['duration'] = float(tab['duration']); tab['clocks'] = read(row['bank_path'])['expanded']
        for policy in POLICIES:
            if policy in ['proxy97','proxy103']:
                methods = ['R1_FOLD_CONTINUE']
            else: methods = METHODS
            raw = read(row['raw_paths'][policy])
            packet = None if policy == 'none' else read(row['packet_paths'][policy])
            for method in methods:
                output = predict(raw, tab, packet, fold=method == 'R1_FOLD_CONTINUE')
                output['policy'] = policy
                write(args.run/'predictions'/method/policy/(ident+'.json'), output)
        print('REPAIRED', ident, round(time.perf_counter()-started, 2), flush=True)
    active[0] = False
    write(args.run/'worker-audit'/f'{args.shard}.json', {'ids': [r['id'] for r in rows],
          'actual_read_hook': True, 'opened_data_paths': sorted(set(opened)), 'forbidden_reads': forbidden})
    guard(args.run)


if __name__ == '__main__': main()
