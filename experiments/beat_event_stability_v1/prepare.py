"""Freeze a new comparison while retaining the already source-prepared parent."""
import argparse
from pathlib import Path
import shutil
from .common import (ROOT, PARENT, CONFIG, METHODS, POLICIES, PILOT_IDS,
                     read, write, digest, code_hashes, stamp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--methods', nargs='+', choices=list(METHODS), default=list(METHODS))
    args = parser.parse_args()
    run = args.run
    run.mkdir(parents=True, exist_ok=False)
    index = read(PARENT / 'evaluation-index.json')['rows']
    if args.pilot:
        index = [r for r in index if r['id'] in PILOT_IDS]
    ids = {r['id'] for r in index}
    sources = [r for r in read(PARENT / 'source-inputs.json')['samples'] if r['id'] in ids]
    hashes = {}
    selected = []
    for item in index:
        canonical = item['canonical_reference_path']
        if digest(canonical) != item['reference_sha256']:
            raise RuntimeError('Accepted reference changed')
        # The evaluator's derived reference has different serialization/schema
        # from the canonical owner map; do not compare their byte hashes.
        for path in (canonical, item['reference_path']):
            hashes[path] = digest(path)
        target = run / 'references' / (item['id'] + '.json')
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(item['reference_path'], target)
        selected.append({**item, 'reference_path': str(target.resolve())})
    for row in sources:
        for key in ('events_path', 'family_path'):
            if row.get(key):
                hashes[row[key]] = digest(row[key])
        ident = row['id']
        target = run / 'prepared-source' / (ident + '.json')
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(PARENT / 'prepared-source' / (ident + '.json'), target)
        hashes[str(target.resolve())] = digest(target)
    write(run / 'source-inputs.json', {'samples': sources, 'source_only_parent': str(PARENT),
          'old_time_window_banks_or_tables_used': False})
    write(run / 'evaluation-index.json', {'rows': selected})
    write(run / 'input-freeze.json', {'at_utc': stamp(), 'files': hashes,
          'original_audio_geometry_and_hashes_reused_from_parent_receipts': True})
    # Preserve parent source-before-tap lineage; encoding is reused only afterwards.
    write(run / 'source-before-tap-freeze' / 'reused.json', {
        'files': {str((run / 'prepared-source' / (r['id'] + '.json')).resolve()):
                  digest(run / 'prepared-source' / (r['id'] + '.json')) for r in sources},
        'source_prepared_before_initial_tap_in_parent': True})
    for policy in POLICIES:
        for row in sources:
            target = run / 'encoded-units' / policy / (row['id'] + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PARENT / 'encoded-units' / policy / (row['id'] + '.json'), target)
            hashes[str(target.resolve())] = digest(target)
    write(run / 'input-freeze.json', {'at_utc': stamp(), 'files': hashes,
          'original_audio_geometry_and_hashes_reused_from_parent_receipts': True})
    write(run / 'freeze.json', {'at_utc': stamp(), 'config': CONFIG,
          'methods': METHODS, 'code_hashes': code_hashes()})
    for path in code_hashes():
        target = run / 'code-snapshot' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    write(run / 'protocol.json', {
        'at_utc': stamp(), 'scope': 'pilot' if args.pilot else 'complete_known_cohort',
        'recordings': len(selected), 'selected_methods': args.methods,
        'config': CONFIG, 'methods': METHODS, 'policies': POLICIES,
        'primary_target': 'fixed12 excluding Red Miso: joint valid pulse/bar map without unnecessary changes',
        'expanded_fixed_group_and_variable_meter_regressions_required': True,
        'known_development_material_not_unseen': True,
        'no_reference_role_or_song_identity_in_inference': True,
        'no_constant_tempo_fallback_or_window_search': True,
        'initial_taps': 'same frozen -3%, nominal, +3% source-unit packets; numeric discarded',
        'sources_and_proxies_unchanged': True, 'no_evaluation_read_in_source_workers': True,
        'reading_set_and_unnecessary_change_penalty_unchanged': True,
        'accepted_references_and_past_runs_unchanged': True,
        'app_adoption': False,
        'success_rule': 'Improve fixed12 joint score and false changes; report all prior-good and real-change regressions separately.',
    })
    print('PREPARED', run, len(selected), args.methods, flush=True)


if __name__ == '__main__':
    main()
