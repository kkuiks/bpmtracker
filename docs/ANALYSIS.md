# 템포·박자 맵 분석

DAW 진입점은 `Analyze Audio`. 선택 원음의 초기 BPM·박자·마디 위상과 이후 변경 이벤트를 계산.

## 입력·출력

| 항목 | 명세 |
| --- | --- |
| 오디오 입력 | 선택 이벤트 전체 또는 원음과 겹치는 선택 구간 |
| 보조 입력 | 초기 quarter 박의 Tap 또는 준비된 박 단위 선택 |
| 초기 상태 | quarter 기준 BPM, 분자·분모, 분석 시작에 대한 마디 위상 |
| 변경 이벤트 | 분석 범위 내 시간, 누적 quarter 위치, 변경된 템포·박자 |
| 원본 기록 | 결과, 입력 범위, 보조 입력, 분석기·모델 식별 |

## 박자표

- 자동 추정 후보: 2/4, 3/4, 4/2, 4/4, 5/4, 6/4, 6/8, 7/4.
- 수동 편집: 분자 1–32, 분모 1·2·4·8·16·32.
- 분석 전 박자표 힌트 입력은 없음.

## 추정 과정

1. Beat This `final0`에서 시간별 박·다운비트 관측 추출.
2. 오디오만으로 초기 후보·박 이벤트 준비. Tap 입력은 이 과정 이후에 참조.
3. Tap 또는 확인 입력을 준비된 후보의 이산적인 박 단위로 변환.
4. 선택 단위에 대한 초기 상태와 전체 분석 범위의 변경점 계산.

탭 숫자는 세부 BPM·위상·변경점 점수에 사용하지 않음. 같은 박 단위를 선택하는 탭은 같은 맵 반환.

원음 정보·범위·분석 소스·모델 식별이 일치하면 관측 캐시 재사용. 박 단위 재확인으로 신경망 관측을 반복하지 않음.

## 상태·적용

| 상태·명령 | 동작 |
| --- | --- |
| Tap / Confirm | 준비된 후보가 여러 개일 때 초기 박 단위 확인 |
| Listen without click | 클릭 없이 분석 범위 앞부분 재생 |
| T·Space·TAP | 확인 창의 Tap 입력 |
| Audition / Audition original map | 원음과 원본 분석 맵 미리듣기 |
| Return to project | 현재 프로젝트 맵으로 복귀 |
| Apply & Align | 전체 맵 적용과 곡·연결 스템 정렬 |
| ORIGINAL | 보관한 원본 분석. 수동 맵 편집과 독립 |

적용 후 편집 대상은 프로젝트 Tempo·Signature 이벤트. 재생·클릭·맵 출력도 편집한 프로젝트 맵 기준. 저장·재열기 후에도 원본 분석과 편집 맵 유지.

수동 편집점과 충돌한 재적용은 차단. 해당 점 이동·삭제 후 재적용 가능.

## 범위·제약

- 분석 대상은 원음과 겹치는 범위. 범위 밖의 신규 변경점은 추정하지 않음.
- 적용값은 다음 선언까지 유효. 오디오 속도·길이는 유지.
- 변경점의 박 위치와 마디 중간 박자 변경 보존.
- 박 관측이 부족한 범위는 맵 생성 실패 가능.
- 자동 추정의 음악적 적합성은 청취·수동 수정 대상. 초기 박 단위 선택과 맵 정확도는 별개.
- 수동 맵 편집·재생은 분석 없이 사용 가능.

편집 규칙: [DAW — 분석과 정렬](../apps/daw/README.md#분석과-정렬).

## 외부 모델과 의존성

박·다운비트 관측: [Beat This!](https://github.com/CPJKU/beat_this) 1.1.0, 공식 `final0` checkpoint. Francesco Foscarin, Jan Schlüter, Gerhard Widmer의 ISMIR 2024 공개 모델. 앱의 격자 추정·맵 편집과는 별도 구성요소.

코드·공식 가중치 라이선스: [MIT](https://github.com/CPJKU/beat_this#license). 원문 고지 유지. [공식 모델 목록](https://github.com/CPJKU/beat_this#available-models)의 `final0`를 `models/final0.ckpt`에 배치하거나 빌드의 `--checkpoint`로 지정.

CPU 의존성 기준: [requirements-cpu.lock](../algorithms/fixed/requirements-cpu.lock). 주요 구성은 PyTorch·Torchaudio, NumPy·SciPy, SoundFile·soxr.

[환경 구성](../apps/daw/README.md#소스에서-실행하기) · [외부 구성요소](../THIRD_PARTY_NOTICES.md)
