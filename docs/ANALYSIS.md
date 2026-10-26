# BPM·박자·다운비트 분석

**Analyze Audio**는 선택한 곡 또는 구간에 하나의 고정 BPM·박자표·다운비트 위치를 제안합니다. 트랙 편집과 수동 템포 맵 작성은 분석 없이도 사용할 수 있습니다.

## 입력과 결과

| 항목 | 의미 |
| --- | --- |
| 오디오 | 선택한 이벤트의 곡 전체 또는 원음과 겹치는 선택 구간 |
| Tap | 선택 입력. 곡의 처음 부분에서 들리는 quarter 박을 탭합니다. |
| BPM | quarter 기준 30–400 BPM. 기약분수의 분모가 4 이하인 값을 지원합니다. |
| 박자 | 3/4 또는 4/4 |
| 다운비트 위치 | 선택 범위의 오디오 시작에 대한 위치. 한 마디를 주기로 해석합니다. |
| 상태·점수 | 경쟁 후보와 관측 일치 정도, 모호하거나 약한 결과를 알리는 flag |

결과의 점수는 정답 확률이 아닙니다. 일정한 템포와 박자라는 가정이 맞는지, 클릭이 음악에 맞는지 직접 청취해 확인합니다. 여러 템포·박자 변경을 자동으로 찾지는 않습니다.

## 처리 과정

Beat This가 시간에 따른 박·다운비트 logits를 만듭니다. `algorithms.fixed.infer`는 이를 확률·이벤트 관측으로 구성하고 quarter와 마디 격자를 함께 평가합니다. BPM·박자·위치 후보의 점수는 선택한 전체 오디오 범위에서 계산합니다.

`hinted.prepare_audio_family`는 Tap을 읽기 전에 오디오의 BPM 후보와 그 두 배·절반 계열을 준비합니다. Tap은 이 가운데 이산적인 박 단위만 고릅니다. 같은 박 단위를 고르는 탭 값은 같은 완성 예측을 반환하며, 탭 숫자로 세부 BPM·다운비트 위치·점수를 맞추지 않습니다. 박자표 입력은 받지 않습니다.

탭이 단위 경계에 있거나 오디오가 지지하지 않는 단위를 요구하면 결과를 선택하지 않을 수 있습니다. 충분한 박 관측이 없는 입력도 상태로 구분합니다. 경쟁 후보가 비슷하거나 일치가 약하면 결과에 flag가 붙습니다.

## DAW에서 사용하기

1. 분석할 곡의 이벤트 또는 그 안의 구간을 선택합니다.
2. **Analyze Audio**를 엽니다. 필요하면 처음 부분의 박을 Tap으로 입력합니다.
3. 결과와 클릭을 청취합니다. 저장값은 적용 전에 편집할 수 있습니다.
4. **Apply & Align**에서 기준 마디와 이동량을 확인하고 적용합니다.

원본 예측, 편집한 저장값, 실제 프로젝트 맵·배치는 구분해 보관합니다. **Restore Original Prediction**은 저장값을 복원합니다. 맵과 이벤트 배치를 바꾸려면 **Apply & Align**을 별도로 실행합니다.

분석은 원음과 겹치는 범위만 다룹니다. 맵에 적용한 템포·박자 값은 다음 선언까지 유지되며, 적용이 오디오의 속도나 길이를 변경하지는 않습니다. 자세한 조작은 [앱 가이드](../apps/daw/README.md#분석과-정렬)를 참고하세요.

## 외부 모델과 의존성

박·다운비트 관측에는 [CPJKU의 Beat This!](https://github.com/CPJKU/beat_this) 1.1.0과 공식 `final0` checkpoint를 사용합니다. Francesco Foscarin, Jan Schlüter, Gerhard Widmer의 ISMIR 2024 연구에서 공개한 모델이며, 앱의 격자 선택·DAW 맵 편집과는 별도 구성요소입니다.

공식 저장소는 코드와 공개 가중치를 [MIT 라이선스](https://github.com/CPJKU/beat_this#license)로 제공합니다. 원문 고지와 각 라이브러리의 라이선스를 유지합니다. 모델은 [공식 모델 목록](https://github.com/CPJKU/beat_this#available-models)에서 준비해 소스의 `models/final0.ckpt`에 두거나 빌드 시 `--checkpoint`로 지정합니다.

CPU 의존성은 [requirements-cpu.lock](../algorithms/fixed/requirements-cpu.lock)에 고정되어 있습니다. 주요 구성은 PyTorch·Torchaudio, NumPy·SciPy, SoundFile·soxr입니다. 설치·포터블 조립은 [앱 가이드](../apps/daw/README.md#소스에서-실행하기)를 따릅니다.
