"""Initial reference-derived proxies only; later states never enter source work."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from .common import read, write, guard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    guard(args.run)
    receipt = []
    raw = []
    for row in read(args.run / 'source-inputs.json')['samples']:
        ident = row['id']
        source = read(row['source_unit_path'])
        ref = read(args.run / 'references' / f'{ident}.json')
        old = read(row['prior_packet100_path'])
        packets = []
        for policy, ratio in [('proxy97', .97), ('proxy100', 1.), ('proxy103', 1.03)]:
            value = ref['initial_bpm'] * ratio
            packet = dict(source)
            packet['power'] = math.floor(math.log2(value / source['base_bpm']) + .5) if source['available'] else None
            packets.append(packet)
            # Cached raw maps can be reused only when their discrete input is
            # exactly identical. No proxy numeric value enters a predictor.
            if packet != old:
                raise RuntimeError('New initial unit differs from cached baseline input: ' + ident)
            write(args.run / 'encoded-units' / policy / f'{ident}.json', packet)
            raw.append({'id': ident, 'policy': policy, 'numeric_proxy': value})
        receipt.append({'id': ident, 'all_three_packets_identical': packets[0] == packets[1] == packets[2],
                        'identical_to_cached_input_packet': True, 'available': source['available']})
    write(args.run / 'raw-proxies.json', {'rows': raw})
    write(args.run / 'encoder-receipt.json', {'rows': receipt, 'actual_human_taps': False,
                                             'numeric_values_discarded': True,
                                             'all_source_candidates_prepared_first': True})
    print('ENCODED', len(receipt), flush=True)


if __name__ == '__main__':
    main()
