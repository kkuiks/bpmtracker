"""Prepare immutable source inputs and separate current evaluation references."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from experiments.variable_clock_composition_v1.prepare import normalize
from experiments.variable_clock_composition_v1.common import guard as prior_guard
from .common import ROOT, PRIOR, CONFIG, METHODS, GATES, read, write, digest, stamp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    run = (args.run or ROOT / 'data/research/runs/octave_fold_confirmation_v1' /
           (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-v1')).resolve()
    run.mkdir(parents=True, exist_ok=False)
    prior_guard(PRIOR)
    catalog_path = ROOT / 'data/samples/catalog.json'
    excluded_path = ROOT / 'data/samples/excluded-candidates.json'
    catalog = read(catalog_path)
    tracks = {track['id']: track for track in catalog['tracks']}
    exclusions = read(excluded_path)['candidates']
    sources, evaluation, provenance = [], [], []
    frozen_inputs = {str(catalog_path): digest(catalog_path), str(excluded_path): digest(excluded_path)}
    old_inputs = read(PRIOR / 'input-freeze.json')['files']
    old_provenance = {row['id']: row for row in read(PRIOR / 'provenance.json')['rows']}
    rows = [row for row in read(PRIOR / 'evaluation-index.json')['rows'] if row['id'].startswith('r')]
    for row in rows:
        ident = row['id']
        track = tracks[row['original_id']]
        if any(item.get('permanent_exclusion') and
               (track['id'] == item.get('id') or item.get('slug', '!') in track['audio']['path'] or
                track['title'].casefold() == item.get('title', '!').casefold()) for item in exclusions):
            raise RuntimeError('Excluded sample selected')
        old = old_provenance[ident]
        if track['audio'].get('sha256') and track['audio']['sha256'] != old['audio_sha256']:
            raise RuntimeError('Catalog audio identity differs from retained source observations')
        bank = PRIOR / 'banks' / f'{ident}.json'
        table = PRIOR / 'tables/expanded' / f'{ident}.npz'
        unit = PRIOR / 'source-unit' / f'{ident}.json'
        raw = {policy: str(PRIOR / 'predictions/M3_REGION_HOLD' / policy / f'{ident}.json')
               for policy in ('none', 'proxy100')}
        packet = PRIOR / 'encoded-units/proxy100' / f'{ident}.json'
        for path in [bank, table, unit, packet] + [Path(value) for value in raw.values()]:
            actual = digest(path)
            relative = str(path.relative_to(PRIOR))
            if relative in old_inputs and old_inputs[relative] != actual:
                raise RuntimeError('Retained input changed: ' + relative)
            frozen_inputs[str(path)] = actual
        sources.append({'id': ident, 'duration_seconds': row['duration_seconds'],
                        'bank_path': str(bank), 'table_path': str(table), 'source_unit_path': str(unit),
                        'raw_predictions': raw, 'prior_packet100_path': str(packet)})
        ref_path = ROOT / 'data/samples' / track['reference']['path']
        actual_ref_hash = digest(ref_path)
        if track['reference'].get('sha256') and track['reference']['sha256'] != actual_ref_hash:
            raise RuntimeError('Current reference differs from catalog identity')
        frozen_inputs[str(ref_path)] = actual_ref_hash
        (run / 'references').mkdir(exist_ok=True)
        shutil.copy2(ref_path, run / 'references' / f'{ident}.original.json')
        write(run / 'references' / f'{ident}.json', normalize(track, read(ref_path)))
        evaluation.append({**row, 'title': track['title'],
                           'reference_path': str(run / 'references' / f'{ident}.json'),
                           'current_canonical_reference_path': str(ref_path),
                           'reference_sha256': actual_ref_hash,
                           'qualification': track.get('qualification', {}),
                           'known_material_not_unseen_evaluation': True})
        provenance.append({'id': ident, 'original_id': track['id'],
                           'audio_sha256_from_catalog_and_prior_receipt': old['audio_sha256'],
                           'original_audio_rehashed_or_decoded_this_run': False,
                           'source_bank_and_tables': str(PRIOR),
                           'current_reference_matches_prior': actual_ref_hash == old['reference_sha256'],
                           'raw_map_source_method': 'M3_REGION_HOLD',
                           'raw_map_boundaries_are_source_derived': True})
    write(run / 'source-inputs.json', {'samples': sources})
    write(run / 'evaluation-index.json', {'rows': evaluation})
    write(run / 'provenance.json', {'rows': provenance, 'source_preparation_finished_before_new_tap_encoding': True})
    for path in (run / 'references').glob('*.json'):
        frozen_inputs[str(path)] = digest(path)
    write(run / 'input-freeze.json', {'at_utc': stamp(), 'files': frozen_inputs})
    roles = dict(Counter(row['role'] for row in evaluation))
    write(run / 'protocol.json', {
        'created_at_utc': stamp(), 'config': CONFIG, 'methods': METHODS, 'gates': GATES,
        'cohort_role_counts': roles, 'complete_recording_minutes': sum(row['duration_seconds'] for row in rows) / 60.,
        'cached_observations_and_source_maps': True, 'new_neural_inference_or_learning': False,
        'current_references_only_for_initial_unit_encoder_and_later_scoring': True,
        'known_previous_outcomes_informed_hypothesis_not_unseen_confirmation': True,
        'source_bank_interval_edges_and_emission_scores_unchanged': True,
        'component_probe_not_new_complete_clock_selector': True,
        'near_2x_and_half_only_not_general_change_magnitude': True,
        'true_octave_change_risk_reported_in_full_denominators': True,
        'all_twenty_one_recordings_retained': True,
        'initial_tap_tolerance_percent': 3, 'actual_human_taps_collected': False,
        'source_candidate_quality_threshold_is_not_tap_tolerance': True,
        'phase_choices_are_existing_source_clocks_not_numeric_division_only': True,
        'app_integration': False, 'source_git_mutations': False,
    })
    plan = '''# 두 배·절반 오류 보호 확인 실험\n\n기존 M3의 원음 기반 후보·근거·출력 경계를 그대로 보존하고, 출력 구간을 시간순으로 읽는 작은 보정 부품만 비교한다. 기존 BPM을 중심으로 곡 전체를 제한하지 않는다. 새 후보가 직전 선택 속도의 약 두 배·절반일 때만 재검토한다. 다른 비율의 변속은 이 규칙으로 제한하지 않는다.\n\n기본 보정은 2배·절반 후보를 환산한 속도가 직전 속도와 5% 이내일 때 발동한다. 이 5%는 시작 탭 ±3%와 다른 값이다. 환산한 속도·박 위치에 맞는 기존 음원 후보가 있고 근거가 있으면 그 후보를 선택한다. 후보가 없거나 근거가 부족하면 직전 시계의 BPM과 위상을 유지한다. 음원에 없는 정답 후보를 새로 만들어 넣지 않는다. 3%·8% 범위는 미리 정한 민감도 대조이며 결과를 보고 기본값을 바꾸지 않는다.\n\n비교: 원래 출력, 배수 변경 차단 후 기존 속도 유지, 환산 후보 선택(기본 5%, 대조 3%·8%). 변속 11곡·변박 4곡·고정 대조 6곡 모두 평가한다. 이미 여러 번 분석한 실제 21곡이며 새 곡 일반화의 증거가 아니다. 진짜 두 배 변경이 있는 Juno를 포함하고 실패를 제거하지 않는다.\n\n전체 변속곡에서 맞는 BPM·박 위치의 시간, 두 배·절반 오류 시간, 실제 출력 클릭의 점수를 비교한다. 작은 실제 변속의 전후 구간과 진짜 두 배 변속은 별도 표로 남긴다. 속도 후보 부족, 환산 후보의 박 위치·근거 부족, 잘못된 시작 단위 유지, 변속 경계의 문제를 나눠 설명한다.\n\n성분 효과의 사전 판단: 변속곡 평균 맞는 시계 시간 +3%p 이상, 배수 오류 상대 25% 이상 감소, 클릭 점수 하락 0.5%p 이내, 대조군 맞는 시계 시간 하락 1%p 이내, 작은 실제 변속 뒤 명목 BPM 시간 하락 1%p 이내. 모든 곡에서 손해 없이 사용할 수 있다는 판단은 별도로 하며, 변속곡 개별 하락 3%p 이내와 진짜 두 배 변속 뒤 하락 1%p 이내를 요구한다. 이 수치는 연구 확인 기준이며 제품 합격 기준이 아니다.\n\n이 부품은 원래 출력의 변경 시점을 재사용하므로 경계 검출을 해결했다고 주장하지 않는다. 실제 두 배·절반 변속을 따로 식별하는 기능도 없다. 배수 오류 감소와 실제 변속 손실을 함께 보고하며, 기존 앱·표본·정답·동결된 실험은 수정하지 않는다.\n'''
    (run / 'preregistered-plan.ko.md').write_text(plan)
    write(run / 'entry-state.json', {'at_utc': stamp(), 'git_status': subprocess.run(
        ['git', 'status', '--short'], cwd=ROOT, text=True, capture_output=True, check=True).stdout})
    print('PREPARED', run, roles, flush=True)


if __name__ == '__main__':
    main()
