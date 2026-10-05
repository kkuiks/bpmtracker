# 템포·박자 분석 구조와 실행 방법

현재 구현은 완성 음원의 음악 시간축을 제안하는 실험용 Python 코드입니다. 데스크톱 편집기나 자동 승인 서비스는 아직 구현하지 않았습니다. 현재 점수와 평가 범위는 [벤치마크](benchmark.md)에 있습니다.

## 입력과 출력

추론에는 기준 WAV, Beat This final0의 프레임별 박·다운비트 관측, 공식 최소 디코더의 사건 목록을 사용합니다. WAV의 SHA-256과 샘플레이트·샘플 수를 확인하여 서로 다른 파일의 관측을 섞지 않습니다.

결과는 구간별 음악 좌표와 음원 시각을 연결하는 `clock_knots`, 음표 단위, 박자 사건, 마디 기준 위치, 격자 지원 범위를 갖는 지도입니다. 박·마디 시작 시각과 후보 선택 사유도 저장합니다. 지도 수정만으로 원본 오디오를 늘이거나 줄이지 않습니다.

지도 형식의 검증·시간 변환·마디 렌더링은 [music_map_contract.py](../experiments/analysis_legacy/music_map_contract.py)를 재사용합니다. 이는 실험용 표현이며 제품의 공통 인터페이스로 확정된 스키마는 아닙니다.

## 공통 처리 순서

1. **일정 격자:** 박 활성값의 주기와 위상을 추정하고, 다운비트 관측으로 일정한 마디 길이와 시작 위치를 선택합니다.
2. **제한된 템포 변경:** 지속되는 대체 주기와 음향 적합도를 바탕으로 최대 세 번의 변경을 갖는 제한된 후보를 평가합니다.
3. **마디 간격 기반 템포 변경:** 단일 4/4 기본 지도의 원시 마디 간격을 분할합니다. 최소 구간 길이, 누락 관측, 변경 벌점과 원시 사건 설명력 개선을 확인합니다.
4. **조건부 6/8 해석:** 여섯 세부 주기의 마디에서 세 주기 단위 관측이 충분할 때 6/8 후보를 구성합니다.
5. **후보 선택:** 제한된 템포 변경 → 마디 간격 기반 변경 → 6/8 → 일정 격자의 고정된 우선순위를 적용합니다.
6. **격자 종료:** 마지막 부분의 박 간격 변화와 다운비트 지지 소실이 함께 나타날 때 지원 범위를 줄입니다.
7. **BPM 정리:** 정수에서 0.1 BPM, 그렇지 않으면 0.5 단위에서 0.05 BPM 이내인 값을 제안합니다. 박·마디 개수, 템포 변경 구조와 시간축을 보존하고, 모든 클릭·변경점 이동이 35ms 이내일 때만 적용합니다.

각 조건은 개발 표본에서 설계한 제한적인 실험 규칙입니다. 일정 격자의 후보 범위는 35–320 quarter BPM이며, 마디 간격 기반 변경은 현재 4/4에 한정됩니다. 종료 판단은 마지막 45초를 탐색합니다. 이 조건들이 일반적인 음악 법칙이거나 보정된 신뢰도라는 주장은 하지 않습니다.

곡 이름·참조 지도·승인된 정렬값은 선택 근거로 읽지 않습니다. 다만 개발자가 이전 평가를 보고 규칙을 수정했으므로, 참조를 읽지 않는 실행과 미관측 자료 검증은 별개입니다.

## 빠른 검증

[저장소 첫 화면](../README.md)의 가벼운 환경은 `numpy`, `soundfile`, `soxr`와 그 필수 의존성만 설치합니다. 현재 v2 테스트에는 실제 곡과 모델 가중치가 필요하지 않습니다.

```bash
PYTHONPATH=.:experiments/tempo_meter_v2:experiments/analysis_legacy \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
.venv/bin/python -m unittest discover \
  -s experiments/tempo_meter_v2 -p 'test_*.py' -q
```

이 경로는 Linux/WSL의 Python 3.12에서 검증합니다. 네이티브 Windows 제품 실행·설치 검증은 남아 있습니다.

## 실제 WAV의 관측 생성

이 단계에는 별도의 모델 실행 환경과 이미 확보한 체크포인트가 필요합니다. 가벼운 테스트 환경에는 PyTorch나 Beat This를 설치하지 않습니다.

