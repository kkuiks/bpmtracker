"""Select all additional approved fixed inputs and all unused reserved groups."""
import argparse
from pathlib import Path
from collections import Counter
import shutil
import soundfile as sf
from experiments.multiple_rhythm_continuity_v1.references import normalized
from tools.project_storage import resolve_path
from .common import (ROOT, CANDIDATE, GTZAN, FIXED, CONFIG, PRIMARY, read, write,
                     digest, stamp, code_hashes, candidate_hashes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    frozen = read(CANDIDATE / 'freeze.json')
    if frozen['code_hashes'] != candidate_hashes() or frozen['config'] != CONFIG:
        raise RuntimeError('Candidate drift before cohort selection')
    old_ids = {r['original_id'] for r in read(CANDIDATE / 'evaluation-index.json')['rows']}
    history = {r['id']: r for r in read(FIXED / 'evaluation-manifest.json')['samples']}
    excluded = read(ROOT / 'data/samples/excluded-candidates.json')['candidates']
    sources, index, qualification, hashes = [], [], [], {}
    for track in read(ROOT / 'data/samples/catalog.json')['tracks']:
        if track['id'] in old_ids:
            continue
        if any(r.get('permanent_exclusion') and (
                track['id'] == r.get('id') or r.get('slug', '!') in track['audio']['path'])
               for r in excluded):
            raise RuntimeError('Excluded recording')
        audio = ROOT / 'data/samples' / track['audio']['path']
        canonical = ROOT / 'data/samples' / track['reference']['path']
        ref = normalized(track, read(canonical))
        qualification.append({'id': track['id'], 'role': track['role'],
                              'fixed': ref['role'] == 'fixed_control'})
        if ref['role'] != 'fixed_control':
            continue
        ident = f'n{len(sources):03d}'
        info = sf.info(str(audio))
        ahash = digest(audio)
        if track['audio'].get('sha256') != ahash:
            raise RuntimeError('Approved audio changed: ' + track['id'])
        if abs(info.duration - track['duration_seconds']) > 1e-6:
            raise RuntimeError('Approved audio geometry changed')
        hashes[str(audio)] = ahash
        hashes[str(canonical)] = digest(canonical)
        cache = ROOT / 'data/research/state/experiment/metronome-v1/evidence' / (track['id'] + '.npz')
        family = FIXED / 'source-families' / (track['id'] + '.json')
        cached_identity = history.get(track['id'], {}).get('audio', {}).get('sha256') == ahash
        use_cache = cache.is_file() and cached_identity
        if use_cache:
            hashes[str(cache)] = digest(cache)
        if family.is_file() and cached_identity:
            hashes[str(family)] = digest(family)
        else:
            family = None
        cohort = ('additional_real_excerpts' if track['role'] == 'formal_original_recording_excerpt'
                  else 'additional_formal_synthetic' if track['role'] == 'formal_synthetic_recording'
                  else 'auxiliary_guitar' if track['role'] == 'auxiliary_solo_guitar'
                  else 'auxiliary_synthetic')
        sources.append({'id': ident, 'audio_path': str(audio), 'sample_rate': info.samplerate,
                        'sample_frames': info.frames, 'channels': info.channels,
                        'duration_seconds': info.duration, 'source_audio_sha256': ahash,
                        'cache_path': str(cache) if use_cache else None,
                        'cache_family_path': str(family) if family else None})
        target = run / 'references' / (ident + '.json')
        write(target, ref)
        hashes[str(target)] = digest(target)
        index.append({'id': ident, 'original_id': track['id'], 'title': track['title'],
                      'cohort': cohort, 'role': 'fixed_control', 'genre': 'owner-reviewed source',
                      'reference_path': str(target), 'canonical_reference_path': str(canonical),
                      'reference_sha256': digest(canonical), 'duration_seconds': info.duration,
                      'qualification': track.get('qualification', {}),
                      'not_used_in_candidate_tuning': True, 'known_original_estimator_material': True,
                      'model_seeded_reference_diagnostic_only': False,
                      'complete_song': False, 'waveform_available': True})
    rows = read(GTZAN / 'qualification.json')['rows']
    seen = set()
    feature = resolve_path(next(r['spectrogram_path'] for r in rows if r.get('eligible')))
    hashes[str(feature)] = digest(feature)
    for row in sorted(rows, key=lambda r: r['id']):
        if not row.get('eligible') or row.get('role') != 'reserved' or row['parent_group'] in seen:
            continue
        seen.add(row['parent_group'])
        ident = f'g{len(seen)-1:03d}'
        raw_path = GTZAN / 'references' / (row['id'] + '.json')
        raw = read(raw_path)
        start, end = raw['support_seconds']
        ref = {'support': [[start, end]], 'quarters': raw['beat_times_seconds'],
               'bars': raw['downbeat_times_seconds'],
               'states': [{'start': start, 'end': end, 'bpm': raw['pulse_bpm'],
                           'numerator': raw['bar_pulse_count'], 'denominator': 4}],
               'segments': [{'start_seconds': start, 'end_seconds': end,
                             'quarter_bpm': raw['pulse_bpm']}],
               'transitions': [], 'initial_bpm': raw['pulse_bpm'], 'role': 'fixed_control',
               'additional_offset_applied_seconds': 0,
               'annotation_pulse_as_quarter_is_diagnostic_not_verified_notation': True}
        target = run / 'references' / (ident + '.json')
        write(target, ref)
        hashes[str(target)] = digest(target)
        hashes[str(raw_path)] = digest(raw_path)
        sources.append({'id': ident, 'spectrogram_path': str(feature),
                        'spectrogram_key': row['spectrogram_key'],
                        'spectrogram_frames': row['spectrogram_frames'], 'mel_bands': row['mel_bands'],
                        'fps': row['fps'], 'duration_seconds': row['duration_seconds'],
                        'feature_sha256': row['feature_sha256'], 'cache_path': None,
                        'cache_family_path': None})
        index.append({'id': ident, 'original_id': row['id'], 'title': row['id'],
                      'cohort': 'reserved_features', 'role': 'fixed_control', 'genre': row['genre'],
                      'reference_path': str(target), 'canonical_reference_path': str(raw_path),
                      'reference_sha256': digest(raw_path), 'duration_seconds': row['duration_seconds'],
                      'qualification': raw, 'parent_group': row['parent_group'],
                      'not_used_in_candidate_tuning': True, 'previous_fitter_inference': False,
                      'model_seeded_reference_diagnostic_only': False,
                      'complete_song': False, 'waveform_available': False,
                      'pcm_channel_unavailable_not_synthesized_from_neural_events': True})
    checkpoint = ROOT / 'data/models/final0.ckpt'
    hashes[str(checkpoint)] = digest(checkpoint)
    write(run / 'source-inputs.json', {'samples': sources})
    write(run / 'evaluation-index.json', {'rows': index})
    write(run / 'qualification.json', {'additional_catalog_rows': qualification,
          'selection_before_predictions': True, 'reserved_unique_groups': len(seen)})
    write(run / 'input-freeze.json', {'at_utc': stamp(), 'files': hashes})
    write(run / 'freeze.json', {'at_utc': stamp(), 'config': CONFIG, 'code_hashes': code_hashes(),
                              'candidate_code_hashes': candidate_hashes()})
    for path in code_hashes():
        target = run / 'code-snapshot' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    write(run / 'protocol.json', {'at_utc': stamp(), 'candidate': str(CANDIDATE),
          'primary_method': PRIMARY, 'comparison_method': 'ORIGINAL_FIXED_UNIT',
          'policies': ['proxy97', 'proxy100', 'proxy103'],
          'cohorts': dict(Counter(r['cohort'] for r in index)),
          'genres': dict(Counter(r['genre'] for r in index if r['cohort'] == 'reserved_features')),
          'no_parameter_search_or_algorithm_changes': True,
          'no_reference_changes_or_post_prediction_exclusions': True,
          'source_preparation_before_tap': True, 'initial_tap_proxy_percent': 3,
          'waveform_and_feature_results_must_remain_separate': True,
          'feature_missing_PCM_is_a_limit_on_full_waveform_generalization_claims': True,
          'existing_qualified_reserved_role_consumption_authorized_by_current_validation_request': True,
          'historical_reserved_descriptors_and_runs_unchanged': True,
          'artist_and_checkpoint_training_independence_not_verified': True,
          'approval_target': 'Assess whether the previous approximately 99% joint score maintains on additional fixed sources; no formal product threshold invented.',
          'app_adoption': False})
    print('PREPARED', run, len(sources), dict(Counter(r['cohort'] for r in index)), flush=True)


if __name__ == '__main__':
    main()
