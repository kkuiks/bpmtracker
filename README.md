# Joljak

**합주·공연용 멀티트랙 준비를 위한 템포·박자 분석 프로젝트**

완성 음원과 악기별 스템에서 공통 음악 시간축을 얻고, 이를 검토·편집하여 음악·클릭·가이드를 동기화된 파일로 출력하는 Windows 프로그램을 목표로 합니다.

현재는 **분석 알고리즘과 평가 체계를 검증하는 실험 단계**입니다. 실행 가능한 데스크톱 앱, 통합 편집·출력 기능, Windows 설치 패키지는 아직 없습니다. 현재 실험 환경은 Linux/WSL이며 최종 제품은 WSL 없이 Windows에서 실행하는 것을 목표로 합니다.

## 무엇을 분석하나요?

박이 발생한 시각을 찾는 것에서 출발하여 다음 정보를 담은 **템포·박자 지도**를 구성합니다.

- 4분음표 기준 BPM과 구간별 템포 변경
- 박자표, 마디의 시작 위치와 변경
- 고정 클릭을 적용할 수 있는 시간 범위
- 원본 음원의 시간축에 맞춘 박·마디 시각

메트로놈을 기준으로 제작된 스튜디오 음악이 주 대상입니다. 분석 결과는 검토할 수 있는 제안 지도이며, 자유 템포 연주 전반의 자동 복원을 보장하지 않습니다.

```mermaid
flowchart LR
    A[완성 음원] --> B[Beat This 박·다운비트 관측]
    B --> C[공통 템포·박자 지도 재구성]
    C --> D[지도·박·마디 시각]
    D --> E[클릭 청취 검토]
```

현재 공통 실행기는 저장된 음원·관측에 같은 규칙을 적용합니다. 곡 이름이나 참조 지도를 이용해 경로를 고르지 않습니다. 관측 생성과 지도 재구성은 별도 단계이며, 기존 청취 검토 묶음도 독립된 실험 도구입니다.

## 현재 결과

**2026-09-27 고정 개발 기준선: 검수된 13곡 중 10곡 통과**

| 범위 | 현재 상태 |
| --- | --- |
| 참조 자료 | 전곡 지도 12곡 + 고정 격자와 자유 엔딩을 구분한 1곡 |
| 통과 기준 | BPM·박자·박·마디·두 종류의 변경 점수 각각 90% 이상 |
| 사건 허용 오차 | 박·마디 ±70ms, 템포·박자 변경 ±500ms |
| 오탐 처리 | 추가 박·마디·변경 감점; 일정한 참조에 거짓 변경이 있으면 해당 항목 실패 |
| 실패곡 | Nocturne, Naysayer, Archspire — Liminal Cypher |
| 해석 | 이미 관찰하고 규칙 개발에 사용한 표본의 결과; 미관측곡 성공률은 미검증 |

이전의 11/11 결과는 알려진 곡의 개별 근거를 연결한 별도 실험입니다. 현재의 공통 경로와 실행 조건이 다릅니다. [곡별 성적·오탐·연구 과정](docs/benchmark.md)에서 두 결과와 한계를 확인할 수 있습니다.

## 코드 읽기

| 목적 | 진입점 |
| --- | --- |
| 현재 공통 실행기 | [run_generic_map.py](experiments/tempo_meter_v2/run_generic_map.py) |
| 일정 BPM·마디 격자 | [constant_grid.py](experiments/tempo_meter_v2/constant_grid.py) |
| 단계적 템포 변경 | [tempo_segments.py](experiments/tempo_meter_v2/tempo_segments.py), [barwise_tempo.py](experiments/tempo_meter_v2/barwise_tempo.py) |
| 6/8 해석과 격자 종료 | [compound_meter.py](experiments/tempo_meter_v2/compound_meter.py), [tail_support.py](experiments/tempo_meter_v2/tail_support.py) |
| BPM 정리와 시간 이동 제한 | [plausible_bpm.py](experiments/tempo_meter_v2/plausible_bpm.py) |
| 별도 13곡 평가기 | [score_generic13.py](experiments/tempo_meter_v2/score_generic13.py) |
| 음악 지도 표현·렌더링 | [music_map_contract.py](experiments/analysis_legacy/music_map_contract.py) |

[분석 구조와 실행 방법](docs/analysis.md)은 입력·출력 형식, 선택 규칙과 재현 범위를 설명합니다.

## 음원·모델 없이 테스트하기

Python 3.12의 Linux/WSL 환경에서 저장소 루트를 기준으로 실행합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt

PYTHONPATH=.:experiments/tempo_meter_v2:experiments/analysis_legacy \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
.venv/bin/python -m unittest discover \
  -s experiments/tempo_meter_v2 -p 'test_*.py' -q
```

현재 40개 테스트는 합성 관측, 음악 시간축, 오탐 억제, 종료 구간 및 클릭 생성 등의 동작을 검증합니다. GPU, 사전학습 가중치, 실제 곡, 회원 계정은 필요하지 않습니다. 단위 테스트 통과는 13곡 벤치마크를 재실행했다는 의미가 아닙니다.

## 저장소 구성

```text
experiments/
  tempo_meter_v2/    현재 지도 재구성 및 후속 비교 실험
  analysis_legacy/   이전 분석, 평가, 참조 준비 및 재사용 유틸리티
  analysis          analysis_legacy를 가리키는 호환 링크
  audio-engine/     향후 엔진 검증용 위치
apps/desktop/       향후 데스크톱 앱
services/analysis/  향후 분석 서비스
packages/contracts/ 향후 제품 공통 인터페이스
tests/fixtures/     재배포 가능한 테스트 자료용 위치
docs/              공개 기술 설명과 집계 결과
examples/          참조 없이 구성하는 입력 매니페스트 예시
```

`analysis_legacy`는 과거 실험을 재현하는 코드와 현재 사용하는 공통 유틸리티를 함께 보존합니다. 날짜·11곡·특정 곡을 대상으로 하는 실행기는 해당 실험의 준비된 자료를 요구합니다. 새 입력의 공통 지도 재구성은 `run_generic_map.py`에서 시작합니다. 제품 디렉터리는 현재 구조만 마련되어 있습니다.

## 자료와 재현 범위

원본 음원, 제작 MIDI·프로젝트, 모델 가중치, 대용량 관측·실행 결과는 배포하지 않습니다. 라이선스와 접근 조건이 서로 다른 자료를 포함하므로, 공개 저장소만으로 원래 13곡을 그대로 재채점할 수는 없습니다.

대신 [곡별 집계 JSON](docs/benchmarks/primary13.json)에 여섯 점수, 오탐·미탐, 평가 범위와 원본 결과의 해시를 제공합니다. 실제 추론에는 별도로 준비한 음원과 가중치가 필요합니다. 외부 모델·데이터의 이용 조건은 각 원출처를 따릅니다.

## 다음 검증 범위

- 기존 통과곡의 성능을 보존하면서 고난도 변박·마디 위상 처리 개선
- 코드를 고정한 뒤 새로운 완성 음원에서 적용 가능성 검증
- 지도 검토, 묶음 편집과 음악·클릭·가이드 출력의 통합
- Windows 실행·패키징과 실제 준비 작업의 수정량·소요 시간 검증
