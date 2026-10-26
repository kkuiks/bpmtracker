# 아키텍처

BPMTracker는 Windows 데스크톱 앱입니다. React 화면과 Electron이 프로젝트 편집·파일 작업을 담당하고, Web Audio와 Python worker가 재생·오디오 처리를 나눠 수행합니다.

## 구성

| 구성요소 | 주요 위치 | 역할 |
| --- | --- | --- |
| 사용자 화면 | `apps/daw/src/` | 트랙·이벤트·맵·믹서·편집 패널 |
| 프로젝트 모델 | `model.ts`, `music.ts`, `arrangement.ts`, `history.ts` | 좌표 변환, 편집과 Undo/Redo |
| 데스크톱 연결 | `electron/main.cjs`, `preload.cjs` | IPC, 파일 선택, 프로젝트 저장·복구와 worker 실행 |
| 오디오 재생 | `src/audio.ts`, `public/transport-worklet.js` | 버퍼 전송, 샘플 시계와 믹싱·클릭 |
| 오디오 작업 | `backend/worker.py` | 원음 디코딩, 재생용 변환, 분석과 출력 |
| 분석기 | `algorithms/fixed/` | 고정 템포·박자·다운비트 추정 |
| 라이브러리 | `electron/sample-library.cjs` | 사용자가 선택한 음원·타이밍 라이브러리 읽기와 초안 저장 |

## 오디오 흐름

음원을 가져오면 Python worker가 원음의 샘플레이트·채널·프레임 수를 기록하고 파형 표시 및 재생 버퍼를 준비합니다. 재생 버퍼는 48 kHz로 맞추며 원본 파일은 그대로 둡니다. Electron이 필요한 데이터를 전달하고 AudioWorklet이 같은 샘플 시계로 오디오·믹싱·메트로놈을 처리합니다.

디코딩 버퍼는 재생을 위한 캐시입니다. 프로젝트·Undo가 참조하는 데이터는 유지하고, 필요하지 않은 버퍼는 정리합니다. 캐시가 없어지면 동일한 원음에서 다시 만들 수 있습니다. 프로젝트 이동에는 원음도 함께 제공해야 합니다.

## 시간과 프로젝트 맵

프로젝트는 전체 BPM·박자표와 명시적인 Tempo/Signature 이벤트를 보관합니다. 이벤트 값은 다음 선언까지 유지됩니다. 구간이나 음원이 끝났다고 기본값으로 돌아가지 않습니다.

Linear 트랙은 초 단위 배치를, Musical 트랙은 quarter 좌표의 앵커를 유지합니다. 시간 기준을 바꾸는 순간에는 현재 배치를 보존합니다. 이후 맵 편집은 Musical 이벤트의 위치를 바꾸지만 원음의 속도·길이·소스 범위를 바꾸지 않습니다.

수동 맵 편집은 `src/music.ts`와 worker의 맵·출력 코드가 처리합니다. 분석 결과가 없어도 트랙 배치, 맵 편집과 메트로놈을 사용할 수 있습니다.

## 분석 흐름

1. 선택한 곡·구간의 원음 범위를 샘플 경계로 정합니다.
2. worker가 Beat This의 공식 `final0`로 박·다운비트 관측을 얻습니다.
3. `algorithms.fixed`가 오디오만으로 모든 후보와 점수를 준비합니다.
4. Tap을 입력했다면 박 단위를 선택한 뒤 하나의 BPM·박자·다운비트 위치를 반환합니다.
5. 원본 예측은 따로 저장합니다. 사용자는 결과를 편집·청취하고 **Apply & Align**에서 맵과 배치에 적용합니다.

입출력과 제약은 [분석 기능](ANALYSIS.md)을 참고하세요.

## 저장·복구·출력

`.bpmtracker` 프로젝트는 음원 정보, 트랙, 이벤트, 템포·박자 맵과 분석 원본·편집값을 보관합니다. **Save As → Collect original audio**는 원음을 프로젝트와 함께 모읍니다. 복구 정보와 재생 캐시는 각각 관리하며, 저장된 원음 경로가 달라졌다면 파일을 다시 지정합니다.

출력 작업은 요청 시점의 프로젝트 사본으로 실행합니다. WAV 믹스·스템·클릭은 같은 구간과 샘플 시계를 사용하고, JSON/MIDI는 프로젝트 맵을 표현합니다.

## 실행과 배포

소스 실행에서는 저장소의 `algorithms/fixed`를 읽고, 포터블 앱은 `resources/analysis/algorithms/fixed`를 읽습니다. 공식 모델은 소스의 `models/final0.ckpt` 또는 번들의 `resources/analysis/final0.ckpt`에 있습니다.

`algorithms/fixed/payload.json`이 분석 소스 목록의 기준입니다. 전체 패키징, `--refresh-app`, Windows launcher가 같은 `scripts/analysis_payload.py`를 사용합니다. 갱신은 관리 대상 앱·분석 소스만 교체하며 Python·모델·사용자 작업 폴더는 재사용합니다. 번들의 `analysis-payload.json`에서 소스별 해시와 revision을 확인할 수 있습니다.
