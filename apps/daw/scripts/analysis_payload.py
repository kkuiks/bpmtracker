"""Synchronize managed analysis source without changing Python, models or media."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path("algorithms/fixed/payload.json")


def sync_analysis(destination: Path, source_root: Path = ROOT) -> dict:
    source_root = source_root.resolve()
    destination = destination.resolve()
    if destination == source_root or source_root.is_relative_to(destination):
        raise ValueError("Choose a dedicated analysis payload directory")
    if destination.name != "analysis" or destination.parent.name != "resources" or not (destination / "final0.ckpt").is_file():
        raise ValueError("Choose an app bundle's resources/analysis directory with its existing checkpoint")
    specification = json.loads((source_root / MANIFEST).read_text(encoding="utf-8"))
    if specification.get("schemaVersion") != 1:
        raise ValueError("Unsupported analysis payload version")
    rows = []
    contents = {}
    for name in specification["files"]:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "algorithms":
            raise ValueError("Invalid managed analysis path")
        source = source_root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing product analysis source: {relative}")
        content = source.read_bytes()
        contents[relative.as_posix()] = content
        rows.append({"path": relative.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    destination.mkdir(parents=True, exist_ok=True)
    managed = destination / "algorithms"
    if managed.is_symlink():
        raise ValueError("The managed analysis package must not be a link")
    if managed.is_dir():
        shutil.rmtree(managed)
    for row in rows:
        target = destination / row["path"]
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p != destination.parent):
            raise ValueError("Managed analysis paths must not follow links")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[row["path"]])
    revision = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    result = {"schemaVersion": 1, "revision": revision, "files": rows}
    (destination / "analysis-payload.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    result = sync_analysis(args.target)
    print(json.dumps({"analysisRevision": result["revision"], "files": len(result["files"])}))


if __name__ == "__main__":
    main()