[기존 Linux/Python 3.12/CUDA 12.6 잠금 파일](../experiments/analysis_legacy/requirements-linux-py312-cu126.lock)은 음향 추론 환경의 재현 자료입니다. CUDA 패키지를 포함하므로 가벼운 테스트 설치와 구분합니다. [공식 Beat This 저장소](https://github.com/CPJKU/beat_this)에서 모델과 이용 조건을 확인하여 가중치를 별도로 준비해야 합니다.

다음 예시는 잠금 파일을 설치한 Linux 환경에서, 전체 길이의 기준 WAV와 로컬 final0 체크포인트를 사용합니다.

```bash
python3.12 -m venv .venv-model
.venv-model/bin/python -m pip install --require-hashes \
  -r experiments/analysis_legacy/requirements-linux-py312-cu126.lock

.venv-model/bin/python experiments/analysis_legacy/run_beat_this.py \
  --audio=data/input/source.wav \
  --checkpoint=data/models/final0.ckpt \
  --device=cpu \
  --output-dir=data/runs/observations
```

GPU를 사용할 경우 해당 환경을 확인한 뒤 `--device=cuda`를 지정합니다. 실행기는 가중치를 자동 다운로드하지 않습니다. 전체 지도에는 전체 음원의 관측이 필요하므로 이 과정에서 `--max-seconds`로 일부만 분석하지 않습니다. 입력은 이미 디코딩된 WAV여야 합니다.

출력의 `result.json`은 음원 식별 정보와 공식 사건 목록을, `logits.npz`는 `beat`, `downbeat`, `fps` 배열을 포함합니다. 이미 같은 음원에 대해 생성한 관측이 있다면 재사용할 수 있습니다.

## 입력 매니페스트와 지도 실행

[예시 매니페스트](../examples/source-only-manifest.example.json)를 참고하여 `data/input-manifest.json`을 준비합니다. 예시의 0으로 채운 SHA 값은 자리표시자이므로 실제 파일의 값으로 바꿔야 합니다.

```bash
sha256sum data/input/source.wav \
  data/runs/observations/logits.npz \
  data/runs/observations/result.json
```

매니페스트의 `source_only: true`, `reference_read: false`는 실행 조건의 선언입니다. 실제 선택기는 음원과 관측만 읽지만, 이 선언 자체가 외부 모델이나 모든 자료의 독립성을 증명하지는 않습니다.

저장소 루트에서 실행합니다. 매니페스트의 상대 경로 역시 저장소 루트를 기준으로 합니다.

```bash
PYTHONPATH=.:experiments/tempo_meter_v2:experiments/analysis_legacy \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
.venv/bin/python -m experiments.tempo_meter_v2.run_generic_map \
  --input-manifest=data/input-manifest.json \
  --output=data/runs/example-map
```

출력 폴더는 새 경로여야 합니다. `prediction-manifest.json`에는 입력과 구현 해시, 각 후보, 선택 분기와 후처리 결정이 기록됩니다. `predictions/<id>/selected.json`이 선택된 제안 지도입니다. 이름을 추가해도 각 행에 같은 규칙이 적용됩니다.

## 평가와 청취

[score_generic13.py](../experiments/tempo_meter_v2/score_generic13.py)는 원래의 검수된 13곡에 대한 고정 평가기입니다. 정확한 참조 목록, 승인 지도와 원본 파일이 필요하므로 공개 집계 JSON만으로 이 평가기를 실행할 수는 없습니다. 임의의 새 곡을 위한 범용 참조 수집기는 아닙니다.

[build_primary11_listening.py](../experiments/tempo_meter_v2/build_primary11_listening.py)는 알려진 11곡의 예측 묶음을 클릭으로 렌더링한 실험용 검토 도구입니다. 같은 샘플 시간축에서 원곡·클릭을 재생하고 독립 음량 조절과 메모를 제공합니다. 청취 도구의 동작 검증, 사람이 실제로 듣고 내린 판단, 분석기의 정확도는 구분합니다. 기존 클릭은 음원 0초에서 시작하며 원곡 이전 카운트인은 아직 렌더링하지 않습니다.

## 실험 코드의 역할

- `run_generic_map.py`와 일곱 개 구성 모듈: 현재 공통 경로.
- `score_*.py`: 예측 완료 후 참조를 읽는 평가기 및 정책 비교.
- `run_*11.py`, `diagnose_*`, `train_*`, `sweep_*`: 알려진 표본에 대한 탐색·실패 원인·대조 실험. 각 실행기의 준비된 입력이 필요합니다.
- `analysis_legacy`: 이전 알고리즘, 참조 준비·감사, 평가·렌더링 유틸리티. 일부 과거 도구는 특정 로컬 자료 배치와 선택적 모델 의존성을 가정합니다.

분석 정확도 개선은 곡별 성적과 추가 사건 수로 비교합니다. 합성 테스트 통과, 실제 음악의 참조 검수, 미관측곡 적용과 제품 사용성은 각각 별도의 검증 범위입니다.
