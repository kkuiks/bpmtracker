# 외부 구성요소

각 구성요소의 원문 라이선스 적용.

| 구성요소 | 용도 | 출처 |
| --- | --- | --- |
| Electron / Chromium | 데스크톱 런타임 | [Electron](https://github.com/electron/electron), [Chromium](https://www.chromium.org/) |
| React | 화면 구성 | [React](https://github.com/facebook/react) |
| Lucide | 아이콘 | [Lucide](https://github.com/lucide-icons/lucide) |
| Python | 오디오 작업 실행 | [Python](https://www.python.org/) |
| Beat This! | 박·다운비트 관측, 공식 `final0` 모델 | [Beat This!](https://github.com/CPJKU/beat_this) |
| PyTorch / Torchaudio | 모델 실행·오디오 연산 | [PyTorch](https://pytorch.org/), [Torchaudio](https://github.com/pytorch/audio) |
| NumPy / SciPy | 수치 연산 | [NumPy](https://numpy.org/), [SciPy](https://scipy.org/) |
| SoundFile / libsndfile | 음원 읽기·WAV 출력 | [SoundFile](https://github.com/bastibe/python-soundfile), [libsndfile](https://github.com/libsndfile/libsndfile) |
| soxr | 샘플레이트 변환 | [python-soxr](https://github.com/dofuuz/python-soxr) |

Beat This! 코드·공식 모델: MIT. 저작권 표기:

> Copyright (c) 2024 Institute of Computational Perception, JKU Linz, Austria

[원문 라이선스](https://github.com/CPJKU/beat_this/blob/main/LICENSE) · [모델 사용 범위](docs/ANALYSIS.md#외부-모델과-의존성)

버전 기준: [프런트엔드 잠금 파일](apps/daw/package-lock.json), [Python 잠금 파일](algorithms/fixed/requirements-cpu.lock). Windows 번들에는 Electron·Chromium, Python 및 각 패키지의 원문 라이선스 고지 포함.
