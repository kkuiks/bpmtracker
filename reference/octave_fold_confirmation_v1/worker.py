"""Source-only correction worker; existing maps and clocks are immutable."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import numpy as np

from .common import METHODS, read, write, guard
from .correct import apply


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--shards', type=int, default=1)
    args = parser.parse_args()
    guard(args.run)
    rows = read(args.run / 'source-inputs.json')['samples'][args.shard::args.shards]
    opened, forbidden = [], []
    active = [False]

    def audit(event, arguments):
        if event != 'open' or not active[0] or not isinstance(arguments[0], (str, bytes)):
            return
        value = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        mode = arguments[1] if isinstance(arguments[1], str) else ''
        if any(character in mode for character in 'wax+') or Path(value).suffix not in ('.json', '.npz'):
            return
        opened.append(value)
        if any(token in value.lower() for token in ('/references/', 'evaluation-index', 'catalog.json',
                                                    'raw-proxies', 'acceptance.json')):
            forbidden.append(value)
            raise RuntimeError('Forbidden evaluation read in source worker')

    sys.addaudithook(audit)
    active[0] = True
    try:
        for row in rows:
            started = time.perf_counter()
            ident = row['id']
            with np.load(row['table_path'], allow_pickle=False) as arrays:
                tab = {name: arrays[name].copy() for name in ('time', 'quality', 'seed_count')}
            tab['clocks'] = read(row['bank_path'])['expanded']
            raw_maps = {policy: read(path) for policy, path in row['raw_predictions'].items()}
            for method, options in METHODS.items():
                policies = ['none', 'proxy100'] + (['proxy97', 'proxy103'] if method == 'F1_FOLD05' else [])
                for policy in policies:
                    base = 'none' if policy == 'none' else 'proxy100'
                    if policy != 'none':
                        packet = read(args.run / 'encoded-units' / policy / f'{ident}.json')
                        if packet != read(row['prior_packet100_path']):
                            raise RuntimeError('Cached map discrete input mismatch')
                    output = apply(raw_maps[base], tab, method, options)
                    output['policy'] = policy
                    write(args.run / 'predictions' / method / policy / f'{ident}.json', output)
            print('CORRECTED', ident, round(time.perf_counter() - started, 2), flush=True)
    finally:
        active[0] = False
    write(args.run / 'worker-audit' / f'{args.shard}.json', {
        'actual_data_read_hook': True, 'opened_data_paths': sorted(set(opened)),
        'forbidden_reads': forbidden, 'ids': [row['id'] for row in rows],
        'not_an_OS_sandbox_claim': True,
    })
    guard(args.run)


if __name__ == '__main__':
    main()
