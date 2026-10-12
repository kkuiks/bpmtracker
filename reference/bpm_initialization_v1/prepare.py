"""Reuse retained source evidence and take fresh, independent reference snapshots."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from experiments.bpm_continuity_v1.common import LEGACY, frozen_guard
from experiments.bpm_continuity_v1.prepare import accepted_reference
from .common import ROOT, BASELINE, CONFIG, METHODS, POLICIES, read, write, digest


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    frozen_guard(BASELINE)
    run = (args.run or ROOT / 'data/research/runs/bpm_initialization_v1' /
           (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-v1')).resolve()
    run.mkdir(parents=True, exist_ok=False)
    catalog_path = ROOT / 'data/samples/catalog.json'
    catalog = read(catalog_path)
    tracks = {t['id']: t for t in catalog['tracks']}
    excluded = read(ROOT / 'data/samples/excluded-candidates.json')['candidates']
    old_sources = {r['id']: r for r in read(BASELINE / 'source-worker-inputs.json')['samples']}
    old_provenance = {r['id']: r for r in read(BASELINE / 'source-manifest.json')['samples']}
    earlier_sources = {r['id']: r for r in read(LEGACY / 'source-inputs.json')['samples']}
    rows = [r for r in read(BASELINE / 'evaluation-manifest.json')['samples'] if r['role'] == 'fixed']
    sources = []; evaluation = []; provenance = []
    for row in rows:
        ident = row['id']; track = tracks[row['original_id']]
        if any(e.get('permanent_exclusion') and
               (row['original_id'] == e.get('id') or
                e.get('slug', 'NEVER') in track['audio']['path'] or
                track['title'].casefold() == e.get('title', '').casefold()) for e in excluded):
            raise ValueError('Permanently excluded source selected')
        source = old_sources[ident]
        destinations = {}
        for key, directory, suffix in [('evidence_path', 'source-evidence', '.npz'),
                                       ('bank_path', 'candidate-banks', '.json')]:
            target = run / directory / (ident + suffix); target.parent.mkdir(exist_ok=True)
            shutil.copy2(source[key], target); destinations[key] = str(target)
        family_path = Path(earlier_sources[ident].get('original_family_path',
                                                    LEGACY / 'new-original-families' / f'{ident}.json'))
        family = read(family_path)
        if not family.get('all_candidates_and_scores_prepared_before_hint'):
            raise ValueError('Whole-input family does not certify pre-hint preparation')
        if abs(family['input_duration_seconds'] - source['duration_seconds']) > .08:
            raise ValueError('Retained family duration differs from retained source')
        target = run / 'source-families' / f'{ident}.json'; target.parent.mkdir(exist_ok=True)
        shutil.copy2(family_path, target)
        destinations['family_path'] = str(target)
        for arm, policies in [('C_HOLD', (*POLICIES, 'oracle_start')),
                              ('C1_STATELESS', ('proxy_unit_zero',))]:
            for policy in policies:
                prior = BASELINE / 'predictions' / arm / policy / f'{ident}.json'
                destination = run / 'baseline-comparison/predictions' / arm / policy / f'{ident}.json'
                destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(prior, destination)
        for policy in POLICIES:
            for directory, suffix in [('bootstrap', '.json'), ('decision-traces/C_HOLD', '.jsonl.gz')]:
                prior = BASELINE / directory / policy / (ident + suffix)
                destination = run / 'baseline-comparison' / directory / policy / (ident + suffix)
                destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(prior, destination)
        sources.append(dict(id=ident, **destinations, duration_seconds=source['duration_seconds'], fps=50))
        reference_path = ROOT / 'data/samples' / track['reference']['path']
        normalized = accepted_reference(track, read(reference_path))
        if normalized['transitions'] or len({s['quarter_bpm'] for s in normalized['segments']}) != 1:
            raise ValueError('Fixed ablation contains a variable-rate reference')
        normalized_path = run / 'current-references' / f'{ident}.normalized.json'
        write(normalized_path, normalized)
        shutil.copy2(reference_path, run / 'current-references' / f'{ident}.json')
        evaluation.append(dict(row, reference_path=str(normalized_path),
                               source_reference_path=str(reference_path), reference_sha256=digest(reference_path)))
        previous = old_provenance[ident]
        provenance.append({'id': ident, 'inherited_audio_path': previous['audio_path'],
                           'inherited_audio_sha256': previous['audio_sha256'],
                           'audio_bytes_rehashed_this_run': False,
                           'current_catalog_audio_hash_matches_inherited':
                           track['audio'].get('sha256') in (None, previous['audio_sha256']),
                           'source_evidence_sha256': digest(destinations['evidence_path']),
                           'candidate_bank_sha256': digest(destinations['bank_path']),
                           'family_sha256': digest(target), 'retained_family_path': str(family_path),
                           'reference_sha256': digest(reference_path),
                           'reference_unchanged_since_baseline': digest(reference_path) == row['reference_sha256'],
                           'cache_provenance': previous['source_metadata'], 'fresh_neural_run': False})
        print('PREPARED', ident, flush=True)
    write(run / 'config.json', CONFIG)
    write(run / 'source-worker-inputs.json', {'samples': sources})
    write(run / 'source-manifest.json', {'samples': provenance, 'catalog_sha256': digest(catalog_path),
                                        'baseline_frozen_guard_passed': True})
    write(run / 'evaluation-manifest.json', {'samples': evaluation, 'catalog_sha256': digest(catalog_path)})
    protocol = {
        'version': '1.0', 'baseline': str(BASELINE), 'fixed_ids': [r['id'] for r in rows],
        'methods': METHODS, 'policies': POLICIES, 'downstream': 'unmodified C_HOLD, window 6 s',
        'method_rules': {
            'I0_LOCAL6': 'Exact reproduction of prior source bootstrap, six-second trailing window.',
            'I1_WHOLE_RATE_LOCAL6': 'Best already source-scored whole-input family level in the COMMON unit; '
                'take its exact fractional BPM only, then select a six-second locally qualified phase in the unchanged bank. '
                'No fallback if that rate is absent or cannot qualify.',
            'I2_LOCAL12': 'Twelve-second trailing initial window; earliest commitment t >= 12 s.',
            'I3_LOCAL24': 'Twenty-four-second trailing initial window; earliest commitment t >= 24 s.'},
        'long_window_commit_rule': 'Long-window seed qualifications AND six-second downstream output qualifications; '
                                   'same bank indexing, deadline 30 s, no retrospective filling.',
        'unit_rule': 'All methods use the six-second source base and identical encoded integer powers. '
                     'Translate whole-input family levels into this base; do not reuse family powers blindly.',
        'whole_input_limitation': 'Fixed-song diagnostic with whole-song lookahead. Reported seed time is an '
                                 'offline timeline property, never an online latency claim.',
        'all_methods_offline': 'The retained sensor/candidate/phase banks also use whole-input information; '
                               'long-window comparisons alone cannot certify streaming inference.',
        'full_support': 'Same current approved support; waiting, NO_SEED, UNKNOWN and every failed input retained.',
        'no_tuning': 'No per-song winner, rounding rule, threshold selection or candidate changes after scores.',
        'primary_policy': 'proxy_unit_zero; minus/plus five percent are identity diagnostics, not 24 independent songs.',
        'actual_human_taps_collected': False, 'reference_use': 'Unit adapter and post-prediction evaluator only.',
        'gates': {'macro_clock_correct_min': .80,
                  'macro_quarter_f1_min': .774362570538882,
                  'each_song_clock_drop_max_vs_I0': .05,
                  'every_gate_required': True,
                  'quarter_f1_baseline': 'Frozen C1_STATELESS/proxy_unit_zero, eight fixed inputs, rescored if references change',
                  'per_song_baseline': 'I0_LOCAL6/proxy_unit_zero (prior C_HOLD proxy)'},
        'secondary_analysis': ['seed exact rate and phase', 'waiting versus post-seed loss',
            'strict 20/30/70ms and actual emitted-quarter F1', 'near-rate group rivals',
            'per-song differences, whole-input limitations and candidate availability'],
        'out_of_scope': ['variable-tempo experiments', 'near-rate correction', 'phase bank expansion',
                         'new audio, model training, app integration', 'source Git staging/commit/push']}
    write(run / 'protocol.json', protocol)
    status = subprocess.run(['git', 'status', '--short'], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    write(run / 'receipts/entry-state.json', {'source_status': status,
                                              'source_git_mutations_performed': False})
    print('RUN', run, flush=True)


if __name__ == '__main__':
    main()
