# BPMTracker / Joljak

음악의 템포·박자 맵을 추정하고, 원음과 프로젝트 메트로놈을 함께 들으며 검토하는 프로젝트입니다. 현재 개발의 중심은 **변속곡으로 확장하는 것**입니다.

## 현재 기준

**2026-10-13부터 `L2_DENSE_PROPOSALS`를 variable 개발의 새 기준 버전으로 삼습니다.** 직접 청취한 현재 품질을 개선의 출발점으로 받아들이고, 이후 수정은 이 결과와 비교합니다. 기존 고정 전용 알고리즘과 승인된 정답 맵도 비교 기준으로 유지합니다.

다음 목표는 **Spiritbox — Circle With Me의 205→210→205→210 변속 세 번을 따라가면서 마디 첫 박을 유지하는 것**입니다. 마지막의 잘못된 2/4 변경도 없어져야 합니다. 현재는 변속 전 구간을 잘 맞추지만 세 변속을 모두 놓칩니다. 같은 종류의 작은 변속과 일반 고정곡의 품질을 함께 비교할 예정입니다.

| 구분 | 현재 위치와 상태 |
| --- | --- |
| 새 개발 진입점 | [algorithms/variable](algorithms/README.md): 기존 L2 구현을 그대로 선택하는 인터페이스 |
| 실제 추론 구현·설정 | [beat_event_stability_v1](experiments/beat_event_stability_v1/README.md): 현재 측정된 코드·설정 유지 |
| 명확한 현황·다음 작업 | [프로젝트 상태](project-state.json), [개발 안내](docs/DEVELOPMENT.md) |
| 소스 파일을 찾을 때 | [코드 지도](docs/CODE_MAP.md) |
| 이전 코드와 완료된 작업 | [reference](reference/README.md) |
| Windows 앱 | [apps/daw](apps/daw/README.md), 현재 버전 **0.6.15** |

새 기준은 **개발·실험의 비교 기준**입니다. 앱의 Analyze Audio는 아직 고정 BPM·박자·시작 오프셋 하나를 반환하는 기존 분석기를 사용합니다. 자동 variable 분석의 앱 적용은 별도 구현 작업입니다. 기록된 점수·실패 사례·정답·평가 규칙을 바꾸어 새 기준을 만든 것은 아닙니다.

## 직접 비교하기

현재 결과와 정답의 `.joljak` 청취 자료는 아래 로컬 폴더에 있습니다.

```text
data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/listen-projects/
```

원음이 있는 저조 사례 **21쌍**을 일반 고정곡·변속곡·변박곡·고난도·보조 표본으로 구분했습니다. 각 곡의 `reference.joljak`과 `current.joljak`을 열고 Click을 켜면 됩니다. 차이가 드러나는 구간과 두 프로젝트에서 이동할 시간도 안내되어 있습니다. 원음이 없는 GTZAN 저조 사례 22개는 별도 목록이며 청취 파일을 만들지 않았습니다.

다시 열 때 음이 낮고 느리게 들리던 샘플레이트 복원 문제는 **0.6.15**에서 수정했습니다. 열어둔 앱을 완전히 종료한 뒤 **Start Joljak.cmd**로 다시 실행해 같은 파일을 여세요. 원음·BPM·박자·배치를 수정할 필요는 없습니다.

## 앱 실행과 기능

Windows 탐색기에서 **Start Joljak.cmd**를 실행합니다. 이미 실행 중이면 완전히 종료한 뒤 다시 실행해야 현재 빌드를 불러옵니다. 최초 실행 이후 `.joljak` 파일을 더블클릭해 열 수도 있습니다.

앱은 음원·스템 가져오기, 이동·복사·분할·트림, 범위 편집, Undo/Redo, 믹싱, Tempo/Signature 트랙, Linear/Musical 트랙, 표본 검토, 프로젝트 저장과 WAV·맵 출력을 지원합니다. Tempo·Signature 선언은 기존 박 위치에 둘 수 있으며 마디 중간도 허용합니다. 맵 편집은 원음의 속도나 길이를 바꾸지 않습니다.

자세한 사용·빌드는 [앱 안내](apps/daw/README.md), 표본 작업은 [관리 도구](tools/README.md)를 보세요. 승인된 정답과 사용자 수정안은 별도로 저장합니다.

## 저장소 구조

```text
algorithms/variable/     현재 variable 개발 진입점
experiments/             측정된 기준 구현·고정 비교·공통 관측/검색/평가 코드
reference/               이전 독립 실험·완료된 일회성 작업·이전 청취 도구
apps/daw/                현재 Windows 앱
apps/daw/reference/      이전 UI 검증·시안·원격 설치 자료
tools/                   현재 표본·저장소 관리 도구
docs/                    개발 안내·코드 지도·보존한 결과 이력
data/                    원음은 로컬; 정답·실험 기록은 별도 비공개 데이터 Git
_local/                  별도 비공개 프로젝트 노트
```

현재 구현에서 재사용하는 이전 모듈은 `experiments/`에 유지했습니다. 과거 방법의 이름이 남았다고 그 방법을 새로 실행하거나 채택한다는 뜻은 아닙니다. [실험 코드 안내](experiments/README.md)에서 현재 역할과 참고 역할을 확인할 수 있습니다.

프로젝트 상태를 간단히 확인하려면:

```bash
python3 tools/repository/status.py
```

원래 고정 모델의 수치·평가 집합·초기 연구는 [보존한 결과](docs/reference/FIXED_MODEL_RESULTS.md), 앱 버전별 검증은 [검증 이력](apps/daw/reference/VALIDATION_HISTORY.md)에 있습니다. 원음과 승인 맵의 소속·경로는 `data/samples/catalog.json`이 관리합니다. 기록된 실험의 분모와 입력은 이후 표본 추가나 정리로 바꾸지 않습니다.

소스 저장소의 커밋·푸시는 사용자가 수행합니다. 문서의 계획이나 예제 명령만으로 새 실험·수집·검증을 시작하지 않습니다.

비공개 자료는 [joljak-data](https://github.com/kkuiks/joljak-data)에 보관합니다.
기존 `data/`가 독립된 데이터 저장소이며, 공개 소스 Git에서는 계속 제외합니다.
작은 정답·수정안은 Git으로, 큰 실험 자료는 비공개 릴리스 첨부로 보관합니다.
원음·음원 압축본·로그인 정보·재생 캐시는 제외합니다. 백업 범위와 복원 절차는
`data/README.md`와 [관리 도구 안내](tools/repository/README.md)에 있습니다.
