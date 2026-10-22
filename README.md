# BPMTracker / Joljak

음악의 BPM·박자·다운비트 위치를 추정하고, Windows 앱 **Joljak**에서 원음과 메트로놈을 함께 들으며 템포 맵을 검토·편집하는 프로젝트입니다.

## 주요 기능

- 음원·스템 가져오기와 여러 트랙 배치
- 이동·복사·분할·트림, 범위 편집, Undo/Redo와 믹싱
- 오디오 분석 결과 청취, 템포·박자 맵 편집과 곡·스템 정렬
- `.joljak` 프로젝트 저장, WAV 믹스·스템·클릭과 템포 맵 JSON/MIDI 출력

**Analyze Audio는 곡 또는 선택 구간에 고정 BPM·박자표·다운비트 오프셋을 하나씩 반환합니다.** 프로젝트 맵에는 여러 템포·박자 변경을 직접 입력할 수 있으며, 맵 편집은 원음의 속도나 길이를 바꾸지 않습니다. 변속·변박 자동 추정은 별도 연구 코드에서 개발하고 있습니다.

## Windows에서 실행하기

소스 체크아웃에서는 탐색기로 **Start Joljak.cmd**를 실행합니다. 최초 빌드와 분석 런타임 준비는 [앱 안내](apps/daw/README.md#run-on-windows)를 따릅니다. 업데이트 후에는 실행 중인 앱을 완전히 종료한 뒤 다시 실행합니다.

포터블 배포본은 폴더 전체를 유지한 채 **Joljak.exe**를 실행합니다.

음원을 가져온 뒤 **Analyze Audio**로 분석하고, 결과를 청취한 후 **Apply & Align**으로 적용합니다. 필요한 맵을 직접 수정하고 프로젝트를 저장하거나 출력할 수 있습니다. 자세한 순서는 [기본 사용법](apps/daw/README.md#basic-workflow)을 보세요.

## 개발과 문서

앱의 고정 템포 분석기와 변속 알고리즘 연구는 별도로 관리합니다. 구현 범위와 검증 상태는 [개발 안내](docs/DEVELOPMENT.md), 알고리즘 원리·측정 결과·한계는 [연구 문서](docs/AUTORESEARCH.md)에 정리되어 있습니다.

| 찾는 내용 | 문서 |
| --- | --- |
| 앱 사용·빌드 | [Joljak 앱 안내](apps/daw/README.md) |
| 소스 구조와 진입점 | [코드 지도](docs/CODE_MAP.md), [알고리즘 안내](algorithms/README.md) |
| 개발 현황 | [개발 안내](docs/DEVELOPMENT.md), [프로젝트 상태](project-state.json) |
| 알고리즘 검토 | [현재 방법·결과·열린 질문](docs/RESEARCH_REVIEW.md) |
| 알고리즘 성능과 재현 | [연구 문서](docs/AUTORESEARCH.md) |
| 표본 검토·관리 | [관리 도구](tools/README.md) |
| 데이터 보관·복원 | [데이터 구조](tools/LOCAL_DATA.md), [저장소 관리](tools/repository/README.md) |

## 저장소 구성

```text
apps/daw/       Windows 앱
algorithms/     알고리즘 진입점
experiments/    추론·검색·평가 구현
reference/      검토용 소스, 이전 연구와 완료된 작업
tools/          표본·저장소 관리 도구
docs/           개발 안내와 연구 문서
```

음원·원시 평가 자료·개별 예측·모델 체크포인트는 공개 소스 배포에 포함되지 않습니다. 알고리즘 검토용 소스와 집계 결과는 `reference/decoder_review/`에 있습니다.
