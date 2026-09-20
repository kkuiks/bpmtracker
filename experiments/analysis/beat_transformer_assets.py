"""Explicit, hash-checked provisioning for the Beat Transformer experiment.

Run with --fetch to download public official assets into ignored data storage.
An optional --frontend-python restores only madmom's pinned submodule package
initializer/license, which GitHub source archives omit. No madmom neural model
weights are used by this experiment's DBN decoder.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request


COMMIT = "063667fc9e4e11507f9d76dc1154d9db953a85eb"
BASE = f"https://raw.githubusercontent.com/zhaojw1998/Beat-Transformer/{COMMIT}/"
SOURCES = {
    "LICENSE": "00d28f59df6ede4917be18e57a60cef4ad97a844401037b01961f94cace98cfe",
    "README.md": "89810bc0f39befbcc340006a3c57dff38b7b1d548538f3a55f6788de21628608",
    "code/DilatedTransformer.py": "e7c07d70d92af962de39434491a220b2950c2767058672c846421237e2c72bf4",
    "code/DilatedTransformerLayer.py": "91583f48839d02e42e31934278ddb20ff2fb985749790d84eff00e4e90e38d83",
    "code/eight_fold_test.py": "b42449ad90883dbf36fd8ef2b58eff9c02edd2b6ac8aa3352aa68f4cecb368ec",
    "preprocessing/demixing.py": "8b0ae415c5d87a8108e290e8adbe99b1fabc3e372dd6b12d7866ef199eae8a16",
    "code/spectrogram_dataset.py": "f2f6034006278a14e26134bb8e0b4a540113d35dc7599804d94781a1d664cccc",
}
CHECKPOINT_SHA256 = "b76033014dd07d12307743b92337b7dffadf1f20a6ccd5a1edb03276e99a4512"
SPLEETER_SHA256 = "25a1e87eb5f75cc72a4d2d5467a0a50ac75f05611f877c278793742513cc7218"
SPLEETER_FILES = {
    "checkpoint": "011c96b970c1f56137037924fe1a0f0851369b0ee6692e120aea798615326f48",
    "model.meta": "00fc7ce46920ba5622e9f3d281e5670c711ff1a72003199e1928a19774a1efec",
    "model.index": "b20377789eb084cb5ac78d141a1d480dfdbf8c796ecc554a9b8e4376cd3cee20",
    "model.data-00000-of-00001": "aace47a9eacc62e6fda823cee92ba45375b48e65b7c69713b91a7fa9d87ae920",
}
DEMO_URL = "https://drive.google.com/uc?export=download&id=1IdrpMO1AivWmy-Bm8ktmMy14ED9jllux"
DEMO_SHA256 = "01175eb46b14c12488c17d79d6f6decfbbb1806ad5e14ebbaceaee4416e6a24b"
MADMOM_COMMIT = "3bc8334099feb310acfce884ebdb76a28e01670d"
MADMOM_MODELS_COMMIT = "7e3dc1b0cad499792767074d03c38b194b9b0a79"
MADMOM_METADATA = {
    "__init__.py": "89b71c041c78770a217abe0d9eaf83f428f44c95bb70e41a1907eff29785a7cb",
    "LICENSE": "4ab453b7c3b87cfb097e6a1535b0660f2b5adf775be15651b70e3aa1cf7b1757",
    "README.rst": "a031ee7cc7579ffd6c94475cd74b17c83e1e9a2349c05503ccdbd0b9c91e9538",
}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for value in iter(lambda: f.read(1024*1024), b""):
            h.update(value)
    return h.hexdigest()


def fetch(url, path, expected=None):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name+".download")
        if temporary.exists():
            raise ValueError(f"incomplete download already exists: {temporary}")
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("xb") as f:
            while value := response.read(1024*1024):
                f.write(value)
        if expected and sha(temporary) != expected:
            raise ValueError(f"download hash mismatch: {url}; temporary file retained for diagnosis")
        temporary.replace(path)
    actual = sha(path)
    if expected and actual != expected:
        raise ValueError(f"existing asset hash mismatch: {path}")
    return {"url": url, "sha256": actual, "bytes": path.stat().st_size}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fetch", action="store_true", required=True)
    p.add_argument("--root", type=Path, default=Path("data/models/beat-transformer"))
    p.add_argument("--frontend-python", type=Path)
    args = p.parse_args()
    root = args.root
    files = []
    for name, expected in SOURCES.items():
        record = fetch(BASE+name, root / "upstream" / name, expected)
        files.append({"path": name, **record})
    demo = fetch(DEMO_URL, root / "upstream/official_demo.ipynb", DEMO_SHA256)
    (root / "upstream/provenance.json").write_text(json.dumps({
        "repository": "https://github.com/zhaojw1998/Beat-Transformer", "commit": COMMIT,
        "files": files, "official_demo": demo,
    }, indent=2)+"\n")
    checkpoint = fetch(BASE+"checkpoint/fold_4_trf_param.pt", root / "fold_4_trf_param.pt", CHECKPOINT_SHA256)
    (root / "fold_4_trf_param.json").write_text(json.dumps({
        **checkpoint, "upstream_commit": COMMIT, "selection": "Official demo FOLD=4, fixed before local scoring",
        "license": "MIT repository LICENSE retained under upstream/",
    }, indent=2)+"\n")
    archive = root / "spleeter/5stems.tar.gz"
    record = fetch("https://github.com/deezer/spleeter/releases/download/v1.4.0/5stems.tar.gz", archive, SPLEETER_SHA256)
    target = root / "spleeter/5stems"
    if not target.exists():
        target.mkdir()
        with tarfile.open(archive) as tf:
            tf.extractall(target, filter="data")
        (target / ".probe").write_text("OK")
    if not (target / "checkpoint").is_file():
        raise ValueError("incomplete Spleeter extraction")
    for name, expected in SPLEETER_FILES.items():
        if sha(target / name) != expected:
            raise ValueError(f"extracted Spleeter weight mismatch: {name}")
    (root / "spleeter/provenance.json").write_text(json.dumps({
        **record, "files": {v.name: sha(v) for v in sorted(target.iterdir()) if v.is_file()},
    }, indent=2)+"\n")
    if args.frontend_python:
        location = subprocess.check_output([str(args.frontend_python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
        models = Path(location) / "madmom/models"
        records = []
        for name, expected in MADMOM_METADATA.items():
            record = fetch(f"https://raw.githubusercontent.com/CPJKU/madmom_models/{MADMOM_MODELS_COMMIT}/{name}", models / name, expected)
            records.append({"file": name, **record})
        (root / "madmom-model-metadata.json").write_text(json.dumps({
            "madmom_commit": MADMOM_COMMIT, "submodule_commit": MADMOM_MODELS_COMMIT, "files": records,
            "scope": "Official package initializer and license only; no madmom neural weights used",
        }, indent=2)+"\n")
    print(root)


if __name__ == "__main__":
    main()
