# DAW

Windows x64 대상 Electron 앱. React·TypeScript 편집 화면, Web Audio·AudioWorklet 재생, Python worker 기반 오디오 처리.

## 모듈

| 경로 | 역할 |
| --- | --- |
| `src/` | 화면, 프로젝트 모델, 편집·재생 제어 |
| `electron/` | IPC, 파일 입출력, worker·캐시 관리 |
| `backend/worker.py` | 디코딩, 분석, WAV·맵 출력 |
| `public/transport-worklet.js` | 샘플 시계, 믹싱·메트로놈 |
| `scripts/` | Windows 실행·빌드 |
| `audit/` | 프로젝트·편집·작업 전환 검사 |

## 소스에서 실행하기

필수 환경: Node.js 24·npm, Python 3.12. 의존성 기준은 `package-lock.json`과 프로젝트 루트의 `algorithms/fixed/requirements-cpu.lock`.

모델: [Beat This! 공식 모델 목록](https://github.com/CPJKU/beat_this#available-models)의 `final0`를 프로젝트 루트 `models/final0.ckpt`에 배치.

Windows PowerShell, 프로젝트 루트 기준:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r algorithms/fixed/requirements-cpu.lock
cd apps/daw
npm ci
npm run build
npm run desktop
```

| 환경변수 | 의미 |
| --- | --- |
| `BPMTRACKER_PYTHON` | 기본 `.venv` 대신 사용할 Python 실행파일 |
| `BPMTRACKER_CHECKPOINT` | 기본 `models/final0.ckpt` 대신 사용할 모델 경로 |

준비된 Windows 개발 런타임이 있으면 루트 `Start BPMTracker.cmd`로 실행. Launcher는 빌드된 화면·Electron·backend·분석 소스를 복사하고 Python·모델은 재사용. 화면 변경 후 `npm run build`, 앱 재시작 필요.

## 포터블 빌드

Linux/WSL, 프로젝트 루트 기준. 대상은 Windows x64·CPython 3.12.10·CPU.

```bash
python3.12 -m venv .venv
cd apps/daw
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci
npm run build
cd ../..
.venv/bin/python apps/daw/scripts/package_windows.py --checkpoint models/final0.ckpt --zip
```

출력: `dist/BPMTracker-win-x64/`와 ZIP. Electron·Python·모델·고정 버전 wheel 포함. 실행 진입점은 `BPMTracker.exe`, 실행 단위는 폴더 전체.

앱 종료 후 소스 갱신:

```bash
.venv/bin/python apps/daw/scripts/package_windows.py --refresh-app
```

화면 변경 시 갱신 전에 `npm run build` 필요. 소스 수정만으로 기존 번들 내용이 바뀌지는 않음.

| 옵션 | 용도 |
| --- | --- |
| `--zip` | ZIP 생성·갱신 |
| `--output` | 출력 폴더 |
| `--runtime-cache` | 런타임 ZIP·wheel 캐시 |
| `--offline` | 캐시된 고정 버전만 사용 |
| `--resume` | 이 빌더의 미완료 출력 재개 |
| `--resource-editor` | [rcedit](https://github.com/electron/rcedit/releases/tag/v2.0.0) Windows 실행파일. 아이콘·버전 정보 설정 |

아이콘 원본: `public/app-icon.svg`. PNG·ICO 재생성: `npx electron scripts/create_icons.cjs`.

조립한 ZIP이 있는 WSL 환경의 Vite 연결: `npm run dev:windows`. Electron·backend·분석 소스 변경에는 앱 재시작 필요.

## 화면·입력 참조

| 영역·입력 | 동작 |
| --- | --- |
| Arrangement | 트랙·오디오 이벤트·Tempo·Signature 편집 |
| Inspector | 선택 항목·저장된 분석 참조 |
| Audio Editor / MixConsole | 상세 오디오 편집 / 트랙 믹싱 |
| View | 패널 표시·레이아웃 조절 |
| Object / Range / Split | 이벤트 선택·이동 / 시간·트랙 범위 / 분할 |
| 숫자 드래그·휠 | 값 조절. Shift로 미세 조절 |
| 숫자 더블클릭 | 직접 입력. Enter 적용, Escape 취소 |
| Ctrl-click | 볼륨·팬 기준값 복원 |
| Start·End·위치 | 시간 단위별 동일 폭. 가리킨 단위를 드래그·휠, 좌우키로 단위 선택 |

박 경계로 제한된 위치의 세부 단위는 표시 전용. BPM 직접 입력은 분수 허용. 트랙 선택과 이벤트·범위·맵 선택은 별도 상태.

## 오디오·트랙 편집 규칙

- 오디오 레인 드롭: 해당 트랙의 포인터 위치에 삽입. 레인 아래 드롭: 새 트랙 생성.
- Import Audio: 한 트랙에 순차 배치, 개별 트랙 또는 연결 스템으로 가져오기.
- 새 트랙 기본 시간 기준은 Linear. 기존 트랙으로 가져오면 시간 기준·믹서 설정 유지.
- 이벤트 이동·복사·트림·분할은 비파괴 편집. 트림 중 Ctrl은 Snap 임시 해제.
- Linked edits (`K`): 그룹의 이동·복사·분할·트림·삭제 동기화. 믹서 값은 트랙별 독립.
- Range 복사·이동: 빈 구간과 상대 트랙 간격 포함. 붙여넣기 기준은 목적 트랙의 커서.
- Ctrl D: 선택 이벤트·범위 전체를 바로 뒤에 복제.
- 같은 트랙의 오디오 중첩: 앞쪽 이벤트가 겹치는 구간 재생.
- 트랙 헤더: Ctrl-click 개별 선택, Shift-click 연속 선택, 드래그 순서 변경, 우클릭 관리.

## 재생·믹싱

- Space: 재생·정지. Stop은 현재 위치 유지, 정지 중 재입력 시 재생 시작 위치로 복귀.
- L/R Locators·Cycle: 반복 범위와 반복 재생.
- 메트로놈 켜짐: 앱 전체 설정으로 저장. 다른 프로젝트·재실행에도 유지.
- 클릭 볼륨: 프로젝트별 저장, 0 dB가 기본 기준. 클릭 출력에도 적용.
- Inspector·MixConsole: 트랙별 볼륨·팬·Mute·Solo. 볼륨 0 dB·팬 중앙에 기준선·스냅.

## 템포·박자 맵

| 항목 | 규칙 |
| --- | --- |
| 선언 유효 범위 | 다음 선언까지 유지. 오디오 끝에서 초기값 복귀 없음 |
| Signature 추가 | 레인 더블클릭 또는 Add Signature at Beat…에서 `3/4` 등 직접 입력 |
| Signature 수정 | 더블클릭, 선택 후 Enter·F2, Inspector 목록 |
| 마디 중간 변경 | 박 위치 삽입 허용. 4/4의 3박 시작에 3/4 삽입 시 앞마디에 2/4 자동 선언 |
| 자동 보정 | 원인 선언 수정·이동·삭제 시 재계산. 원인 편집과 한 번의 Undo/Redo |
| 보정 선언 선택 | 연결 버튼으로 다음 원인 선언 편집. 기존 선언이 짧아지면 요청값과 실제 길이 구분 |
| Position in previous meter | 변경 전 박자 그리드 기준 위치 입력 |
| Linear | 맵 편집 시 오디오의 초 단위 배치 유지 |
| Musical | quarter 앵커 유지, 맵 편집 시 배치 재계산 |
| 시간 기준 전환 | 현재 배치 보존. 원음의 속도·길이·소스 범위 유지 |
| 일반 값 수정·삭제 | 다른 맵 선언의 오디오 위치 보존 |
| 명시적 점 이동 | 선택한 선언 이동. 오디오와 함께 이동하면 하나의 history 편집 |
| 시작 선언 삭제 | 남은 첫 선언 값을 초기 구간에 적용. 이후 수정도 연동, 저장·재열기 후 유지 |
| 남은 선언 없음 | 기본값 120 BPM·4/4 |

선언 표시: 일반·자동 보정 모두 동일 레인·형태. 인접 선언은 표시 폭을 제한하고 hover·선택 시 전체 값 표시. Musical 트랙의 후속 배치는 앞부분 맵 변경의 영향을 받음.

## 분석과 정렬

입력 범위: 선택 이벤트 전체 또는 한 이벤트와 겹치는 Range·Audio Editor 구간. 초기 박 단위는 Tap 또는 후보 선택으로 확인. 세부 BPM·박자·변경점은 오디오에서 계산.

| 명령·상태 | 의미 |
| --- | --- |
| Analyze Audio | 원음 관측·템포·박자 맵 계산 |
| Audition / Audition original map | 원본 분석 맵 미리듣기 |
| Return to project | 현재 프로젝트 맵으로 복귀 |
| Apply & Align | 전체 맵과 곡·연결 스템의 배치를 한 번에 적용. Linked edits 설정과 독립 |
| ORIGINAL | 원본 분석 보관. 수동 맵 편집과 독립 |
| Restore Original Prediction | 기존 고정 분석의 저장값 복원. 프로젝트 맵 적용과는 별도 |

적용 후 편집 대상은 Tempo·Signature 이벤트. 수동 수정점과 충돌하는 재적용은 차단하며 해당 점 이동·삭제 후 재적용 가능. 분석 범위 밖의 새 변경점은 추정하지 않음.

[분석 명세](../../docs/ANALYSIS.md)

## 저장·복구·출력

- `.bpmtracker`: 트랙·이벤트·원음 정보, 전체 BPM·박자·맵 이벤트, 원본 분석·편집값.
- Save As → Collect original audio: 프로젝트와 원음 수집. 기본 저장은 원음 경로 참조.
- 복구 정보·디코딩 캐시는 별도 관리. 캐시가 없어도 동일 원음에서 재생 버퍼 재생성.
- WAV 출력: 믹스·트랙별 스템·메트로놈 클릭. 동일 시간 원점·길이 사용.
- JSON·MIDI 출력: 현재 프로젝트 맵. JSON은 원본 분석 별도 보관, MIDI는 tick 단위 양자화.
- 저장·출력에 따른 원음 덮어쓰기 없음.

## 단축키

| 입력 | 동작 |
| --- | --- |
| 1 / 2 / 3 | Object / Range / Split |
| Space / Num Enter | 재생·정지 / 재생·재개 |
| Ctrl E / 이벤트 더블클릭 | Audio Editor |
| Ctrl Z / Ctrl Shift Z | Undo / Redo |
| Ctrl C / X / V / D | 복사 / 잘라내기 / 붙여넣기 / 복제 |
| Alt-drag / Alt X | 이벤트 복사 / 커서에서 분할 |
| Ctrl G / Ctrl U / K | 그룹 / 그룹 해제 / Linked edits |
| Ctrl S / Ctrl Shift S | Save / Save As |
| T | Add Audio Track. Tap 입력 중에는 탭 |
| Ctrl-wheel / Shift-wheel | 포인터 기준 확대 / 가로 스크롤 |

## 오류 확인

| 증상 | 확인 대상 |
| --- | --- |
| 모델 없음 | `models/final0.ckpt` 또는 `BPMTRACKER_CHECKPOINT` |
| 분석 소스 없음 | 현재 launcher·`--refresh-app`의 분석 payload |
| 원음 없음 | 원음 경로 재지정 또는 Collect original audio 결과 |
| 클릭 불일치 | 초기 박 단위, Tempo·Signature 선언, 원음 기준 위치 |

[아키텍처](../../docs/ARCHITECTURE.md) · [계약 검사](audit/README.md)
