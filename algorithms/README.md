# 분석 모듈

[fixed](fixed/)는 DAW의 **Analyze Audio**에서 사용하는 고정 BPM·박자·다운비트 분석기입니다. 지원 조건과 처리 과정은 [분석 기능](../docs/ANALYSIS.md), 설치와 실행은 [앱 가이드](../apps/daw/README.md#소스에서-실행하기)를 참고하세요.

- `infer.make_evidence`: Beat This의 박·다운비트 관측을 분석 입력으로 구성합니다.
- `hinted.prepare_audio_family`: 오디오로 템포·박자·위치 후보와 점수를 준비합니다.
- `hinted.select_from_family`: 선택적으로 입력한 Tap의 박 단위에 맞춰 결과를 고릅니다.
- `config-tap-v2.json`: 분석 설정입니다.
- `requirements-cpu.lock`: CPU 실행 의존성의 고정 버전입니다.
- `payload.json`: 앱 실행·갱신·패키징에서 사용하는 분석 소스 목록입니다.

CLI는 `python -m algorithms.fixed.hinted --help`로 확인할 수 있습니다. 음원을 처리할 때는 공식 모델을 `--checkpoint`로 지정합니다. DAW의 수동 템포·박자 맵 편집은 이 모듈과 별개로 동작합니다.
