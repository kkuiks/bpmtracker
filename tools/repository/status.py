"""Print application, algorithm and evaluation-data status from project metadata."""
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
    # Retain the historical metadata key; this comparison has completed.
    evaluation = state['next_objective']
    print('비교 범위:', evaluation.get('title', evaluation.get('primary_recording', '미정')))
    research = state.get('current_research')
    if research:
        print('연구 상태:', research['status'])
        print('연구 후보:', research['primary']['trial'], '/', research['primary']['scope'])
        print('연구 근거:', research['run_root'], '/ 안내:', research['source_document'])
        print('개발 자료의 전체 탐색 검증:', research['verification']['full_L2_verified'])
        print('독립 평가:', '완료' if research['independent_evaluation']['evaluated'] else '미완료')
        repair = research.get('post_evaluation_repair')
        if repair:
            print('후속 선택 실험:', repair['status'])
            print('후속 실험 범위:', repair['formal_sources'], '정식 /', repair['broad_sources'], '대량 입력')
    review = state.get('review_preparation')
    if review:
        print('검토 요약:', review['source_document'])
        print('검토용 소스:', review['source_snapshot'])
        print('다음 알고리즘 설계:', '미선정' if not review['next_architecture_selected'] else '선정')
    collection = evaluation.get('collection_counts', {})
    if collection:
        print('목록화된 원본 입력:', collection['source_inputs_available'])
        print('입력·기준 주석 쌍:', collection['source_provider_beat_reference_pairs'])
        print('집계 범위:', collection.get('scope', '완료한 자료 목록'))
    print('대량·정식 비교 상태:', evaluation['status'])
    print('현재 결과:', baseline['primary_recorded_run'])
    print('청취 자료:', baseline['native_listening_review'])
    print('안내: docs/DEVELOPMENT.md / docs/RESEARCH_REVIEW.md / docs/CODE_MAP.md')


if __name__ == '__main__':
    main()
