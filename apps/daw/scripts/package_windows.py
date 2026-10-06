"""Assemble or refresh a portable Windows app from a built frontend.

Runtime packages are cached locally. The bundle contains the pinned CPU
analysis environment and a local official checkpoint.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import argparse

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
RUNTIME = ROOT / '.daw-runtime'
OUTPUT = ROOT / 'dist' / 'Joljak-win-x64'
PYTHON_VERSION = '3.12.10'


def download(url, target):
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f'Download {target.name}', flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'Joljak-Build/0.1'})
    with urllib.request.urlopen(request, timeout=120) as source, target.open('wb') as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)


def refresh_app(package):
    resource = OUTPUT / 'resources'
    if not (OUTPUT / 'Joljak.exe').is_file() or not (resource / 'python/python.exe').is_file():
        raise SystemExit('Assemble the complete Windows runtime before refreshing application files')
    target = resource / 'app'
    for directory in ['dist', 'electron', 'backend']:
        if directory == 'dist' and (target / directory).exists():
            shutil.rmtree(target / directory)
        shutil.copytree(APP / directory, target / directory,
                        ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    (target / 'package.json').write_text(json.dumps({'name': 'joljak-daw', 'productName': 'Joljak', 'version': package['version'], 'main': 'electron/main.cjs'}, indent=2), encoding='utf-8')
    (OUTPUT / 'START HERE.txt').write_text(
        'Joljak\n\nRun Joljak.exe on Windows. Keep the whole folder together.\n'
        'No Node.js, Python, WSL or network connection is needed at runtime.\n\n'
        'Import WAV, MP3 or FLAC. Select a song or a range inside one reference event, then Analyze Audio.\n'
        'Drop a file at its timeline position, or use Import Audio for one track, different tracks or linked stems.\n'
        'T opens Add Audio Track. Right-click tracks to duplicate/remove; drag headers to reorder.\n'
        'Object-tool double-click or Ctrl E opens Audio Editor: zoom, range selection, trim and split.\n'
        'Drag a selected range to move its contents; Alt copies. Ctrl D duplicates the complete range.\n'
        'Range clipboard preserves gaps. Paste uses the selected destination track.\n'
        'A tap chooses the metrical layer only. Apply & Align moves the song and linked stems onto the project grid.\n'
        'Use the Tempo/Signature tracks, Linear/Musical track switch and bottom Transport with click volume.\n'
        'Tempo/signature values hold until the next event. Drag the lower ruler/cursor to seek.\n'
        'Stop keeps the current position; Start resumes. Second Stop returns to playback start.\n'
        'Bottom BPM changes the map from the cursor; earlier tempo stays unchanged.\n'
        'Restore Original Prediction changes saved values only. Apply & Align separately.\n\n'
        'Analysis supports constant tempo and 3/4 or 4/4; tempo and meter changes are not detected automatically.\n'
        'No recordings or accepted reference maps are included.\n', encoding='utf-8')


def replace_archive():
    temporary = ROOT / 'dist/Joljak-win-x64.next.zip'
    try:
        shutil.make_archive(str(temporary.with_suffix('')), 'zip', root_dir=OUTPUT.parent, base_dir=OUTPUT.name)
        temporary.replace(ROOT / 'dist/Joljak-win-x64.zip')
    finally:
        # This builder owns this temporary archive. Do not retain a failed
        # duplicate of the large portable runtime on the host's limited disks.
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Resume an incomplete bundle created by this build')
    parser.add_argument('--refresh-app', action='store_true', help='Refresh built UI/Electron/adapter files only; keep the existing Python/model runtime')
    parser.add_argument('--zip', action='store_true', help='Write the portable ZIP after assembly/refresh')
    args = parser.parse_args()
    package = json.loads((APP / 'package.json').read_text())
    electron = package['devDependencies']['electron']
    electron_zip = RUNTIME / f'electron-v{electron}-win32-x64.zip'
    python_zip = RUNTIME / f'python-{PYTHON_VERSION}-embed-amd64.zip'
    if not (APP / 'dist/index.html').is_file():
        raise SystemExit('Run npm run build in apps/daw first')
    if args.refresh_app:
        refresh_app(package)
        if args.zip:
            replace_archive()
        print(f'Application files refreshed: {OUTPUT}', flush=True)
        return
    if OUTPUT.exists() and not args.resume:
        raise SystemExit('Output already exists. Choose a new output directory before rebuilding; preserved bundles are not overwritten.')
    download(f'https://github.com/electron/electron/releases/download/v{electron}/{electron_zip.name}', electron_zip)
    download(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/{python_zip.name}', python_zip)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    print('Extract Windows Electron runtime', flush=True)
    with zipfile.ZipFile(electron_zip) as archive:
        archive.extractall(OUTPUT)
    (OUTPUT / 'electron.exe').replace(OUTPUT / 'Joljak.exe')
    resource = OUTPUT / 'resources'
    target = resource / 'app'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP / 'dist', target / 'dist', dirs_exist_ok=True)
    shutil.copytree(APP / 'electron', target / 'electron', dirs_exist_ok=True)
    shutil.copytree(APP / 'backend', target / 'backend', ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    (target / 'package.json').write_text(json.dumps({'name': 'joljak-daw', 'productName': 'Joljak', 'version': package['version'], 'main': 'electron/main.cjs'}, indent=2), encoding='utf-8')
    analysis = resource / 'analysis'
    (analysis / 'experiments').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'experiments/__init__.py', analysis / 'experiments/__init__.py')
    module = analysis / 'experiments/metronome_reconstruction_v1'
    module.mkdir(exist_ok=True)
    for name in ['__init__.py', 'grid.py', 'infer.py', 'hinted.py', 'config-tap-v2.json', 'design-tap-v2.json']:
        shutil.copyfile(ROOT / 'experiments/metronome_reconstruction_v1' / name, module / name)
    shutil.copyfile(ROOT / 'samples/.experiment-state/metronome-v1/final0.ckpt', analysis / 'final0.ckpt')
    python = resource / 'python'
    python.mkdir(exist_ok=True)
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(python)
    (python / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n', encoding='utf-8')
    site = python / 'Lib/site-packages'
    site.mkdir(parents=True, exist_ok=True)
    wheels = RUNTIME / 'windows-wheels'
    wheels.mkdir(exist_ok=True)
    pip = ROOT / '.venv-metronome-v1/bin/python'
    # pip cross-platform resolution evaluates some markers against the Linux
    # build host. Download the complete frozen list without dependency expansion
    # so CPU Windows packaging cannot pull Linux-only CUDA dependencies.
    common = [str(pip), '-m', 'pip', 'download', '--dest', str(wheels), '--platform', 'win_amd64', '--python-version', '312', '--implementation', 'cp', '--abi', 'cp312', '--only-binary=:all:', '--no-deps', '--cache-dir', str(RUNTIME / 'pip-cache')]
    print('Resolve recorded CPU PyTorch wheels for Windows', flush=True)
    subprocess.run(common + ['--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.6.0+cpu', 'torchaudio==2.6.0+cpu'], check=True)
    # Keep model-side dependency versions from the preserved first run. Plotting
    # and packaging tools are not required by this application adapter.
    lock = (ROOT / 'experiments/metronome_reconstruction_v1/requirements-cpu.lock').read_text()
    dependencies = [line.strip() for line in lock.splitlines() if '==' in line and line.split('==')[0] not in ('torch', 'torchaudio')]
    print('Resolve recorded analysis dependencies for Windows', flush=True)
    subprocess.run(common + dependencies, check=True)
    wanted = {line.split('==')[0].lower().replace('-', '_') for line in dependencies} | {'torch', 'torchaudio'}
    for wheel in sorted(wheels.glob('*.whl')):
        if wheel.name.split('-')[0].lower().replace('-', '_') not in wanted:
            continue
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
                with archive.open(info) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
    (OUTPUT / 'START HERE.txt').write_text('Joljak\n\nRun Joljak.exe on Windows. No Node.js, Python, WSL or network connection is needed after assembly.\n\nImport your own WAV, MP3 or FLAC files. Use 1/2/3 for object/range/split tools. Select a song event or a range inside it, then Analyze Audio. Tap input chooses only the initial beat unit. Apply a proposal to its analyzed scope; Restore Original Prediction restores saved analysis values; apply separately to change the grid.\n\nNo recordings or reviewed reference maps are included. Analysis supports constant tempo and 3/4 or 4/4.\n', encoding='utf-8')
    refresh_app(package)
    if args.zip:
        replace_archive()
    print(f'Windows portable app assembled: {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
