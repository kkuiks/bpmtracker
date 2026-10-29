"""Assemble or refresh the Windows app with its pinned CPU analysis runtime."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from analysis_payload import sync_analysis

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
PYTHON_VERSION = '3.12.10'


def download(url, target, offline=False):
    if target.is_file():
        return
    if offline:
        raise FileNotFoundError(f'Required cached runtime is missing: {target.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f'Download {target.name}', flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'BPMTracker-Build/0.1'})
    with urllib.request.urlopen(request, timeout=120) as source, target.open('wb') as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def refresh_app(package, output):
    resource = output / 'resources'
    if not (output / 'BPMTracker.exe').is_file() or not (resource / 'python/python.exe').is_file() or not (resource / 'analysis/final0.ckpt').is_file():
        raise SystemExit('Assemble the complete Windows runtime before refreshing application files')
    target = resource / 'app'
    for directory in ['dist', 'electron', 'backend']:
        if (target / directory).exists():
            shutil.rmtree(target / directory)
        shutil.copytree(APP / directory, target / directory, ignore=shutil.ignore_patterns('__pycache__'))
    (target / 'package.json').write_text(json.dumps({'name': 'bpmtracker-daw', 'productName': 'BPMTracker', 'version': package['version'], 'main': 'electron/main.cjs'}, indent=2), encoding='utf-8')
    payload = sync_analysis(resource / 'analysis')
    (output / 'START HERE.txt').write_text(
        'BPMTracker\n\nWindows에서 BPMTracker.exe를 실행하세요. 폴더 전체를 함께 보관하세요.\n'
        '조립이 끝난 포터블 앱은 Node.js, Python, WSL 또는 네트워크 연결 없이 실행됩니다.\n\n'
        '1. 사용할 곡을 가져와 오디오 이벤트 또는 분석할 구간을 선택합니다.\n'
        '2. Analyze Audio로 템포·박자 맵을 만듭니다. 필요하면 Tap / Confirm에서 초기 박 단위를 확인합니다.\n'
        '3. Audition으로 원곡과 분석 맵을 듣고 Return to project로 현재 프로젝트에 돌아옵니다.\n'
        '4. 기준 마디·이동량을 확인한 뒤 Apply & Align으로 맵과 배치를 적용합니다.\n'
        '5. Tempo/Signature 점을 선택하고 값을 더블클릭해 수정합니다. Enter로 적용하고 Ctrl Z로 되돌립니다.\n'
        '6. 메트로놈이 꺼져 있으면 C로 켜고 Space로 재생합니다. L/R Locators와 Cycle로 필요한 곳을 반복해 확인합니다.\n'
        '7. Save As로 프로젝트를 저장합니다. 다시 열면 맵과 수정값이 유지됩니다. 메트로놈의 마지막 켜짐 상태도 앱 전체 설정으로 기억합니다.\n\n'
        '분석 원본은 ORIGINAL로 보관되며 수동 맵 편집으로 바뀌지 않습니다. 원음의 속도와 길이도 유지됩니다.\n'
        '자동 분석은 초기 템포·박자와 변경점을 제안합니다. 클릭을 듣고 맞지 않는 부분은 직접 수정합니다.\n'
        'Save As의 Collect original audio로 프로젝트에 원음을 모을 수 있습니다.\n'
        'WAV 믹스·스템·클릭과 JSON/MIDI 맵을 출력할 수 있습니다. 녹음·VST·타임 스트레칭은 지원하지 않습니다.\n', encoding='utf-8')
    licenses = output / 'licenses'
    licenses.mkdir(exist_ok=True)
    for module, filename in [('react', 'React.txt'), ('react-dom', 'ReactDOM.txt'), ('lucide-react', 'Lucide.txt')]:
        shutil.copyfile(APP / 'node_modules' / module / 'LICENSE', licenses / filename)
    (output / 'THIRD_PARTY_NOTICES.txt').write_text(
        'BPMTracker — 외부 구성요소\n\n'
        '각 구성요소에는 해당 프로젝트의 원문 라이선스가 적용됩니다.\n'
        'Electron: LICENSE / Chromium: LICENSES.chromium.html\n'
        'React, ReactDOM, Lucide: licenses 폴더\n'
        'Python: resources/python/LICENSE.txt\n'
        'Beat This!, PyTorch, Torchaudio, NumPy, SciPy, SoundFile, soxr 등:\n'
        'resources/python/Lib/site-packages의 각 *.dist-info 폴더에 원문 고지가 있습니다.\n\n'
        '박·다운비트 관측에는 Beat This!의 공식 final0 모델을 사용합니다.\n'
        '코드와 공식 모델은 MIT 라이선스로 제공됩니다.\n'
        'Copyright (c) 2024 Institute of Computational Perception, JKU Linz, Austria\n'
        '원문: resources/python/Lib/site-packages/beat_this-1.1.0.dist-info/licenses/LICENSE\n'
        'https://github.com/CPJKU/beat_this\n', encoding='utf-8')
    return payload


def replace_archive(output):
    temporary = output.parent / (output.name + '.next.zip')
    try:
        shutil.make_archive(str(temporary.with_suffix('')), 'zip', root_dir=output.parent, base_dir=output.name)
        temporary.replace(output.with_suffix('.zip'))
    finally:
        temporary.unlink(missing_ok=True)


def brand_windows(output, editor, package):
    if not editor:
        return
    def windows_path(value):
        if sys.platform == 'win32':
            return str(value.resolve())
        return subprocess.check_output(['wslpath', '-w', str(value.resolve())], text=True).strip()
    icon = APP / 'public/app-icon.ico'
    if not icon.is_file() or not editor.is_file():
        raise SystemExit('Provide rcedit and generate public/app-icon.ico before setting Windows resources')
    subprocess.run([str(editor.resolve()), windows_path(output / 'BPMTracker.exe'),
                    '--set-icon', windows_path(icon),
                    '--set-file-version', package['version'] + '.0',
                    '--set-product-version', package['version'],
                    '--set-version-string', 'FileDescription', 'BPMTracker',
                    '--set-version-string', 'ProductName', 'BPMTracker',
                    '--set-version-string', 'CompanyName', 'BPMTracker',
                    '--set-version-string', 'InternalName', 'BPMTracker',
                    '--set-version-string', 'OriginalFilename', 'BPMTracker.exe'], check=True)


def cached_wheel(folder, requirement):
    name, version = requirement.split('==')
    normalized = name.lower().replace('-', '_')
    for wheel in sorted(folder.glob('*.whl')):
        parts = wheel.name.split('-')
        if (parts[0].lower().replace('-', '_') == normalized and parts[1] == version
                and wheel.name.endswith(('win_amd64.whl', 'any.whl'))):
            return wheel
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Resume an incomplete bundle created by this builder')
    parser.add_argument('--refresh-app', action='store_true', help='Refresh UI, backend and analysis source; reuse Python and checkpoint')
    parser.add_argument('--zip', action='store_true', help='Write the portable ZIP after assembly/refresh')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/BPMTracker-win-x64')
    parser.add_argument('--runtime-cache', type=Path, default=ROOT / '.daw-runtime')
    parser.add_argument('--checkpoint', type=Path, default=ROOT / 'models/final0.ckpt')
    parser.add_argument('--offline', action='store_true', help='Use the existing runtime ZIPs and exact pinned wheels without downloading')
    parser.add_argument('--resource-editor', type=Path, help='Optional Windows rcedit executable for the app icon and version details')
    args = parser.parse_args()
    output, runtime = args.output.resolve(), args.runtime_cache.resolve()
    package = json.loads((APP / 'package.json').read_text())
    if not (APP / 'dist/index.html').is_file():
        raise SystemExit('Run npm run build in apps/daw first')
    if args.refresh_app:
        payload = refresh_app(package, output)
        brand_windows(output, args.resource_editor, package)
        if args.zip:
            replace_archive(output)
        print(f'Application and analysis source refreshed: {output} ({payload["revision"]})', flush=True)
        return
    if output.exists() and not args.resume:
        raise SystemExit('Output already exists. Choose a new output directory or resume this builder\'s incomplete output.')
    if not args.checkpoint.is_file():
        raise SystemExit('Provide the official final0 checkpoint with --checkpoint or place it in models/final0.ckpt')
    electron = package['devDependencies']['electron']
    electron_zip = runtime / f'electron-v{electron}-win32-x64.zip'
    python_zip = runtime / f'python-{PYTHON_VERSION}-embed-amd64.zip'
    download(f'https://github.com/electron/electron/releases/download/v{electron}/{electron_zip.name}', electron_zip, args.offline)
    download(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/{python_zip.name}', python_zip, args.offline)
    wheels = runtime / 'windows-wheels'
    wheels.mkdir(parents=True, exist_ok=True)
    lock = (ROOT / 'algorithms/fixed/requirements-cpu.lock').read_text()
    requirements = [line.strip() for line in lock.splitlines() if '==' in line and not line.lstrip().startswith('#')]
    common = [sys.executable, '-m', 'pip', 'download', '--dest', str(wheels), '--platform', 'win_amd64', '--python-version', '312', '--implementation', 'cp', '--abi', 'cp312', '--only-binary=:all:', '--no-deps', '--cache-dir', str(runtime / 'pip-cache')]
    for cpu in [True, False]:
        missing = [r for r in requirements if (r.split('==')[0] in {'torch', 'torchaudio'}) == cpu and cached_wheel(wheels, r) is None]
        if missing:
            if args.offline:
                raise SystemExit('Missing pinned cached wheels: ' + ', '.join(missing))
            index = ['--index-url', 'https://download.pytorch.org/whl/cpu'] if cpu else []
            subprocess.run(common + index + missing, check=True)
    selected = [cached_wheel(wheels, r) for r in requirements]
    if any(wheel is None for wheel in selected):
        raise SystemExit('The exact pinned Windows wheel set is incomplete')
    output.mkdir(parents=True, exist_ok=True)
    print('Extract Windows Electron runtime', flush=True)
    with zipfile.ZipFile(electron_zip) as archive:
        archive.extractall(output)
    (output / 'electron.exe').replace(output / 'BPMTracker.exe')
    resource = output / 'resources'
    analysis = resource / 'analysis'
    analysis.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.checkpoint, analysis / 'final0.ckpt')
    python = resource / 'python'
    python.mkdir(exist_ok=True)
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(python)
    (python / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n', encoding='utf-8')
    site = python / 'Lib/site-packages'
    site.mkdir(parents=True, exist_ok=True)
    for wheel in selected:
        print(f'Install {wheel.name}', flush=True)
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                parts = info.filename.split('/')
                if parts[0].endswith('.data'):
                    if len(parts) > 2 and parts[1] in ('purelib', 'platlib'):
                        relative = Path(*parts[2:])
                    else:
                        continue
                else:
                    relative = Path(*parts)
                destination = site / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open('wb') as target:
                    shutil.copyfileobj(source, target)
    payload = refresh_app(package, output)
    brand_windows(output, args.resource_editor, package)
    if args.zip:
        replace_archive(output)
    print(f'Windows portable app assembled: {output} ({payload["revision"]})', flush=True)


if __name__ == '__main__':
    main()
