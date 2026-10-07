"""Acquire the published GTZAN spectrograms and their matching v1.0 labels."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import time
import urllib.request
import zipfile

from .inference import write_json


RECORD = "https://zenodo.org/records/13922116"
FILES = {
    "gtzan.zip": "39a7dfe6a6b0a5279a94d770506db879",
    "beat_this_annotations.zip": "a11e22e5f9aec7b14d8dd92b6251117c",
}


def download(destination, expected_md5, maximum_bytes):
    url = f"{RECORD}/files/{destination.name}?download=1"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        partial = destination.with_name(destination.name + ".partial")
        start = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={"User-Agent": "Joljak-Benchmark/1.0"})
        if start:
            request.add_header("Range", f"bytes={start}-")
        with urllib.request.urlopen(request, timeout=45) as response:
            if start and response.status != 206:
                start = 0
            if start and not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                raise ValueError("Unexpected transfer resume range")
            length = response.headers.get("Content-Length")
            if length and start + int(length) > maximum_bytes:
                raise ValueError("Published file exceeds the acquisition limit")
            total, last_print = start, time.monotonic()
            with partial.open("ab" if start else "wb") as stream:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > maximum_bytes:
                        raise ValueError("Download exceeds the acquisition limit")
                    stream.write(block)
                    if time.monotonic() - last_print >= 10:
                        print(f"{destination.name}: {total / 1_000_000:.1f} MB", flush=True)
                        last_print = time.monotonic()
        with partial.open("rb") as stream:
            actual_md5 = hashlib.file_digest(stream, "md5").hexdigest()
        if actual_md5 != expected_md5:
            raise ValueError("Downloaded file differs from the published fingerprint")
        partial.replace(destination)
    with destination.open("rb") as stream:
        actual_md5 = hashlib.file_digest(stream, "md5").hexdigest()
    if destination.stat().st_size > maximum_bytes or actual_md5 != expected_md5:
        raise ValueError("Local archive differs from the published file")
    return {"url": url, "bytes": destination.stat().st_size, "md5": actual_md5,
            "published_md5": expected_md5}


def extract_inputs(root):
    selected, total = [], 0
    for name in FILES:
        with zipfile.ZipFile(root / name) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
                    raise ValueError("Unsafe archive path")
                if entry.is_dir():
                    continue
                if name == "gtzan.zip":
                    relative = Path("gtzan.npz") if path.name == "gtzan.npz" else None
                elif "gtzan" in path.parts:
                    index = path.parts.index("gtzan")
                    remainder = PurePosixPath(*path.parts[index:])
                    relative = Path(*remainder.parts) if (remainder.name == "info.json"
                        or remainder.suffix == ".beats") else None
                else:
                    relative = None
                if relative is None:
                    continue
                total += entry.file_size
                if total > 500_000_000:
                    raise ValueError("Selected data exceeds the extraction limit")
                destination = root / "inputs" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source:
                    if destination.exists():
                        if destination.stat().st_size != entry.file_size:
                            raise ValueError(f"Existing input size differs: {relative}")
                        with destination.open("rb") as existing:
                            while block := source.read(1024 * 1024):
                                if existing.read(len(block)) != block:
                                    raise ValueError(f"Existing input differs: {relative}")
                    else:
                        temporary = destination.with_name(destination.name + ".partial")
                        with temporary.open("wb") as stream:
                            shutil.copyfileobj(source, stream)
                        temporary.replace(destination)
                selected.append({"path": str(relative), "bytes": entry.file_size})
    if not (root / "inputs/gtzan.npz").is_file():
        raise ValueError("Published spectrogram bundle is missing")
    return {"files": selected, "selected_bytes": total}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    transfers = {name: download(args.root / name, digest,
                               350_000_000 if name == "gtzan.zip" else 15_000_000)
                 for name, digest in FILES.items()}
    extraction = extract_inputs(args.root)
    write_json(args.root / "acquisition.json", {
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(), "record": RECORD,
        "annotation_version": "v1.0", "transfers": transfers, "extraction": extraction,
        "source_audio_acquired": False, "precomputed_features_only": True})
    print(f"Prepared {len(extraction['files'])} files; {extraction['selected_bytes'] / 1_000_000:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
