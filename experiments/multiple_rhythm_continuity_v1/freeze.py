from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from .common import ROOT, CONFIG, METHODS, GATES, PRIMARY_READINGS, BROAD_READINGS, read, write, digest, stamp, code_hashes
from .worker import paths


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--stage', choices=['code', 'sources'], required=True)
    args = parser.parse_args()
    if args.stage == 'code':
        if (args.run / 'freeze.json').exists():
            raise RuntimeError('Cannot overwrite code freeze')
        if not read(args.run / 'controls.json')['all_pass']:
            raise RuntimeError('Pre-target controls failed')
        hashes = code_hashes()
        for name in hashes:
            target = args.run / 'code-snapshot' / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        write(args.run / 'freeze.json', {'at_utc': stamp(), 'code_hashes': hashes, 'config': CONFIG,
              'methods': METHODS, 'gates': GATES, 'primary_readings': PRIMARY_READINGS,
              'broad_readings': BROAD_READINGS, 'past_outcomes_known': True,
              'new_target_predictions_and_scores_not_read': True})
        print('CODE FROZEN', len(hashes), flush=True)
    else:
        from .common import guard
        guard(args.run); hashes = {}
        for row in read(args.run / 'source-inputs.json')['samples']:
            bank, table = paths(args.run, row)
            for path in (bank, table, args.run / 'source-unit' / f"{row['id']}.json"):
                hashes[str(path)] = digest(path)
        write(args.run / 'source-freeze.json', {'at_utc': stamp(), 'files': hashes,
                                               'source_prepared_before_numeric_proxy_encoding': True})
        print('SOURCES FROZEN', len(hashes), flush=True)


if __name__ == '__main__':
    main()
