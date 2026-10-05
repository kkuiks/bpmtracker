"""Download fixed public research assets with size/checksum provenance.

Media and third-party annotations belong under ignored data/, not source Git.
Archives are downloaded only; this utility does not execute or extract content.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request


ASSETS = {
    "babyslakh": ("https://zenodo.org/records/4603870/files/babyslakh_16k.tar.gz?download=1", 882818115, "311096dc2bde7d61c97e930edbfc7f78", "CC-BY-4.0"),
    "gtzan-features": ("https://zenodo.org/records/13922116/files/gtzan.zip?download=1", 306944985, "39a7dfe6a6b0a5279a94d770506db879", "CC-BY-4.0; published spectrograms, not original audio"),
    "beat-annotations-v1.1": ("https://codeload.github.com/CPJKU/beat_this_annotations/zip/890407d158078527ab396b49fea3c8a83e5734ee", None, None, "MIT repository; retain per-dataset attribution"),
}


def fetch(name, directory):
    url, expected_size, expected_md5, license_note = ASSETS[name]
    directory.mkdir(parents=True, exist_ok=True)
    filename = name + (".tar.gz" if name == "babyslakh" else ".zip")
    target = directory / filename
    partial = target.with_name(target.name + ".partial")
    if target.exists() or partial.exists():
        raise ValueError("destination must be new; preserve and inspect any partial download")
    md5, sha256 = hashlib.md5(), hashlib.sha256()
    count, last_report = 0, 0
    request = urllib.request.Request(url, headers={"User-Agent": "Joljak research corpus downloader"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as output:
        resolved_url = response.url
        while chunk := response.read(1024*1024):
            output.write(chunk)
            md5.update(chunk)
            sha256.update(chunk)
            count += len(chunk)
            if count-last_report >= 100*1024*1024:
                print(f"{name}: {count/1024**2:.0f} MiB", flush=True)
                last_report = count
    if expected_size is not None and count != expected_size:
        raise ValueError(f"download size mismatch: {count} != {expected_size}")
    if expected_md5 is not None and md5.hexdigest() != expected_md5:
        raise ValueError("download differs from publisher checksum")
    partial.rename(target)
    report = {"asset": name, "url": url, "resolved_url": resolved_url, "bytes": count,
              "md5": md5.hexdigest(), "sha256": sha256.hexdigest(), "publisher_md5": expected_md5,
              "license_note": license_note, "retrieved_at_utc": datetime.now(timezone.utc).isoformat()}
    target.with_name(target.name+".json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", choices=ASSETS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    fetch(args.asset, args.output_dir)


if __name__ == "__main__":
    main()
