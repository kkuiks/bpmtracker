from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE = Path(__file__).resolve().parent
HELD = "PINNED_INITIAL_HELD_METER_L2"
CONSTANT = "PINNED_INITIAL_CONSTANT_MAP"
HISTORICAL = "HISTORICAL_L2_UNMODIFIED"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if replace else "x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def guard(run, *, evaluation=False):
    """A new guard; never relax or replace a historical freeze."""
    freeze = read(Path(run) / ("evaluation-freeze.json" if evaluation
                               else "inference-freeze.json"))
    changed = [path for path, sha in freeze["files"].items()
               if not Path(path).is_file() or digest(path) != sha]
    if changed:
        raise RuntimeError("Research freeze changed: " + ", ".join(changed))
    return freeze
