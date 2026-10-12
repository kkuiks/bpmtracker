from __future__ import annotations

import argparse
import math
from pathlib import Path

from .common import read, write, guard, digest, stamp


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); guard(args.run)
    rows = read(args.run / 'source-inputs.json')['samples']; receipts, raw, hashes = [], [], {}
    if any(not (args.run / 'source-receipts' / f"{row['id']}.json").exists() for row in rows):
        raise RuntimeError('All source preparation must finish before encoding a tap')
    for row in rows:
        ident = row['id']; source = read(args.run / 'source-unit' / f'{ident}.json')
        reference = read(args.run / 'references' / f'{ident}.json'); packets = []
        for policy, ratio in [('proxy97', .97), ('proxy100', 1.), ('proxy103', 1.03)]:
            value = reference['initial_bpm'] * ratio; packet = dict(source)
            packet['power'] = math.floor(math.log2(value/source['base_bpm'])+.5) if source['available'] else None
            packets.append(packet); target = args.run / 'encoded-units' / policy / f'{ident}.json'
            write(target, packet); hashes[str(target)] = digest(target)
            raw.append({'id': ident, 'policy': policy, 'numeric_proxy': value})
        receipts.append({'id': ident, 'same_discrete_unit': packets[0] == packets[1] == packets[2],
                         'source_unit_available': source['available'],
                         'different_units_if_any_retained_as_initialization_sensitivity': True})
    write(args.run / 'raw-proxies.json', {'rows': raw})
    write(args.run / 'encoder-receipt.json', {'rows': receipts, 'actual_human_taps': False,
                                             'all_source_candidates_prepared_first': True})
    write(args.run / 'encoded-input-freeze.json', {'at_utc': stamp(), 'files': hashes})
    print('ENCODED', len(rows), flush=True)


if __name__ == '__main__':
    main()
