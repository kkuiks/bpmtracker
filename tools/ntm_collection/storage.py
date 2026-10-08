"""Bind collection batches to one permanent per-session media directory."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
import re


REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / 'data/samples'
CONFIG = SAMPLES / 'ntm-storage.json'
EXCLUSIONS = SAMPLES / 'excluded-candidates.json'


def words(value):
    return ' '.join(re.findall(r'[a-z0-9]+', str(value).casefold().replace('&', ' and ')))


def identity_text(value):
    return words(value).replace(' ', '')


def assert_candidate_allowed(song, activity='collection'):
    """Honor durable exclusions even when all per-song files have been deleted."""
    if not EXCLUSIONS.is_file():
        raise RuntimeError('source_exclusion_registry_required')
    rows = json.loads(EXCLUSIONS.read_text())['candidates']
    for row in rows:
        permanent = row.get('permanent_exclusion') is True
        disabled = row.get(activity + '_enabled') is False
        if not permanent and not disabled:
            continue
        slug_matches = bool(song.get('slug')) and song['slug'] in (row.get('id'), row.get('slug'))
        id_matches = row.get('session_id') is not None and str(song.get('session_id')) == str(row['session_id'])
        exact_title = bool(song.get('title')) and identity_text(song['title']) == identity_text(row.get('title', ''))
        artist, name = words(row.get('artist', '')), words(row.get('song', ''))
        identity_matches = bool(artist and name) and (
            (identity_text(song.get('artist', '')) == identity_text(artist) and identity_text(song.get('song', '')) == identity_text(name)) or
            (' ' + artist + ' ' in ' ' + words(song.get('title', '')) + ' ' and
             ' ' + name + ' ' in ' ' + words(song.get('title', '')) + ' '))
        if slug_matches or id_matches or exact_title or identity_matches:
            raise RuntimeError('permanently_excluded_source' if permanent else 'owner_excluded_source')


@contextmanager
def storage_lock():
    with (SAMPLES / '.ntm-storage.lock').open('a') as stream:
        if os.name != 'nt':
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        else:
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write('0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def save(path, value):
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def library_root():
    if not CONFIG.exists():
        raise RuntimeError('ntm_storage_configuration_required')
    settings = json.loads(CONFIG.read_text())
    root = Path(str(SAMPLES / settings['library_root_relative']))
    if not root.is_dir():
        raise RuntimeError('sample_library_unavailable')
    return root


def bind_song(batch, song):
    """Bind identity to its canonical directory without allocating batch links."""
    assert_candidate_allowed(song)
    slug = song['slug']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug):
        raise RuntimeError('invalid_collection_slug')
    root = library_root()
    target = root / slug / 'collection'
    recording = root / slug / 'recording.json'
    record = json.loads(recording.read_text()) if recording.exists() else {}
    if record.get('status') == 'owner_excluded':
        raise RuntimeError('owner_excluded_source')
    if record.get('session_id') not in (None, song['session_id']):
        raise RuntimeError('collection_session_identity_mismatch')
    if recording.exists() and not target.exists():
        raise RuntimeError('existing_recording_material_requires_explicit_reuse')
    if target.exists() and any(target.iterdir()) and not recording.exists():
        raise RuntimeError('unregistered_existing_material_requires_explicit_reuse')
    target.mkdir(parents=True, exist_ok=True)
    Path(batch).mkdir(parents=True, exist_ok=True)
    update_record(song, batch)
    return target


def bind_selected(batch, songs):
    for song in songs:
        with storage_lock():
            bind_song(batch, song)


def update_record(song, batch, status=None):
    """Maintain storage discovery without enrolling or certifying a sample."""
    assert_candidate_allowed(song)
    root = library_root(); slug = song['slug']; path = root / slug / 'recording.json'
    value = json.loads(path.read_text()) if path.exists() else {
        'schema_version': 1, 'slug': slug, 'session_id': song['session_id'], 'title': song['title'],
        'status': 'selected_for_collection', 'enrolled_ids': [], 'batch_records': [],
        'collection_home': 'collection', 'sample_catalog_remains_membership_authority': True,
        'historical_python_and_predictions_are_not_active_research': True}
    if value.get('session_id') is None:
        value['session_id'] = song['session_id']
    batch_record = str(Path(batch).absolute().relative_to(SAMPLES))
    value['batch_records'] = list(dict.fromkeys([*value.get('batch_records', []), batch_record]))
    value.pop('batch_views', None)
    if status and value['status'] not in ('owner_accepted', 'owner_excluded'):
        value['status'] = status
    value['storage_record_updated_at_utc'] = datetime.now(timezone.utc).isoformat()
    save(path, value)
    index_path = SAMPLES / 'ntm-library-index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {
        'schema_version': 1, 'library_root_windows': str(root),
        'recordings': [], 'sample_catalog_remains_membership_authority': True}
    rows = {row['slug']: row for row in index['recordings']}; rows[slug] = value
    index['recordings'] = list(rows.values())
    index['physical_recording_count'] = sum(row.get('source_material_deleted') is not True for row in index['recordings'])
    index['list_only_permanent_exclusions'] = sum(row.get('permanent_exclusion') is True and row.get('source_material_deleted') is True
                                                for row in index['recordings'])
    save(index_path, index)


def note_stage(song, batch, status):
    with storage_lock():
        update_record(song, batch, status)
