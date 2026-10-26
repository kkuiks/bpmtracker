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
        '1. WAV, MP3, FLAC 음원과 스템을 가져와 트랙에 배치합니다.\n'
        '2. 이동·복사·분할·트림하고 재생·믹싱·메트로놈을 사용합니다.\n'
        '3. Tempo/Signature 맵을 편집합니다. 원음의 속도와 길이는 유지됩니다.\n'
        '4. 필요하면 Analyze Audio로 선택한 곡·구간을 분석합니다. Tap은 박 단위만 선택합니다.\n'
        '5. Apply & Align으로 맵과 배치를 적용하고 프로젝트를 저장하거나 출력합니다.\n\n'
        '분석은 고정 템포와 3/4·4/4를 지원합니다. 녹음·VST·타임 스트레칭은 지원하지 않습니다.\n'
        'Save As의 Collect original audio로 프로젝트에 원음을 모을 수 있습니다.\n'
        'Restore Original Prediction은 저장값을 복원하며, 적용은 Apply & Align에서 별도로 합니다.\n', encoding='utf-8')
    return payload


def replace_archive(output):
    temporary = output.parent / (output.name + '.next.zip')
    try:
        shutil.make_archive(str(temporary.with_suffix('')), 'zip', root_dir=output.parent, base_dir=output.name)
        temporary.replace(output.with_suffix('.zip'))
    finally:
        temporary.unlink(missing_ok=True)


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
    args = parser.parse_args()
    output, runtime = args.output.resolve(), args.runtime_cache.resolve()
    package = json.loads((APP / 'package.json').read_text())
    if not (APP / 'dist/index.html').is_file():
        raise SystemExit('Run npm run build in apps/daw first')
    if args.refresh_app:
        payload = refresh_app(package, output)
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
    if args.zip:
        replace_archive(output)
    print(f'Windows portable app assembled: {output} ({payload["revision"]})', flush=True)


if __name__ == '__main__':
    main()
