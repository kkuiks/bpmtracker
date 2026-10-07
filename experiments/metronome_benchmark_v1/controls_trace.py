"""Focused invariance and completeness checks for source-only tracing."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import tempfile

import numpy as np

from experiments.metronome_reconstruction_v1 import infer, hinted
from .inference import write_json
from .trace import CandidateTrace


def fixture(bpm, meter, weak=False):
    duration, offset = 20.0, .137
    t = np.arange(int(duration * 50)) / 50
    period = 60 / bpm
    beat = np.full(len(t), -8.0)
    down = np.full(len(t), -8.0)
    for index, position in enumerate(np.arange(offset, duration, period)):
        if not (weak and index % 9 == 5):
            beat += 17 * np.exp(-.5 * ((t - position) / .015) ** 2)
        if index % meter == 0:
            down += (11 if weak else 17) * np.exp(-.5 * ((t - position) / .015) ** 2)
    return beat, down, duration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(Path('experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    cases = []
    def check(name, value):
        if not value:
            raise AssertionError(name)
        cases.append({"name": name, "passed": True})
    with tempfile.TemporaryDirectory(prefix='joljak-clock-trace-') as temp:
        directory = Path(temp)
        for index, (bpm, meter, weak) in enumerate([(120, 4, False), (83 + 1 / 3, 3, True)], 1):
            evidence = infer.make_evidence(*fixture(bpm, meter, weak), config)
            ordinary = hinted.prepare_audio_family(evidence, config)
            original_score = infer.score_candidate
            ident = f'fixture{index}'
            with CandidateTrace(directory, ident) as recorder:
                traced = hinted.prepare_audio_family(evidence, config)
                recorder.finish(traced, hinted.select_from_family(traced))
            check(f'{ident}:complete_family_identical', traced == ordinary)
            check(f'{ident}:automatic_prediction_identical', hinted.select_from_family(traced) == hinted.select_from_family(ordinary))
            check(f'{ident}:unit_prediction_identical', hinted.select_from_family(traced, bpm) == hinted.select_from_family(ordinary, bpm))
            check(f'{ident}:functions_restored', infer.score_candidate is original_score and hinted.score_candidate is original_score)
            summary = json.loads((directory / f'{ident}.json').read_text())
            with gzip.open(directory / f'{ident}.scores.jsonl.gz', 'rt') as stream:
                records = [json.loads(line) for line in stream]
            check(f'{ident}:all_score_calls_recorded', summary['complete'] and len(records) == summary['score_count']
                  and [row['score_id'] for row in records] == list(range(1, len(records) + 1)))
            check(f'{ident}:pruned_candidates_preserved', any(block['scores'] > block['retained_count'] for block in summary['blocks']))
            ids = {row['score_id'] for row in records}
            check(f'{ident}:refinement_parent_preserved', any(row['parent_score_id'] for row in records)
                  and all(row['parent_score_id'] is None or row['parent_score_id'] in ids for row in records)
                  and all(row['stage'] != 'unclassified' for row in records))
            check(f'{ident}:every_original_candidate_value_preserved', all(row['candidate']['time_signature']['denominator'] == 4
                  and row['candidate']['bpm_fraction']['denominator'] <= 4 for row in records))
    write_json(args.output, {"purpose":"Trace invariance and completeness; not music accuracy", "cases":cases,"passed":True})
    print(f'PASS {len(cases)} trace controls', flush=True)


if __name__ == '__main__':
    main()
