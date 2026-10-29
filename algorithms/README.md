# 오디오 분석 모듈

DAW의 `Analyze Audio`에서 사용하는 Python 패키지. 입력은 원음과 박·다운비트 관측, 출력은 초기 템포·박자와 변경 이벤트.

## 템포·박자 맵

패키지: [`tempo_map`](tempo_map/)

| API·파일 | 역할 |
| --- | --- |
| `tempo_map.runtime.prepare_observations` | 박 관측과 오디오에서 초기 후보·박 이벤트 준비 |
| `tempo_map.runtime.initial_unit` | Tap 또는 확인 입력에 따른 초기 박 단위 선택 |
| `tempo_map.runtime.predict` | 준비된 이벤트와 박 단위로 전체 범위의 맵 계산 |
| `tempo_map/parameters.json` | 맵 추정 수치 설정 |

반환값: 분석 범위 길이, 초기 BPM·박자표·마디 위상, 변경 이벤트의 시간·quarter 좌표. 실행 단위는 별도 Python worker 프로세스.

DAW에서는 원본 분석을 보관하고 프로젝트의 `tempos`·`signatures`에 적용. 원본 분석과 적용 후 편집한 맵은 별도 데이터.

## 박 관측·초기 후보

패키지: [`fixed`](fixed/)

| API·파일 | 역할 |
| --- | --- |
| `infer.make_evidence` | 모델의 박·다운비트 관측을 분석 입력으로 변환 |
| `hinted.prepare_audio_family` | 오디오에서 템포·박자·위치 후보 준비 |
| `hinted.select_from_family` | 초기 박 단위에 맞는 고정 후보 선택 |
| `fixed/config-tap-v2.json` | 관측·후보 준비 설정 |
| `fixed/requirements-cpu.lock` | Python CPU 의존성 버전 |
| `fixed/payload.json` | 실행·갱신·패키징 공통 분석 소스 목록 |

고정 분석 CLI:

```bash
python -m algorithms.fixed.hinted --help
```

모델 경로 옵션은 `--checkpoint`. DAW의 수동 맵 편집·재생은 분석 실행과 독립.

입출력 명세: [분석](../docs/ANALYSIS.md). 환경 구성: [DAW](../apps/daw/README.md#소스에서-실행하기).
