"""Freeze all approved complete recordings; extras extend controls, not changes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from .common import ROOT, COMPOSITION, LAST, CONFIG, METHODS, GATES, PRIMARY_READINGS, BROAD_READINGS, read, write, digest, stamp
from .references import normalized, templates


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    run = (args.run or ROOT / 'data/research/runs/multiple_rhythm_continuity_v1' /
           (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-v1')).resolve()
    run.mkdir(parents=True, exist_ok=False)
    library = ROOT / 'data/samples'
    catalog_path = library / 'catalog.json'; excluded_path = library / 'excluded-candidates.json'
    catalog = read(catalog_path); exclusions = read(excluded_path)['candidates']
    tracks = [track for track in catalog['tracks'] if track['role'] == 'finished_recording_development']
    previous = {row['original_id']: row for row in read(COMPOSITION / 'evaluation-index.json')['rows'] if row['id'].startswith('r')}
    provenance = {row['id']: row for row in read(COMPOSITION / 'provenance.json')['rows']}
    fixed_inputs = {row['id']: row for row in read(library / 'selections/fixed-metronome-v1/all-valid-inference.json')['samples']}
    sources, evaluation, history = [], [], []
    frozen = {str(catalog_path): digest(catalog_path), str(excluded_path): digest(excluded_path),
              str(ROOT / 'data/models/final0.ckpt'): digest(ROOT / 'data/models/final0.ckpt')}
    extra = 0
    for track in tracks:
        original = track['id']; old = previous.get(original)
        ident = old['id'] if old else f'e{extra:03d}'
        if not old:
            extra += 1
        if any(item.get('permanent_exclusion') and (original == item.get('id') or item.get('slug', '!') in track['audio']['path'] or
               track['title'].casefold() == item.get('title', '!').casefold()) for item in exclusions):
            raise RuntimeError('Excluded input')
        audio_path = library / track['audio']['path']; ref_path = library / track['reference']['path']
        ref_bytes_hash = digest(ref_path)
        if track['reference'].get('sha256') and ref_bytes_hash != track['reference']['sha256']:
            raise RuntimeError('Reference differs from catalog')
        reference = normalized(track, read(ref_path))
        reference['permitted_reading_rules'] = templates(reference, PRIMARY_READINGS)
        reference['broad_diagnostic_reading_rules'] = templates(reference, PRIMARY_READINGS + BROAD_READINGS)
        write(run / 'references' / f'{ident}.json', reference)
        shutil.copy2(ref_path, run / 'references' / f'{ident}.original.json')
        frozen[str(ref_path)] = ref_bytes_hash
        row = {'id': ident, 'audio_path': str(audio_path), 'duration_seconds': track['duration_seconds'],
               'sample_rate': track['sample_rate'], 'sample_frames': track['sample_frames'],
               'channels': track.get('channels', 2), 'source_audio_sha256': track['audio'].get('sha256'),
               'reused_composition': bool(old)}
        if old:
            earlier = provenance[ident]
            if track['audio'].get('sha256') != earlier['audio_sha256']:
                raise RuntimeError('Current audio identity differs from reused observations')
            row.update({'old_bank_path': str(COMPOSITION / 'banks' / f'{ident}.json'),
                        'old_table_path': str(COMPOSITION / 'tables/expanded' / f'{ident}.npz'),
                        'old_unit_path': str(COMPOSITION / 'source-unit' / f'{ident}.json'),
                        'old_packet_path': str(COMPOSITION / 'encoded-units/proxy100' / f'{ident}.json'),
                        'old_raw_paths': {policy: str(COMPOSITION / 'predictions/M3_REGION_HOLD' / policy / f'{ident}.json')
                                          for policy in ('none', 'proxy100')}})
            for path in [row['old_bank_path'], row['old_table_path'], row['old_unit_path'], row['old_packet_path']] + list(row['old_raw_paths'].values()):
                frozen[path] = digest(path)
            source_binding = 'current catalog audio hash equals prior source receipt; no new original-audio rehash'
        else:
            current_hash = digest(audio_path)
            if row['source_audio_sha256'] and current_hash != row['source_audio_sha256']:
                raise RuntimeError('Newly included source audio differs from catalog')
            frozen[str(audio_path)] = current_hash
            cache = ROOT / 'data/research/state/experiment/metronome-v1/evidence' / f'{original}.npz'
            old_source = fixed_inputs.get(original)
            if cache.exists() and old_source and old_source['sample_rate'] == row['sample_rate'] and old_source['sample_frames'] == row['sample_frames']:
                row['cache_path'] = str(cache); frozen[str(cache)] = digest(cache)
                source_binding = 'official retained cache bound by same sample identity and source geometry; current recording hash verified'
            else:
                source_binding = 'fresh official final0 observation required; current recording hash verified'
        # Actual channel count comes from the source header, not any reference.
        import soundfile as sf
        info = sf.info(audio_path)
        if info.frames != row['sample_frames'] or info.samplerate != row['sample_rate']:
            raise RuntimeError('Current source geometry mismatch')
        row['channels'] = info.channels
        sources.append(row)
        qualification = track.get('qualification') or {}
        seeded = bool(qualification.get('derived_from_current_estimator_prediction'))
        evaluation.append({'id': ident, 'original_id': original, 'title': track['title'],
                           'role': reference['role'], 'partition': 'original21' if old else 'expanded12',
                           'model_seeded_reference_diagnostic_only': seeded, 'duration_seconds': track['duration_seconds'],
                           'reference_path': str(run / 'references' / f'{ident}.json'),
                           'canonical_reference_path': str(ref_path), 'reference_sha256': ref_bytes_hash,
                           'qualification': qualification, 'known_material_not_unseen': True})
        history.append({'id': ident, 'source_binding': source_binding, 'current_reference_path': track['reference']['path'],
                        'new_source_run': not bool(old), 'references_and_audio_unchanged': True})
    write(run / 'source-inputs.json', {'samples': sources})
    write(run / 'evaluation-index.json', {'rows': evaluation})
    write(run / 'provenance.json', {'rows': history})
    for path in (run / 'references').glob('*.json'):
        frozen[str(path)] = digest(path)
    write(run / 'input-freeze.json', {'at_utc': stamp(), 'files': frozen})
    write(run / 'protocol.json', {'created_at_utc': stamp(), 'config': CONFIG, 'methods': METHODS, 'gates': GATES,
        'primary_readings': PRIMARY_READINGS, 'broad_readings': BROAD_READINGS,
        'complete_recordings': len(sources), 'prior_inputs': sum(s['reused_composition'] for s in sources),
        'additional_complete_recordings': extra, 'total_audio_minutes': sum(s['duration_seconds'] for s in sources)/60,
        'current_reference_roles': {role: sum(r['role'] == role for r in evaluation) for role in ('variable', 'meter_control', 'fixed_control')},
        'model_seeded_diagnostic_inputs': sum(r['model_seeded_reference_diagnostic_only'] for r in evaluation),
        'no_individually_listening_confirmed_alternate_reference_claim': True,
        'extra_samples_do_not_increase_real_variable_song_count': True,
        'latest_algorithm_and_parameters_unchanged': True, 'new_sensor_runs_only_when_no_matching_cache': True,
        'full_time_signature_prediction_is_not_available_and_not_scored': True,
        'no_model_learning_app_changes_source_git_or_provider_acquisition': True,
        'cohort_and_policy_defined_before_new_target_scores': True})
    (run / 'preregistered-plan.ko.md').write_text('''# 복수 리듬 해석과 불필요한 변경을 분리하는 재평가\n\n가장 최근 실험의 5개 방법과 설정은 그대로 둔다. 기존21곡은 저장된 원음 후보·출력을 재사용하며, 승인된 완성곡33곡으로 확대한다. 추가12곡은 고정/변박 대조를 늘리며 실제 변속곡 수를 늘리지 않는다. 모델 예측에서 출발한 Dillinger1곡은 별도 진단으로만 보고한다. Juno는 새108 BPM 정답을 사용한다. 모든 자료는 과거에 접한 보유 음악이며 새 음악 일반화 검증이 아니다.\n\n주 평가의 허용 해석은 원래4분음표, 반·두 배(반속의 두 위치), 박자표 분모의 클릭,6/8·9/8·12/8의 큰 박과 그 큰 박을 둘로 나눈 해석이다. 실제 승인 맵의 음원 상대 시각과 마디 위치에서 일관된 후보를 만든다. 각 대체 맵을 사람이 새로 청취 승인했다는 주장은 하지 않는다. 이것은 사전에 정한 평가 규칙이다. 더 넓은3:2·4:3·3배·엇박 등의 해석은 민감도 진단으로 별도 보고한다.\n\n정답의 실제 BPM 또는 박자표가 바뀌기 전까지 한 구간 전체에서 같은 해석을 택한다. 모델 출력이 바뀌는 위치마다 정답을 새로 선택하지 않는다. 한 곡 전체에서 하나의 해석을 유지해야 하는 더 보수적인 점수도 함께 보고한다.\n\n원래 출력의 속도 변경과 큰 박 위치 변경을 환산 전에 센다. 실제 맵 변경 주변4초에서 같은 해석의 전후 속도·위치를 설명하는 변경은 음악을 따라간 변경이다. 그 외에 이미 맞던 해석을 바꾸거나 실제 작은 변속에서 불필요하게 반·두 배로 세는 방식까지 바꾸면 불필요한 변경으로 남긴다. 잘못된 클릭을 고치는 회복과 여전히 근거가 없는 변경은 분리한다. 작은 박 위치 보정도 원래 횟수를 공개한다.\n\n주 점수는 구간별로 일관된 해석과 맞는 클릭 시간에서 불필요 변경 뒤8초를 감점한 비율이다.4초·16초 감점은 설정 민감도이며 기본값을 결과 보고 바꾸지 않는다. 불필요 변경 횟수와 단순 순간별 허용 점수도 별도로 보여서 복수 정답이 불필요 교체를 지우지 못하도록 한다. 좋은 곡 판정에는 허용 클릭85% 이상·출력 커버리지95% 이상·불필요 변경0회를 요구한다.\n\n부품 효과 판단: 기존21곡 평균 주 점수+3%p 이상, 불필요 변경30% 이상 감소, 추가11개 비모델 대조군 및 실제 변속10곡 평균 하락1%p 이내. 기존 단일 정답 정확도는 현재 맵으로 별도 계산한다. 본 평가는 클릭 흐름에 관한 것이며 박자표를 출력하지 않은 방법에4/4까지 맞혔다고 점수를 주지 않는다. 새로운 추론 모델 학습·앱 반영·유료 수집·실제 재생 검증은 수행하지 않는다.\n''')
    write(run / 'entry-state.json', {'at_utc': stamp(), 'git_status': subprocess.run(
        ['git', 'status', '--short'], cwd=ROOT, text=True, capture_output=True, check=True).stdout})
    print('PREPARED', run, 'recordings', len(sources), 'extra', extra, flush=True)


if __name__ == '__main__':
    main()
