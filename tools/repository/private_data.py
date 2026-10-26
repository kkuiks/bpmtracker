#!/usr/bin/env python3
"""Prepare explicit non-audio checkpoints; never publish or alter source Git."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CLICK = "data/samples/records/runs/reference-audit/walker-he-will-hold-me-fast-intake-20260927-v1/producer-click.wav"
MEDIA = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg", ".m4a", ".mp4", ".webm", ".aac", ".opus", ".zip", ".7z", ".rar", ".bin", ".split", ".SDIR"}
TEXT = {".json", ".jsonl", ".md", ".txt", ".log", ".body", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".html", ".yaml", ".yml", ".ps1", ".cmd", ".lock", ".ini", ".rtf"}
CACHE_PARTS = {"node_modules", "site-packages", "python-deps", "pip-cache", "__pycache__", "__MACOSX", "Cache", "cache"}
SECRET_KEYS = {"access_token", "refresh_token", "id_token", "password", "api_key", "secret_access_key", "authorization", "cookie", "cookies", "storage_state"}
SIGNING_KEYS = {"signature", "token", "access_token", "key-pair-id", "policy", "x-amz-signature", "x-amz-credential", "x-amz-security-token", "x-goog-signature", "x-goog-credential"}
SECRET = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}")
ASSIGNED_SECRET = re.compile(rb'["\x27](access_token|refresh_token|id_token|password|api_key|secret_access_key|authorization|cookie|storage_state)["\x27]\s*:\s*["\x27]([^"\x27]+)["\x27]', re.I)
URL = re.compile(r"https?://[^\s\"'<>`]+")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def data_repository_name():
    remote = subprocess.check_output(
        ["git", "-C", str(DATA), "remote", "get-url", "origin"], text=True
    ).strip()
    remote_path = remote.split(":", 1)[1] if remote.startswith("git@") else urlsplit(remote).path
    parts = [part for part in remote_path.removesuffix(".git").split("/") if part]
    if len(parts) < 2:
        raise ValueError("The data checkout needs a repository remote")
    return "/".join(parts[-2:])


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def signed_url(match):
    value = match.group(0)
    try:
        parts = urlsplit(value)
        query = parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower() in SIGNING_KEYS for k, _ in query):
            return value
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                          urlencode([(k, "REDACTED" if k.lower() in SIGNING_KEYS else v) for k, v in query]), parts.fragment))
    except ValueError:
        return "REDACTED_INVALID_URL"


def redact(value):
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            credential = k.lower() in SECRET_KEYS and bool(v)
            if k.lower() == "authorization" and isinstance(v, str):
                # Experiment protocols record owner authorization as prose.
                credential = v.lower().startswith(("bearer ", "basic ", "token ", "digest "))
            if k.lower() == "storage_state" and isinstance(v, str) and v.endswith(".json"):
                credential = False  # A local path is provenance, not its contents.
            result[k] = "REDACTED" if credential else redact(v)
        return result
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return URL.sub(signed_url, value)
    return value


def prepare(args):
    audit = json.loads(Path(args.audit).read_text())
    checkpoint = DATA / "storage" / args.checkpoint
    if (checkpoint / "selection.json").exists():
        raise SystemExit("Selection already exists; choose a new checkpoint ID.")
    checkpoint.mkdir(parents=True, exist_ok=True)
    selected = {}
    excluded = []
    sanitized = []

    def accept(path, destination, category):
        if not path.is_file() or path.is_symlink():
            excluded.append({"path": str(path), "reason": "missing-or-symlink"})
            return
        relative = path.relative_to(ROOT).as_posix()
        if any(p in CACHE_PARTS for p in path.parts) or path.suffix.lower() in {".pyc", ".pid", ".ttf", ".peak", ".asd", ".reapeaks", ".wfm", ".smt", ".ico", ".nosync"} or path.name in {".DS_Store", "Desktop.ini", ".ntm-storage.lock", "remote-preview-server.log"}:
            excluded.append({"path": relative, "reason": "regenerable-cache-vendor-or-runtime"})
            return
        if path.suffix.lower() in {x.lower() for x in MEDIA} and relative != CLICK:
            # Existing source-index receipts are not recordings or downloads.
            if not (relative.startswith("data/storage/") and path.name in {"source-index-before.bin", "owner-index-before.bin", "git-status-before.bin"}):
                excluded.append({"path": relative, "reason": "source-audio-or-distribution-container"})
                return
        if path.suffix.lower() == ".npz":
            with zipfile.ZipFile(path) as z:
                suspicious = [n for n in z.namelist() if Path(n).stem.lower() in {"waveform", "waveforms", "samples", "raw_audio"}]
                # Reviewed audio.npy and pcm.npy in existing experiment tables
                # are score/feature matrices, not source waveforms.
            if suspicious:
                excluded.append({"path": relative, "reason": "possible-waveform-array", "members": suspicious})
                return
        if path.suffix.lower() in TEXT or path.name in {"AGENTS.md", ".gitignore"}:
            content = path.read_bytes()
            if path.suffix.lower() == ".json":
                # Signed URLs and credential fields occur in acquisition receipts.
                if b"http" in content or ASSIGNED_SECRET.search(content):
                    original = json.loads(content)
                    cleaned = redact(original)
                    if cleaned != original:
                        backup = DATA / "snapshots" / "sanitized-metadata" / args.checkpoint / destination
                        write_json(backup, {"backup_only": True, "original_path": relative,
                                            "original_preserved_locally": True, "sanitization": "credential fields and signed URL query values redacted", "content": cleaned})
                        sanitized.append({"original_path": relative, "backup_path": backup.relative_to(DATA).as_posix()})
                        excluded.append({"path": relative, "reason": "credential-bearing-original-preserved-locally"})
                        accept(backup, backup.relative_to(DATA).as_posix(), "sanitized-acquisition-evidence")
                        return
            actual = []
            for match in ASSIGNED_SECRET.finditer(content):
                key, value = match.group(1).lower(), match.group(2).lower()
                if value in {b"redacted", b"none", b"null", b"example", b"placeholder"}:
                    continue
                if key == b"authorization" and not value.startswith((b"bearer ", b"basic ", b"token ", b"digest ")):
                    continue
                if key == b"storage_state" and value.endswith(b".json"):
                    continue
                actual.append(match)
            if SECRET.search(content) or actual:
                excluded.append({"path": relative, "reason": "credential-pattern-needs-manual-review"})
                return
            decoded = content.decode("utf-8", errors="replace")
            if URL.sub(signed_url, decoded) != decoded:
                excluded.append({"path": relative, "reason": "signed-url-in-non-json-record"})
                return
        if destination in selected:
            return
        if not relative.startswith("data/"):
            target = DATA / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            path = target
        selected[destination] = {"path": destination, "bytes": path.stat().st_size, "category": category}

    for row in audit["candidate_private_data"]["rows"]:
        path = ROOT / row["path"]
        destination = row["path"][5:] if row["path"].startswith("data/") else "snapshots/daw-state/" + args.checkpoint + "/" + row["path"]
        accept(path, destination, row["category"])
    native = {".als", ".ptx", ".flp", ".rpp-bak", ".jams", ".rtf", ".py", ".js", ".cmd", ".log", ".musicapps-project-folder"}
    for row in audit["unclassified_sample_files"]:
        path = ROOT / row["path"]
        if path.suffix.lower() in native or path.name in {"ProjectData", "MetaData", "DisplayStateArchive", "LICENSE"}:
            accept(path, row["path"][5:], "native-project-or-support-evidence")
        else:
            excluded.append({"path": row["path"], "reason": "unclassified-cache-download-or-mac-metadata"})
    # Copy current source bytes, including ignored local agent instructions.
    source = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).decode().split("\0")
    source += ["AGENTS.md", ".gitignore"]
    for relative in sorted(set(source)):
        if not relative or relative.startswith(("data/", "_local/", ".git/", "node_modules/", ".venv/", "dist/")):
            continue
        path = ROOT / relative
        if path.is_file() and not path.is_symlink():
            accept(path, "snapshots/source-worktree/" + args.checkpoint + "/" + relative, "current-source-worktree")
    for row in audit.get("known_windows_records", []):
        path = Path(row["path"])
        if not path.is_file() or path.is_symlink():
            excluded.append({"path": row["path"], "reason": "windows-record-missing"})
            continue
        parts = path.parts
        workspace = len(parts) - 1 - parts[::-1].index("workspace")
        relative = Path(*parts[workspace + 1:])
        target = DATA / "snapshots/windows-workspace" / args.checkpoint / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        accept(target, target.relative_to(DATA).as_posix(), "windows-project-and-analysis-state")
    # Repository-management files are restored from Git, not frozen archives.
    rows = sorted(selected.values(), key=lambda r: r["path"])
    selection = {"schema_version": 1, "checkpoint_id": args.checkpoint,
                 "archive_paths_relative_to": f"{ROOT.name}/data", "files": len(rows),
                 "bytes": sum(r["bytes"] for r in rows), "rows": rows,
                 "sanitized": sanitized, "excluded": excluded,
                 "source_recordings_and_credentials_excluded": True,
                 "original_reference_and_run_files_rewritten": False}
    write_json(checkpoint / "selection.json", selection)
    write_json(checkpoint / "coverage.json", {k: v for k, v in selection.items() if k != "rows"})
    print(json.dumps({"selected_files": len(rows), "selected_bytes": selection["bytes"], "sanitized": len(sanitized), "excluded_candidates": len(excluded)}, indent=2), flush=True)


class HashReader:
    def __init__(self, file):
        self.file = file
        self.digest = hashlib.sha256()

    def read(self, size):
        value = self.file.read(size)
        self.digest.update(value)
        return value


def package(args):
    checkpoint = DATA / "storage" / args.checkpoint
    selection = json.loads((checkpoint / "selection.json").read_text())
    out = checkpoint / "archives"
    out.mkdir(exist_ok=True)
    if list(out.iterdir()):
        raise SystemExit("Archive directory must be empty; existing checkpoints are immutable.")
    groups, group, total = [], [], 0
    for row in selection["rows"]:
        if group and total + row["bytes"] > 512 * 1024 * 1024:
            groups.append(group)
            group, total = [], 0
        group.append(row)
        total += row["bytes"]
    if group:
        groups.append(group)
    members, assets = [], []
    for number, group in enumerate(groups, 1):
        name = f"{args.checkpoint}-part-{number:03d}.tar.gz"
        archive = out / name
        with archive.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", compresslevel=1, fileobj=raw, mtime=0) as gz, tarfile.open(mode="w|", fileobj=gz, format=tarfile.PAX_FORMAT) as tar:
            for row in group:
                path = DATA / row["path"]
                before = path.stat()
                info = tarfile.TarInfo(row["path"])
                info.size, info.mode, info.mtime = before.st_size, before.st_mode & 0o777, int(before.st_mtime)
                with path.open("rb") as f:
                    reader = HashReader(f)
                    tar.addfile(info, reader)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or before.st_size != row["bytes"]:
                    raise SystemExit(f"Input changed during checkpoint: {row['path']}")
                members.append({**row, "sha256": reader.digest.hexdigest(), "archive": name})
        assets.append({"name": name, "bytes": archive.stat().st_size, "sha256": sha(archive), "files": len(group)})
        print(json.dumps({"part": number, "of": len(groups), **assets[-1]}), flush=True)
    manifest = {"schema_version": 1, "checkpoint_id": args.checkpoint, "repository": data_repository_name(), "files": len(members), "bytes": selection["bytes"],
                "archives": assets, "rows": members, "sanitized": selection["sanitized"], "excluded": selection["excluded"],
                "original_audio_included": False, "click_only_exception": CLICK[5:], "source_index_unchanged_required": True}
    write_json(out / "manifest.json", manifest)
    summary = {k: v for k, v in manifest.items() if k not in {"rows", "excluded", "sanitized"}}
    summary["manifest"] = {"name": "manifest.json", "bytes": (out / "manifest.json").stat().st_size, "sha256": sha(out / "manifest.json")}
    summary["compressed_bytes"] = sum(r["bytes"] for r in assets)
    summary["sanitized_records"] = len(selection["sanitized"])
    summary["release_tag"] = "checkpoint-20261013-v1" if args.checkpoint == "20261013-private-data-publication-v1" else "checkpoint-" + args.checkpoint
    write_json(checkpoint / "checkpoint.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "archives"}, indent=2), flush=True)


def git_paths(args):
    checkpoint = DATA / "storage" / args.checkpoint
    rows = json.loads((checkpoint / "selection.json").read_text())["rows"]
    chosen = ["README.md", ".gitignore", "backup_tools/README.md", "backup_tools/restore.py", f"storage/{args.checkpoint}/checkpoint.json", f"storage/{args.checkpoint}/coverage.json", f"storage/{args.checkpoint}/publication.json"]
    sample_text = {".json", ".jsonl", ".beats", ".yaml", ".csv", ".txt", ".md", ".bpmtracker", ".plist", ".jams"}
    report_names = {"manifest.json", "protocol.json", "report.json", "summary.json", "config.json", "catalog.json"}
    for row in rows:
        relative = row["path"]
        path = Path(relative)
        if row["bytes"] > 2 * 1024 * 1024:
            continue
        if ((relative.startswith("samples/") and path.suffix.lower() in sample_text)
                or (relative.startswith("research/") and (path.suffix.lower() in {".md", ".bpmtracker"} or path.name in report_names))
                or relative.startswith("snapshots/sanitized-metadata/")):
            chosen.append(relative)
    chosen = sorted(set(chosen))
    # Allow only reviewed exact files. Directories remain traversable.
    def escape(value):
        return value.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?").replace("[", "\\[")
    (DATA / ".gitignore").write_text("# Non-audio metadata allowlist; regenerate only during an approved checkpoint.\n*\n!*/\n" + "\n".join("!/" + escape(p) for p in chosen) + "\n")
    (checkpoint / "git-paths.bin").write_bytes(b"\0".join(p.encode() for p in chosen) + b"\0")
    write_json(checkpoint / "git-scope.json", {"files": len(chosen), "bytes": sum((DATA / p).stat().st_size for p in chosen if (DATA / p).is_file())})
    print((checkpoint / "git-scope.json").read_text(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "package", "git-paths"))
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--audit")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.checkpoint):
        parser.error("Checkpoint ID must be one safe path component")
    if args.command == "prepare" and not args.audit:
        parser.error("prepare requires an explicitly requested audit inventory")
    {"prepare": prepare, "package": package, "git-paths": git_paths}[args.command](args)


if __name__ == "__main__":
    main()
