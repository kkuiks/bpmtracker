"""Replay the frozen clock fitter on cached source observations with tracing.

No neural inference, reference preparation or hint selection occurs here.
This supplies the complete source-candidate record for additional methods.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import numpy as np

from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
from experiments.metronome_reconstruction_v1.infer import make_evidence
from .inference import decorate, validate_source, write_json
from .trace import CandidateTrace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new replay output')
    rows = json.loads(args.source.read_text())['samples']
    validate_source(rows)
    config = json.loads(args.config.read_text())
    args.output.mkdir(parents=True)
    shutil.copyfile(args.source, args.output / 'source-inputs.json')
    shutil.copyfile(args.config, args.output / 'model-config.json')
    receipt = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'reference_files_read': False, 'hint_files_read': False,
               'neural_inference_repeated': False, 'cached_evidence': str(args.evidence.resolve()),
               'samples': []}
    for index, row in enumerate(rows, 1):
        ident = row['id']
        print(f'REPLAY {index}/{len(rows)} {ident}', flush=True)
        started = time.perf_counter()
        try:
            with np.load(args.evidence / f'{ident}.npz', allow_pickle=False) as data:
                if int(data['fps']) != config['fps'] or abs(float(data['duration_seconds']) - row['duration_seconds']) > 1e-8:
                    raise ValueError('Cached observation coordinates differ from source contract')
                evidence = make_evidence(data['beat_logits'], data['downbeat_logits'], row['duration_seconds'], config)
            with CandidateTrace(args.output / 'traces', ident) as trace:
                family = prepare_audio_family(evidence, config)
                prediction = decorate(select_from_family(family), row['duration_seconds'])
                trace.finish(family, prediction)
            write_json(args.output / 'families' / f'{ident}.json', family)
        except Exception as exc:
            prediction = {'status': 'inference_failed', 'error': f'{type(exc).__name__}: {exc}'}
        write_json(args.output / 'predictions/audio_only' / f'{ident}.json', prediction)
        receipt['samples'].append({'id': ident, 'status': prediction['status'], 'seconds': time.perf_counter() - started})
        write_json(args.output / 'receipt.json', receipt)
    receipt['all_families_prepared_at_utc'] = datetime.now(timezone.utc).isoformat()
    write_json(args.output / 'receipt.json', receipt)


if __name__ == '__main__':
    main()
