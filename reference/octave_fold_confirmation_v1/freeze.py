from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from .common import ROOT, CONFIG, METHODS, GATES, read, write, stamp, code_hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    if (args.run / 'freeze.json').exists() or (args.run / 'predictions').exists():
        raise RuntimeError('Do not overwrite a frozen experiment')
    if not read(args.run / 'controls.json')['all_mechanics_pass']:
        raise RuntimeError('Controls not passed')
    hashes = code_hashes()
    for name in hashes:
        target = args.run / 'code-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    write(args.run / 'freeze.json', {'at_utc': stamp(), 'code_hashes': hashes,
                                    'config': CONFIG, 'methods': METHODS, 'gates': GATES,
                                    'no_new_target_scores_before_freeze': True,
                                    'past_known_target_outcomes_were_available': True})
    print('FROZEN', len(hashes), 'code files', flush=True)


if __name__ == '__main__':
    main()
