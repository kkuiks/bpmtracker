"""Retain the best already-scored clock in every source-derived unit group.

The original objective and tested clock coordinates stay unchanged. All broad
search and narrow-family scores compete, including candidates discarded while
narrowing around a single base. No label, genre or continuous hint is used.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path

from experiments.metronome_reconstruction_v1.hinted import select_from_family, validate_hint_row
from .inference import decorate, validate_source, write_json


def records(path):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        for line in handle:
            yield json.loads(line)


def prepare_family(original, scored):
    if original['status'] != 'audio_family_prepared':
        return original
    base = original['audio_base_bpm']
    config = original['config']
    groups = defaultdict(list)
    counts = defaultdict(int)
    radii = defaultdict(float)
    total = 0
    for record in scored:
        row = record['candidate']
        value = row['quarter_bpm']
        fraction = row['bpm_fraction']
        if not (config['bpm_min'] <= value <= config['bpm_max']
                and fraction['denominator'] <= config['denominator_max']
                and row['time_signature']['numerator'] in config['meters']
                and row['time_signature']['denominator'] == 4):
            raise ValueError('Tested clock violates the frozen output domain')
        power = math.floor(math.log2(value / base) + .5)
        center = base * 2 ** power
        radii[power] = max(radii[power], abs(value - center))
        counts[power] += 1
        total += 1
        # Preserve the winning score and twenty distinct rival summaries per
        # unit. The complete source trace remains the candidate audit record.
        ranked = groups[power]
        key = (value, row['time_signature']['numerator'],
               round(row['offset_seconds'] / row['period_seconds'])
               % row['time_signature']['numerator'])
        old = next((index for index, item in enumerate(ranked) if item[0] == key), None)
        if old is not None:
            if ranked[old][1]['score'] >= row['score']:
                continue
            ranked.pop(old)
        ranked.append((key, row))
        ranked.sort(key=lambda item: item[1]['score'], reverse=True)
        del ranked[20:]
    levels = []
    for power, ranked in sorted(groups.items()):
        values = [row for _, row in ranked]
        levels.append({'power': power, 'audio_center_bpm': base * 2 ** power,
                       'audio_neighbor_radius_bpm': radii[power],
                       'best': values[0], 'top_candidates': values,
                       'tested_clock_count': counts[power]})
    if not levels:
        raise ValueError('A prepared source trace contains no clock scores')
    return {**original, 'levels': levels,
            'method': 'all tested source clocks retained by discrete unit v1',
            'candidate_policy': 'union of all frozen broad-search and family scores',
            'tested_clock_count': total,
            'scores_recomputed': False, 'reference_fields_used': False,
            'time_signature_hint_accepted': False,
            'all_candidates_and_scores_prepared_before_hint': True}


def predict(family, hint=None):
    result = select_from_family(family, hint)
    return {**result, 'method': 'all tested source clocks retained by discrete unit v1',
            'original_clock_objective_unchanged': True,
            'reference_fields_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'select'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hints', type=Path)
    args = parser.parse_args()
    rows = json.loads((args.run / 'source-inputs.json').read_text())['samples']
    validate_source(rows)
    if args.stage == 'prepare':
        if args.output.exists():
            raise ValueError('Use a new method output')
        args.output.mkdir(parents=True)
        receipt = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
                   'reference_files_read': False, 'hint_files_read': False,
                   'source_run': str(args.run.resolve()), 'samples': []}
        for index, row in enumerate(rows, 1):
            ident = row['id']
            print(f'RETAIN {index}/{len(rows)} {ident}', flush=True)
            try:
                trace = json.loads((args.run / 'traces' / f'{ident}.json').read_text())
                if not trace['complete'] or trace['reference_fields_used'] or trace['numeric_hints_used']:
                    raise ValueError('A complete source-only trace is required')
                original = json.loads((args.run / 'families' / f'{ident}.json').read_text())
                family = prepare_family(original, records(args.run / 'traces' / f'{ident}.scores.jsonl.gz'))
                write_json(args.output / 'families' / f'{ident}.json', family)
                prediction = decorate(predict(family), row['duration_seconds'])
            except Exception as exc:
                prediction = {'status': 'inference_failed', 'error': f'{type(exc).__name__}: {exc}'}
            write_json(args.output / 'predictions/audio_only' / f'{ident}.json', prediction)
            receipt['samples'].append({'id': ident, 'status': prediction['status']})
        receipt['all_families_prepared_at_utc'] = datetime.now(timezone.utc).isoformat()
    else:
        receipt = json.loads((args.output / 'receipt.json').read_text())
        if 'all_families_prepared_at_utc' not in receipt or args.hints is None:
            raise ValueError('Prepared audio families and a separate hint file are required')
        hints = json.loads(args.hints.read_text())['samples']
        if len(hints) != len(rows) or {row['id'] for row in hints} != {row['id'] for row in rows}:
            raise ValueError('Source and hint identities differ')
        durations = {row['id']: row['duration_seconds'] for row in rows}
        for hint in hints:
            validate_hint_row(hint)
            try:
                family = json.loads((args.output / 'families' / f'{hint["id"]}.json').read_text())
                prediction = decorate(predict(family, hint['initial_quarter_bpm_tap']), durations[hint['id']])
            except Exception as exc:
                prediction = {'status': 'inference_failed', 'error': f'{type(exc).__name__}: {exc}'}
            write_json(args.output / 'predictions/correct_unit_diagnostic' / f'{hint["id"]}.json', prediction)
        receipt['unit_selection_completed_at_utc'] = datetime.now(timezone.utc).isoformat()
        receipt['reference_unit_hints_are_diagnostic'] = True
    write_json(args.output / 'receipt.json', receipt)


if __name__ == '__main__':
    main()
