# BPMTracker 사용자 가이드

Windows에서 음원·스템을 편집하고 템포·박자 맵을 관리하는 DAW입니다. 화면의 메뉴와 버튼 이름은 영어입니다.

## 실행

포터블 앱은 **BPMTracker.exe**로 실행합니다. 실행 파일과 `resources` 폴더를 함께 보관하세요. 소스 실행은 [소스에서 실행하기](#소스에서-실행하기)를 참고하세요.

준비된 개발 런타임이 있는 소스 체크아웃에서는 루트의 **Start BPMTracker.cmd**를 사용합니다. 앱과 분석 소스를 갱신하려면 실행 중인 창을 닫고 다시 시작합니다.

## 기본 작업

1. 음원·스템을 드래그하거나 **File → Import Audio**로 가져옵니다.
2. 트랙에 배치하고 재생하면서 이동·복사·분할·트림합니다.
3. 볼륨·팬·메트로놈을 조절하고 Tempo/Signature 맵을 편집합니다.
4. 필요하면 곡 또는 구간의 **Analyze Audio**를 실행하고 결과를 청취합니다.
5. **Apply & Align**으로 분석값과 배치를 적용한 뒤 프로젝트를 저장하거나 출력합니다.

분석은 선택 사항입니다. 음원을 직접 배치하고 맵을 입력하는 작업부터 시작할 수 있습니다.

## 화면과 선택

중앙 Arrangement에서 트랙과 오디오 이벤트를 편집합니다. Inspector는 선택한 항목을, 아래쪽 **Audio Editor / MixConsole**은 상세 편집과 믹싱을 표시합니다. **View** 메뉴에서 패널을 열고 경계선을 드래그해 크기를 조절합니다.

Object 도구는 이벤트를 선택·이동하고 Range 도구는 시간·트랙 범위를 선택합니다. Tempo/Signature 맵의 점도 선택해 값을 편집하거나 이동할 수 있습니다. 트랙 헤더의 선택은 이벤트·구간·맵 선택과 구분됩니다.

숫자 값은 드래그·휠로 조절하거나 더블클릭해 직접 입력합니다. Enter로 적용하고 Escape로 취소합니다. Shift는 미세 조절, Ctrl-click은 볼륨·팬 같은 값의 기준 복원에 사용합니다. BPM 직접 입력은 분수도 받습니다.

## 음원과 트랙

음원 하나를 오디오 레인에 놓으면 해당 트랙의 포인터 위치에 들어갑니다. 레인 아래로 놓으면 트랙을 만듭니다. Import Audio에서는 한 트랙에 순서대로 배치하거나, 각각 다른 트랙 또는 연결된 스템으로 가져올 수 있습니다.

새 트랙은 **Linear**입니다. 기존 트랙으로 가져오면 그 트랙의 시간 기준과 믹서 설정을 유지합니다. 가져온 원음은 비파괴 편집하며, 원음을 프로젝트와 모으려면 **Save As → Collect original audio**를 사용합니다.

트랙 헤더에서 Ctrl-click은 개별 선택, Shift-click은 연속 선택입니다. 헤더를 드래그해 순서를 바꾸고 우클릭 메뉴로 트랙을 관리합니다.

## 오디오 편집

이벤트는 다른 트랙으로 이동하거나 Alt-drag로 복사할 수 있습니다. 분할은 Split 도구, Alt-click 또는 커서 위치의 Alt X를 사용합니다. 가장자리를 트림하면 원음의 범위만 달라지고 속도는 유지됩니다. Ctrl은 트림·구간 드래그 중 Snap을 임시로 해제합니다.

**Linked edits** (`K`)는 스템 그룹의 이동·복사·분할·트림·삭제를 함께 처리합니다. Ctrl G로 그룹을 만들고 Ctrl U로 풉니다. 믹서 값은 트랙별로 조절하며, **Apply & Align**은 Linked edits 설정과 관계없이 연결된 스템을 함께 이동합니다.

Range 선택은 빈 구간과 트랙 사이 간격을 포함해 복사·이동합니다. 붙여넣기는 선택한 목적 트랙의 커서에서 시작하며 상대적인 트랙 간격을 유지합니다. Ctrl D는 이벤트 선택 범위 또는 선택 구간 전체를 바로 뒤에 복제합니다.

이벤트 더블클릭, Ctrl E 또는 이벤트가 선택된 상태의 Return으로 **Audio Editor**를 엽니다. 이 패널에서 확대·구간 선택·트림·분할과 분석을 할 수 있습니다. 같은 트랙의 이벤트가 겹치면 앞쪽 이벤트가 겹치는 구간을 재생합니다.

## 재생과 믹싱

Space는 재생·정지를 전환합니다. Stop은 현재 위치를 유지하고, 정지 중 다시 Stop하면 재생을 시작했던 위치로 돌아갑니다. 아래 눈금이나 커서를 드래그해 위치를 옮깁니다. Locators로 루프 범위를 지정할 수 있습니다.

Inspector와 MixConsole에서 볼륨·팬·Mute·Solo를 조절합니다. 볼륨 0 dB와 팬 중앙에는 기준선과 스냅이 있으며 Shift-drag는 미세 조절입니다. Ctrl-click으로 기준값을 복원합니다. 클릭 볼륨은 별도로 저장되며 클릭 출력에도 적용됩니다.

## 템포·박자 맵

Tempo/Signature 트랙에서 값을 입력하거나 점을 편집합니다. 전체 프로젝트 값과 명시적인 맵 이벤트를 구분하며, 이벤트 값은 다음 선언까지 이어집니다. 곡이나 구간이 끝나도 이전 기본값으로 자동 복귀하지 않습니다.

| 시간 기준 | 맵을 나중에 편집했을 때 |
| --- | --- |
| Linear | 이벤트의 초 단위 배치를 유지합니다. |
| Musical | quarter 앵커를 유지하므로 이벤트 위치가 맵을 따라 움직입니다. |

시간 기준을 전환할 때는 현재 배치를 보존합니다. 원음의 소스 범위·길이·재생 속도는 두 모드 모두 유지합니다. 앞부분의 맵을 바꾸면 뒤쪽 Musical 트랙의 위치도 달라질 수 있으므로 배치를 확인하세요.

일반적인 값 편집·삭제는 다른 맵 선언의 오디오 위치를 유지합니다. 선택한 점을 명시적으로 이동하면 해당 점이 이동합니다. 오디오와 맵 점을 함께 선택해 이동할 때는 하나의 편집으로 Undo/Redo합니다.

## 분석과 정렬

**Analyze Audio**는 곡 또는 한 오디오 이벤트와 겹치는 선택 구간에 하나의 고정 BPM·박자·다운비트 위치를 제안합니다. 지원 박자는 3/4·4/4이며, 변속·변박을 자동 추정하지 않습니다.

필요하면 **Tap**에서 처음 부분의 quarter 박을 입력합니다. 탭은 두 배·절반 계열의 박 단위를 고르는 용도입니다. 세부 BPM과 위치는 오디오에서 구합니다. 결과가 모호하거나 약하면 flag가 표시될 수 있으므로 클릭을 청취하세요.

원본 예측과 편집한 저장값은 따로 보관합니다. 저장된 값을 청취하는 것은 적용과 다릅니다. **Restore Original Prediction**은 저장값만 복원하며, **Apply & Align**에서 기준 마디·이동량을 확인한 뒤 프로젝트 맵과 곡·스템 배치에 적용합니다.

분석 범위 밖을 새로 예측하지는 않습니다. 적용한 맵 값은 다음 선언까지 유지됩니다. 분석 방식과 입력·출력은 [분석 기능](../../docs/ANALYSIS.md)에 설명되어 있습니다.

## 저장·복구·출력

프로젝트는 `.bpmtracker`로 저장합니다. 트랙·이벤트·원음 정보, 전체 BPM·박자와 맵 이벤트, 원본 분석과 저장값을 함께 보관합니다. **Save As → Collect original audio**를 사용하면 프로젝트와 원음을 함께 이동할 수 있습니다.

앱은 복구 정보와 디코딩 캐시를 따로 관리합니다. 캐시가 없어도 동일한 원음을 찾으면 다시 만들 수 있습니다. 원음 경로가 바뀌면 원본 파일을 다시 지정합니다. 캐시를 원음이나 프로젝트의 보관본으로 사용하지 마세요.

출력에서는 필요한 범위를 선택하고 WAV 믹스·트랙별 스템·메트로놈 클릭과 JSON/MIDI 템포 맵을 만들 수 있습니다. 오디오 출력은 같은 시간 원점과 길이를 사용합니다. 저장·출력은 원음을 덮어쓰지 않습니다.

## Samples와 타이밍 참조

**Samples**는 사용자가 선택한 음원·타이밍 라이브러리를 여는 선택 기능입니다. 준비된 `catalog.json`과 그 파일이 가리키는 상대 경로의 음원·참조 JSON이 같은 라이브러리 안에 있어야 합니다. 앱에는 라이브러리 음원이 포함되지 않습니다.

**Sample Reference**에서 준비된 클릭·맵을 확인할 수 있습니다. **Open candidate review…**는 호환되는 `daw-review.json`을 엽니다. 초안을 저장하면 별도의 프로젝트·제안 파일을 만들며 라이브러리의 원본 참조는 그대로 둡니다.

## 주요 단축키

| 조작 | 기능 |
| --- | --- |
| 1 / 2 / 3 | Object / Range / Split 도구 |
| Space / Num Enter | 재생·정지 / 재생·재개 |
| Ctrl E / 이벤트 더블클릭 | Audio Editor |
| Ctrl Z / Ctrl Shift Z | Undo / Redo |
| Ctrl C / X / V / D | 복사 / 잘라내기 / 붙여넣기 / 복제 |
| Alt-drag / Alt X | 이벤트 복사 / 커서에서 분할 |
| Ctrl G / Ctrl U / K | 그룹 / 그룹 해제 / Linked edits |
| Ctrl S / Ctrl Shift S | Save / Save As |
| T | Add Audio Track. 분석의 Tap 입력 중에는 탭으로 동작 |
| Ctrl-wheel / Shift-wheel | 포인터 기준 확대 / 가로 스크롤 |

## 소스에서 실행하기

Node.js와 npm, Python 3.12가 필요합니다. Python 의존성은 `algorithms/fixed/requirements-cpu.lock`, 프런트엔드 의존성은 이 디렉터리의 `package-lock.json`을 사용합니다. 모델은 [공식 Beat This 목록](https://github.com/CPJKU/beat_this#available-models)의 `final0`를 루트의 `models/final0.ckpt`에 준비합니다.

Windows PowerShell에서 저장소 루트를 기준으로 실행합니다.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r algorithms/fixed/requirements-cpu.lock
cd apps/daw
npm ci
npm run build
npm run desktop
```

다른 Python 또는 모델 위치를 사용하려면 실행 전에 `BPMTRACKER_PYTHON`과 `BPMTRACKER_CHECKPOINT`를 지정합니다. 실제 Windows Electron 앱이 사용되며, 브라우저 화면만으로 파일·분석 기능을 대신 실행하지 않습니다.

## 포터블 앱 만들기

Linux/WSL에서는 Python과 Node.js/npm으로 Windows x64 / CPython 3.12.10 CPU 번들을 만듭니다. 저장소 루트에서 진행합니다.

```bash
python3.12 -m venv .venv
cd apps/daw
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci
npm run build
cd ../..
.venv/bin/python apps/daw/scripts/package_windows.py --checkpoint models/final0.ckpt --zip
```

모델과 고정 버전의 Windows runtime·wheel을 모아 `dist/BPMTracker-win-x64`와 ZIP을 만듭니다. 라이브러리 버전은 잠금 파일을 따릅니다. 준비한 번들은 Windows에서 별도의 Python·Node.js·WSL 없이 실행됩니다.

앱을 닫은 뒤 작은 앱·분석 소스만 갱신할 때는 다음을 사용합니다.

```bash
.venv/bin/python apps/daw/scripts/package_windows.py --refresh-app
```

Python 환경과 모델은 유지됩니다. `--zip`을 추가하면 ZIP도 갱신합니다. `--output`은 작업용 출력 경로, `--runtime-cache`는 ZIP·wheel 캐시 위치, `--offline`은 이미 있는 고정 버전 캐시만 사용하는 옵션입니다. `--resume`은 이 빌더가 만든 미완료 출력을 이어갑니다.

조립한 ZIP이 있는 WSL 체크아웃에서는 `npm run dev:windows`로 실제 Windows 앱을 Vite와 연결할 수 있습니다. 프런트엔드가 갱신되며 Electron·backend·분석 소스를 바꿨다면 앱을 닫고 다시 시작합니다.

## 문제 해결과 지원 범위

- 모델을 찾지 못하면 `models/final0.ckpt` 또는 지정한 `BPMTRACKER_CHECKPOINT`를 확인합니다.
- 분석 소스가 없다는 메시지가 나오면 앱을 닫고 현재 launcher 또는 `--refresh-app`로 갱신합니다.
- 원음을 찾지 못하면 저장 시 사용한 원본을 다시 지정하거나 Collect original audio로 모은 폴더를 제공합니다.
- 일정하지 않은 템포·박자는 프로젝트 맵에 직접 입력합니다. 자동 분석의 결과와 수동 편집 범위는 다릅니다.
- 녹음, VST, MIDI 연주 편집, 타임 스트레칭·피치 변경, FX·자동화는 지원하지 않습니다.

앱의 데이터 흐름은 [아키텍처](../../docs/ARCHITECTURE.md), 분석 설정과 외부 모델 출처는 [분석 기능](../../docs/ANALYSIS.md)을 참고하세요.
