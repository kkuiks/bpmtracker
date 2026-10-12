from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/research/runs/multiple_rhythm_continuity_v1/20261011T102117Z-v1'
FIXED_COMPARISON = ROOT / 'data/research/analyses/fixed_vs_variable/20261011-fixed13-v1'
POLICIES = ['none', 'proxy97', 'proxy100', 'proxy103']
METHODS = ['R0_RAW_CONTINUE', 'R1_FOLD_CONTINUE']


def read(path): return json.loads(Path(path).read_text())


def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def stamp(): return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def code_hashes():
    files = [ROOT / p for p in read(SOURCE / 'freeze.json')['code_hashes']]
    files += list(Path(__file__).parent.glob('*.py'))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(files))}


def guard(run):
    if read(Path(run) / 'freeze.json')['code_hashes'] != code_hashes():
        raise RuntimeError('Frozen implementation changed')
