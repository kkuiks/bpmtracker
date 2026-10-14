"""Print current project pointers; never execute pending experiments."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def main():
    state = json.loads((ROOT / 'project-state.json').read_text())
    baseline = state['development_baseline']
    app = json.loads((ROOT / 'apps/daw/package.json').read_text())
    print('개발 기준:', baseline['method'], '/', baseline['id'])
    print('개발 진입점:', baseline['entry_point'])
    print('측정된 구현:', baseline['implementation'])
    print('Windows 앱:', app['version'], '(기본 분석기는 고정 전용)')
    next_objective = state['next_objective']
    print('다음 연구안:', next_objective.get('title', next_objective.get('primary_recording', '미정')))
    diagnosis = state.get('latest_diagnosis')
    if diagnosis:
        print('최근 완료 진단:', diagnosis['id'], '/', diagnosis['status'])
        comparison = diagnosis['comparison']
        print('진단 비교: 전체 L2', comparison['full_L2_pairs_completed'],
              '/', comparison['expected_known30_pairs'],
              '· 초기/박자 고정', comparison['held_pairs_completed'],
              '/', comparison['expected_known30_pairs'],
              '· 완료 셀', comparison['completed_cells'])
        print('재현된 퇴행:', comparison['reproduced_regressions'],
              '(비교 완료는 무퇴행 통과와 별개)')
        print('진단 보고:', diagnosis['evidence']['report'])
        print('전달 ZIP:', diagnosis['delivery']['compact_zip'])
        print('보관: 내부 요약만 게시 · 보고서/ZIP은 로컬')
    research = state.get('current_research')
    if research:
        print('종료 회차:', research['id'], '/', research['status'])
        print('연구 후보:', research['primary']['trial'], '/', research['primary']['scope'])
        print('연구 근거:', research['run_root'], '/ 안내:', research['source_document'])
        print('종료 회차의 전체 L2 검증:', research['verification']['full_L2_verified'])
    print('현재 결과:', baseline['primary_recorded_run'])
    print('직접 청취:', baseline['owner_native_listening'])
    print('안내: docs/DEVELOPMENT.md / docs/CODE_MAP.md / reference/README.md')


if __name__ == '__main__':
    main()
