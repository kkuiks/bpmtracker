"""Download BabySlakh v2 and extract the small set of benchmark inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
import urllib.request

URL = "https://zenodo.org/records/4603870/files/babyslakh_16k.tar.gz?download=1"
MD5 = "311096dc2bde7d61c97e930edbfc7f78"
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_EXTRACTED_BYTES = 4_000_000_000


def download(destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if not destination.exists():
        start = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(URL, headers={"User-Agent": "Joljak-Benchmark/1.0"})
        if start:
            request.add_header("Range", f"bytes={start}-")
        with urllib.request.urlopen(request, timeout=45) as response:
            if start and response.status != 206:
                start = 0
            if start and not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                raise ValueError("Unexpected resume range")
            remaining = response.headers.get("Content-Length")
            if remaining and start + int(remaining) > MAX_ARCHIVE_BYTES:
                raise ValueError("Archive exceeds the initial download budget")
            last_print = time.monotonic()
            total = start
            with partial.open("ab" if start else "wb") as stream:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("Archive exceeds the initial download budget")
                    stream.write(block)
                    if time.monotonic() - last_print >= 10:
                        print(f"Downloaded {total / 1_000_000:.1f} MB", flush=True)
                        last_print = time.monotonic()
        with partial.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if digest != MD5:
            raise ValueError(f"Archive fingerprint differs from the published v2 file: {digest}")
        partial.replace(destination)
    else:
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if digest != MD5:
            raise ValueError("Existing archive is not the published BabySlakh v2 file")
    return {"url": URL, "record": "https://zenodo.org/records/4603870",
            "archive": str(destination), "bytes": destination.stat().st_size,
            "md5": digest, "published_md5": MD5, "dataset_version": "v2"}


def extract(archive: Path, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    extracted, skipped, total = [], 0, 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Archive contains an unsafe path")
            track_positions = [i for i, part in enumerate(path.parts)
                               if part.startswith("Track") and len(part) == 10 and part[5:].isdigit()]
            if not track_positions or not member.isfile():
                skipped += 1
                continue
            position = track_positions[-1]
            relative = PurePosixPath(*path.parts[position:])
            number = int(relative.parts[0][5:])
            if not 1 <= number <= 20:
                raise ValueError("BabySlakh v2 contains an unexpected track identity")
            keep = (len(relative.parts) == 2 and relative.name in {"mix.wav", "all_src.mid", "metadata.yaml"}
                    or len(relative.parts) == 3 and relative.parts[1] == "MIDI" and relative.suffix == ".mid"
                    or len(relative.parts) == 3 and relative.parts[1] == "stems" and relative.suffix == ".wav")
            if not keep:
                skipped += 1
                continue
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("Selected inputs exceed the initial extraction budget")
            destination = root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.stat().st_size != member.size:
                    raise ValueError(f"Existing extracted input has a different size: {relative}")
                source_stream = source.extractfile(member)
                if source_stream is None:
                    raise ValueError(f"Unreadable archive member: {relative}")
                with source_stream, destination.open("rb") as existing:
                    while block := source_stream.read(1024 * 1024):
                        if existing.read(len(block)) != block:
                            raise ValueError(f"Existing input differs from the published archive: {relative}")
            else:
                stream = source.extractfile(member)
                if stream is None:
                    raise ValueError(f"Unreadable archive member: {relative}")
                temporary = destination.with_name(destination.name + ".partial")
                with stream, temporary.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                temporary.replace(destination)
            extracted.append({"path": str(relative), "bytes": member.size})
    return {"root": str(root), "selected_bytes": total, "files": extracted,
            "skipped_members": skipped, "selection": "mixture and stem WAVs, original and stem MIDIs, metadata"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    archive = args.root / "babyslakh_16k.tar.gz"
    transfer = download(archive)
    print(f"Published archive acquired: {transfer['bytes'] / 1_000_000:.1f} MB", flush=True)
    inputs = extract(archive, args.root / "inputs")
    receipt = {"acquired_at_utc": datetime.now(timezone.utc).isoformat(),
               "transfer": transfer, "extraction": inputs}
    (args.root / "acquisition.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(inputs['files'])} inputs ({inputs['selected_bytes'] / 1_000_000:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
