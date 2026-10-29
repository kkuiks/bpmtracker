# BPMTracker

Windows 오디오 편집기와 템포·박자 맵 분석 코드.

## 구현 범위

- 오디오·스템 배치, 트림·분할, 트랙 믹싱
- 템포·박자 맵 추정, 초기 박 단위 선택, 원본 분석 보관
- Tempo·Signature 이벤트 편집, 마디 중간 박자 변경, Undo/Redo
- 원음·메트로놈 재생, 구간 반복, 프로젝트 저장·복구
- WAV 믹스·스템·클릭, JSON·MIDI 맵 출력

녹음, VST, MIDI 노트 편집, 타임 스트레칭은 미구현.

## 코드 구조

| 경로 | 역할 |
| --- | --- |
| `apps/daw/src/` | React·TypeScript 화면, 프로젝트 모델, 편집·재생 제어 |
| `apps/daw/electron/` | IPC, 파일 입출력, 프로젝트·캐시 관리 |
| `apps/daw/backend/` | Python 오디오 디코딩, 분석 작업, 출력 |
| `apps/daw/public/transport-worklet.js` | AudioWorklet 믹싱·메트로놈 |
| `apps/daw/scripts/` | Windows 실행·패키징 |
| `apps/daw/audit/` | 프로젝트·시간축·작업 전환 검사 |
| `algorithms/` | 박 관측, 초기 후보 준비, 템포·박자 맵 추정 |
| `docs/` | 구조·분석 명세 |

## 개발 환경

| 항목 | 기준 |
| --- | --- |
| 실행 대상 | Windows x64 |
| 프런트엔드·데스크톱 | Node.js 24, npm, Electron |
| 오디오 처리·분석 | Python 3.12, CPU 실행 |
| 프런트엔드 의존성 | `apps/daw/package-lock.json` |
| Python 의존성 | `algorithms/fixed/requirements-cpu.lock` |
| 박·다운비트 모델 | [Beat This!](https://github.com/CPJKU/beat_this) 공식 `final0` |

환경 구성과 실행 명령: [DAW — 소스에서 실행하기](apps/daw/README.md#소스에서-실행하기).

## 문서

| 문서 | 내용 |
| --- | --- |
| [DAW](apps/daw/README.md) | 실행·빌드, 조작 참조, 편집 규칙 |
| [아키텍처](docs/ARCHITECTURE.md) | 구성요소, 시간 좌표, 데이터 흐름 |
| [분석](docs/ANALYSIS.md) | 입력·출력, 추정 과정, 지원 박자표 |
| [분석 모듈](algorithms/README.md) | Python API와 설정 파일 |
| [검사](apps/daw/audit/README.md) | 계약 검사 실행 명령 |
| [외부 구성요소](THIRD_PARTY_NOTICES.md) | 의존성·모델 출처와 라이선스 |
| [화면](docs/images/arrangement.png) | Arrangement·Inspector·Audio Editor |
