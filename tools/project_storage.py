"""Canonical data locations and path-only relocation of frozen research inputs.

This reads storage paths, never reference clocks or musical annotations. It does
not create filesystem aliases or change the frozen records it consumes.
"""
from functools import lru_cache
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SAMPLES = DATA / "samples"
RUNS = DATA / "research/runs"
MODELS = DATA / "models"
HISTORICAL_ROOT = "/home/yooch/code/joljak"


@lru_cache(maxsize=1)
def _relocations():
    path = DATA / "storage/20261008-consolidation/paths.json"
    if not path.is_file():
        return {}, ()
    record = json.loads(path.read_text(encoding="utf-8"))
    return record["files"], tuple(sorted(record["prefixes"].items(),
                                         key=lambda item: len(item[0]), reverse=True))


def _native(value):
    if value.startswith(HISTORICAL_ROOT + "/"):
        return ROOT / value[len(HISTORICAL_ROOT) + 1:]
    return Path(value)


def resolve_path(value):
    """Resolve a current path or a preserved historical storage identifier."""
    path = Path(value)
    if path.is_relative_to(DATA) and path.exists():
        return path
    text = str(path).replace("\\", "/")
    files, prefixes = _relocations()
    candidates = [text]
    if not path.is_absolute():
        candidates.extend((HISTORICAL_ROOT + "/" + text,
                           HISTORICAL_ROOT + "/samples/" + text))
    try:
        relative = path.relative_to(SAMPLES).as_posix()
        candidates.append(HISTORICAL_ROOT + "/samples/" + relative)
    except ValueError:
        pass
    try:
        relative = path.relative_to(RUNS).as_posix()
        candidates.append(HISTORICAL_ROOT + "/samples/experiments/" + relative)
    except ValueError:
        pass
    # New directory layout plus an old relative member in a frozen descriptor.
    for old, new in prefixes:
        try:
            relative = path.relative_to(_native(new)).as_posix()
        except ValueError:
            continue
        candidates.append(old + ("/" + relative if relative != "." else ""))
    if text.startswith("D:/NailTheMix/library/"):
        candidates.append("/mnt/d/NailTheMix/library/" + text[len("D:/NailTheMix/library/"):])
    for candidate in candidates:
        if candidate in files:
            return _native(files[candidate])
        for old, new in prefixes:
            if candidate == old or candidate.startswith(old + "/"):
                translated = _native(new + candidate[len(old):])
                if translated.exists():
                    return translated
    return path


def read_json(path):
    return json.loads(resolve_path(path).read_text(encoding="utf-8"))
