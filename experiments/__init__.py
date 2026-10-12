"""Stable experiment imports, including byte-preserved reference packages.

Current code remains in this directory. Completed reference-only studies live
in ../reference at the same depth, so their workspace-root calculations and
historical Python import names stay valid. Frozen protocol hashes still belong
to their original snapshots; this bridge does not rewrite or relax them.
"""
from pathlib import Path

_reference = Path(__file__).resolve().parent.parent / "reference"
if _reference.is_dir():
    __path__.append(str(_reference))
