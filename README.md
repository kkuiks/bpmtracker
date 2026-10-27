# BPMTracker

BPMTracker는 여러 음원과 스템을 배치·편집하고, 템포와 박자 맵을 함께 관리하는 Windows DAW입니다. 필요한 구간의 BPM·박자·다운비트 위치를 분석하고, 곡과 스템을 프로젝트의 마디에 맞춰 정렬할 수 있습니다.

## 주요 기능

- 음원·스템 가져오기와 멀티트랙 배치
- 이동·복사·분할·트림·범위 편집과 Undo/Redo
- 재생·루프·믹싱·메트로놈
- 템포·박자 맵 편집, Linear/Musical 트랙과 곡·스템 정렬
- 곡 또는 선택 구간의 BPM·박자·다운비트 분석
- 프로젝트 저장·복구와 WAV 믹스·스템·클릭, JSON/MIDI 템포 맵 출력

맵을 편집해도 오디오의 재생 속도와 길이는 유지됩니다. 자동 분석은 선택한 곡·구간에 하나의 고정 BPM과 3/4 또는 4/4를 제안합니다. 녹음, VST, MIDI 연주 편집과 타임 스트레칭은 지원하지 않습니다.

## Windows에서 실행하기

포터블 앱 폴더(`dist/BPMTracker-win-x64/`)가 준비되어 있다면 그 안의 **BPMTracker.exe**를 실행합니다. 실행 파일과 `resources`를 포함한 폴더 전체를 함께 보관합니다. 이 폴더는 소스와 별도로 갱신하는 실행본입니다.

소스에서는 [앱 가이드의 실행 준비](apps/daw/README.md#소스에서-실행하기)를 따릅니다. Windows 소스 실행과 WSL에서 포터블 앱을 만드는 방법을 안내합니다. 원음과 공식 모델 파일은 소스에 포함되지 않습니다.

## 빠른 시작

1. 음원이나 스템을 가져와 트랙에 배치합니다.
2. 재생하면서 이벤트를 편집하고 볼륨·팬·메트로놈을 조절합니다.
3. Tempo/Signature 맵을 직접 편집합니다. 분석이 필요하면 곡 또는 구간을 선택해 **Analyze Audio**를 실행합니다.
4. 분석 결과를 청취하고 **Apply & Align**으로 맵과 배치에 적용합니다.
5. 프로젝트를 저장하거나 필요한 구간을 출력합니다.

## 문서

| 내용 | 문서 |
| --- | --- |
| 사용법·단축키·설치·빌드 | [앱 사용자 가이드](apps/daw/README.md) |
| 앱 구성과 데이터 흐름 | [아키텍처](docs/ARCHITECTURE.md) |
| BPM·박자·다운비트 분석 | [분석 기능](docs/ANALYSIS.md) |
| 분석 모듈 위치와 API | [알고리즘 안내](algorithms/README.md) |

## 소스 구성

```text
apps/daw/src/          화면과 프로젝트 편집
apps/daw/electron/     데스크톱 IPC, 파일·작업·캐시 관리
apps/daw/backend/      오디오 디코딩·분석·출력
apps/daw/scripts/      실행과 Windows 패키징
apps/daw/audit/        프로젝트 파일 계약 검사
algorithms/fixed/     고정 BPM·박자·다운비트 분석기
docs/                 제품 설계와 분석 기능 안내
```

Electron·React·Web Audio와 Python CPU worker를 사용합니다. 박·다운비트 관측에는 외부 모델 [Beat This!](https://github.com/CPJKU/beat_this)의 공식 `final0`를 사용합니다. 모델 출처와 처리 과정은 [분석 기능 문서](docs/ANALYSIS.md#외부-모델과-의존성)에 있습니다.
