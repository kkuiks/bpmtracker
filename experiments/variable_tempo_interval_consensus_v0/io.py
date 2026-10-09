"""Small explicit I/O helpers; prediction never imports reference loaders."""
from pathlib import Path
import hashlib
import json
import numpy as np


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.partial')
    part.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    part.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_array(path):
    allowed = {'beat_logits', 'downbeat_logits', 'fps', 'duration_seconds', 'silent_frame_mask'}
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key].copy() for key in allowed if key in data}


def validate_source(row):
    allowed = {'id', 'evidence_path', 'duration_seconds', 'fps', 'audio_path', 'original_family_path',
               'original_trace_path', 'original_events_path', 'phasor_cache_path', 'original_prediction_path'}
    if set(row) - allowed or not {'id', 'evidence_path', 'duration_seconds', 'fps'} <= set(row):
        raise ValueError('Non-source fields or missing source geometry')
