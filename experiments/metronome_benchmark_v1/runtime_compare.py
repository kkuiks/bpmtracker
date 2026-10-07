"""Time two clock fitters on the same cached observations, without neural work."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time

import numpy as np

from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family, select_from_family
from experiments.metronome_reconstruction_v1.infer import make_evidence
from .inference import write_json
from .simple_clock import prepare_family, select


def coordinates(prediction):
    return {key: prediction.get(key) for key in ['status', 'quarter_bpm', 'time_signature', 'offset_seconds']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--simple', type=Path, required=True)
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new runtime result')
    rows = json.loads((args.run / 'source-inputs.json').read_text())['samples']
    rows = sorted(rows, key=lambda row: hashlib.sha256(('runtime-v1:' + row['id']).encode()).hexdigest())[:args.count]
    model = json.loads((args.run / 'model-config.json').read_text())
    simple = json.loads((args.simple / 'receipt.json').read_text())['configuration']
    results = []
    for index, row in enumerate(rows):
        with np.load(args.run / 'evidence' / f'{row["id"]}.npz', allow_pickle=False) as data:
            evidence = make_evidence(data['beat_logits'], data['downbeat_logits'], row['duration_seconds'], model)
        timings, matches = {}, {}
        order = ['frozen', 'simple'] if index % 2 == 0 else ['simple', 'frozen']
        for name in order:
            started = time.perf_counter()
            if name == 'frozen':
                prediction = select_from_family(prepare_audio_family(evidence, model))
                old = args.run
            else:
                prediction = select(prepare_family(evidence, model, simple))
                old = args.simple
            timings[name] = time.perf_counter() - started
            saved = json.loads((old / 'predictions/audio_only' / f'{row["id"]}.json').read_text())
            matches[name] = coordinates(prediction) == coordinates(saved)
        results.append({'id': row['id'], 'seconds': timings, 'saved_prediction_matches': matches,
                        'method_order': order})
        print(json.dumps(results[-1]), flush=True)
    summary = {name: {'sum_seconds': sum(row['seconds'][name] for row in results),
                     'median_seconds': statistics.median(row['seconds'][name] for row in results)}
               for name in ['frozen', 'simple']}
    write_json(args.output, {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'selected_count': len(rows),
        'selection': 'ten deterministic source-ID hashes; no outcome-based selection',
        'neural_inference_and_tracing_included': False, 'evidence_preprocessing_included': False,
        'references_read': False, 'timing_repetitions': 1, 'summary': summary, 'rows': results,
        'all_saved_predictions_match': all(all(row['saved_prediction_matches'].values()) for row in results)})


if __name__ == '__main__':
    main()
