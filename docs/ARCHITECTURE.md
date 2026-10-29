# 아키텍처

## 구성

앱 경로는 `apps/daw/` 기준.

| 구성요소 | 경로 | 역할 |
| --- | --- | --- |
| 화면 | `src/` | 트랙·이벤트·맵·믹서·편집 패널 |
| 프로젝트 모델 | `src/model.ts`, `src/music.ts`, `src/arrangement.ts`, `src/history.ts` | 데이터 구조, 좌표 변환, 편집·Undo/Redo |
| 데스크톱 | `electron/main.cjs`, `electron/preload.cjs` | IPC, 파일 선택, 저장·복구, worker 실행 |
| 재생 | `src/audio.ts`, `public/transport-worklet.js` | 버퍼 전송, 샘플 시계, 믹싱·클릭 |
| 오디오 작업 | `backend/worker.py` | 디코딩, 재생용 변환, 분석·출력 |
| 맵 추정 | `algorithms/tempo_map/` — 프로젝트 루트 기준 | 초기 템포·박자, 변경 이벤트 |
| 관측·초기 후보 | `algorithms/fixed/` — 프로젝트 루트 기준 | Beat This 관측, 후보 준비, 고정 분석 API |

## 오디오 경로

```text
원음 → Python 디코딩 → 파형·48 kHz 재생 버퍼
     → Electron 버퍼 전송 → AudioWorklet 믹싱·메트로놈 → 출력
```

- 원음 정보: 샘플레이트·채널·프레임 수·소스 범위. 원본 파일은 비파괴 유지.
- 재생 버퍼: 파생 캐시. 프로젝트·Undo에서 참조 중인 버퍼 유지, 미참조 버퍼 정리.
- 캐시 복구: 동일한 원음에서 재생 버퍼 재생성. 프로젝트 이동 시 원음 필요.
- 오디오·메트로놈: 동일한 AudioWorklet 샘플 시계 사용.

## 시간 좌표·맵

| 항목 | 규칙 |
| --- | --- |
| 프로젝트 맵 | 전체 BPM·박자표와 명시적 Tempo·Signature 이벤트 |
| 이벤트 유효 범위 | 다음 선언까지 유지. 오디오·분석 범위 끝에서 기본값으로 복귀하지 않음 |
| Linear 트랙 | 초 단위 배치 유지 |
| Musical 트랙 | quarter 앵커 유지. 맵 편집 시 이벤트 위치 재계산 |
| 시간 기준 전환 | 전환 시점의 배치 보존 |
| 원음 | 시간 기준·맵 편집에 따른 속도·길이·소스 범위 변경 없음 |
| 편집 처리 | `src/music.ts`, `arrangement.ts`, worker의 맵·출력 코드 |

수동 맵 편집과 재생에는 분석 결과가 필수 아님.

## 분석 데이터 흐름

1. 선택한 원음 범위를 샘플 경계로 제한.
2. Beat This `final0`의 박·다운비트 관측 추출. 원음·범위·분석 소스·모델 식별이 일치하는 캐시는 재사용.
3. `algorithms.fixed`와 `algorithms.tempo_map`에서 오디오 후보 준비.
4. 필요한 초기 박 단위를 Tap 또는 확인 입력으로 선택. 후보가 여러 개면 확인 요청.
5. 별도 Python 프로세스에서 초기 상태·변경 이벤트 계산.
6. 원본 결과·입력 범위·보조 입력·분석기 식별 저장.

| 상태 | 데이터·동작 |
| --- | --- |
| 원본 분석 | `Analysis.result`와 입력 정보. 수동 맵 편집과 독립 |
| 미리듣기 | `Clock.kind=map`에 연결된 원본 분석을 재생 구간으로 변환. 프로젝트 맵 변경 없음 |
| 적용 맵 | 프로젝트 `tempos`·`signatures`. 편집·재생·출력의 기준 |
| Apply & Align | 맵 적용과 곡·연결 스템 이동을 한 번의 history 편집으로 처리 |

분석 중 중복 실행은 차단. 완료·실패 결과 전달 시 다음 분석 허용, 종료 전 프로세스는 정리 대상으로 계속 추적.

프로젝트 형식은 버전 3. 버전 1·2와 기존 고정 분석도 로드. 저장된 분석 재생·프로젝트 재열기에는 재추론 불필요.

## 저장·출력

- `.bpmtracker`: 음원 정보, 트랙·이벤트, 프로젝트 맵, 분석 원본·편집값.
- `Save As → Collect original audio`: 프로젝트와 원음 수집.
- 복구 정보와 디코딩 캐시는 별도 관리. 원음 경로 변경 시 파일 재지정 필요.
- 출력 입력: 요청 시점 프로젝트 사본.
- WAV 믹스·스템·클릭: 동일 구간·샘플 시계.
- JSON·MIDI: 현재 프로젝트 맵. JSON에는 원본 분석과 가변 구간도 별도 보관.
- 클릭·맵 출력에는 원음 PCM 불필요. 믹스·스템 출력에는 원음 버퍼 사용.

## 실행·패키징

| 항목 | 소스 실행 | Windows 번들 |
| --- | --- | --- |
| 분석 코드 | `algorithms/tempo_map`, `algorithms/fixed` | `resources/analysis/algorithms/` |
| 모델 | `models/final0.ckpt` | `resources/analysis/final0.ckpt` |

분석 소스 기준은 `algorithms/fixed/payload.json`. 전체 패키징·`--refresh-app`·Windows launcher가 `scripts/analysis_payload.py`를 공유. 갱신 대상은 관리 중인 앱·분석 소스이며, Python·모델·사용자 작업 폴더는 재사용. 번들 `analysis-payload.json`에 소스별 해시와 revision 기록.

[분석 명세](ANALYSIS.md) · [실행·빌드](../apps/daw/README.md#소스에서-실행하기)
