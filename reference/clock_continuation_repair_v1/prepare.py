from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

from experiments.multiple_rhythm_continuity_v1.common import CONFIG as EVALUATION_CONFIG
from .common import ROOT, SOURCE, FIXED_COMPARISON, POLICIES, METHODS, read, write, digest, code_hashes, stamp


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    run = args.run or ROOT / 'data/research/runs/clock_continuation_repair_v1' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-v1')
    run.mkdir(parents=True, exist_ok=False)
    excluded = read(ROOT / 'data/samples/excluded-candidates.json')['candidates']
    sources = read(SOURCE / 'source-inputs.json')['samples']
    index = read(SOURCE / 'evaluation-index.json')['rows']
    current = {x['id']: x for x in read(ROOT / 'data/samples/catalog.json')['tracks']}
    hashes = {}
    for item in index:
        canonical = ROOT / 'data/samples' / current[item['original_id']]['reference']['path']
        if digest(canonical) != item['reference_sha256']:
            raise RuntimeError('Accepted reference changed since the comparison')
        if any(e.get('permanent_exclusion') and (item['original_id'] == e.get('id') or e.get('slug', '!') in str(canonical)) for e in excluded):
            raise RuntimeError('Excluded input')
        ref = Path(item['reference_path']); hashes[str(ref)] = digest(ref)
        target = run / 'references' / (item['id'] + '.json'); target.parent.mkdir(exist_ok=True)
        shutil.copy2(ref, target); item['reference_path'] = str(target)
    for row in sources:
        ident = row['id']
        row['bank_path'] = row.get('old_bank_path', str(SOURCE / 'banks' / (ident + '.json')))
        row['table_path'] = row.get('old_table_path', str(SOURCE / 'tables' / (ident + '.npz')))
        row['raw_paths'] = {p: str(SOURCE / 'raw-maps' / p / (ident + '.json')) for p in POLICIES}
        row['packet_paths'] = {p: str(SOURCE / 'encoded-units' / p / (ident + '.json')) for p in POLICIES if p != 'none'}
        for path in [row['bank_path'], row['table_path'], *row['raw_paths'].values(), *row['packet_paths'].values()]:
            hashes[path] = digest(path)
    for path in [SOURCE/'metrics.json', FIXED_COMPARISON/'metrics.json', FIXED_COMPARISON/'selection.json',
                 ROOT/'data/samples/catalog.json', ROOT/'data/samples/excluded-candidates.json']:
        hashes[str(path)] = digest(path)
    write(run/'source-inputs.json', {'samples': sources})
    write(run/'evaluation-index.json', {'rows': index})
    write(run/'input-freeze.json', {'at_utc': stamp(), 'files': hashes})
    write(run/'freeze.json', {'at_utc': stamp(), 'code_hashes': code_hashes(), 'evaluation_config': EVALUATION_CONFIG})
    for path in code_hashes():
        target = run/'code-snapshot'/path; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/path, target)
    write(run/'protocol.json', {'at_utc': stamp(), 'primary_method': 'R1_FOLD_CONTINUE', 'primary_policy': 'proxy100',
        'methods': METHODS, 'policies': POLICIES, 'evaluation_config': EVALUATION_CONFIG,
        'common_fixed_comparison_recordings': 13, 'complete_recordings': 33, 'actual_variable_recordings': 10,
        'model_seeded_diagnostic_excluded_from_main': True,
        'gap_repair_only_before_unchanged_local_octave_correction': True,
        'source_candidate_banks_and_accepted_references_unchanged': True,
        'no_audio_decoding_neural_inference_training_or_post_score_tuning': True,
        'same_unit_proxies_must_match': True,
        'continuity_contract': 'No missing output when a retained source-supported initial clock exists; hold physical rate and phase through every later gap; confidence never mutes clicks.',
        'full_meter_prediction_not_available': True,
        'compare_validity_coverage_changes_and_variable_tracking_separately': True})
    print('PREPARED', run, flush=True)


if __name__ == '__main__': main()
