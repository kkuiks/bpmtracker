"""Register aligned references for a fixed two-recording batch."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import math
import shutil

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / 'samples'
BATCH = SAMPLES / 'ntm-intake/20261005-linear3-v1'
VALUES = {'kyle-black-state-champs': '-2.034500',
          'andrew-wade-a-day-to-remember': '-7.053750'}
STATEMENT = '처음 두개는 바로 확정해도 좋을 정도네. 근데 마지막 거 아주 이상하네, 111개의 템포 이벤트??'


def save(path, value):
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def asset(path, recorded_hash=None):
    if recorded_hash is None:
        with path.open('rb') as stream:
            recorded_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(path.relative_to(SAMPLES)), bytes=path.stat().st_size,
                sha256=recorded_hash)


def finalize(slug, decimal, timestamp):
    job = BATCH / slug
    review = json.loads((job / 'review-data.json').read_text())
    if review.get('human_alignment_accepted'):
        return json.loads((job / 'acceptance.json').read_text())
    clock = json.loads((job / 'raw-clock.json').read_text())
    geometry = json.loads((job / 'master-geometry.json').read_text())
    offset = float(decimal)
    support = [[max(0., review['source_range_start_seconds'] + offset),
                min(review['duration_seconds'], review['project_end_seconds'] + offset)]]
    decision = dict(owner_statement=STATEMENT, decision_date_local='2026-10-05',
                    recorded_at_utc=timestamp, scope='first two songs at the currently proposed offsets',
                    offset_decimal_seconds=decimal, offset_seconds=offset,
                    transform='t_master = t_project + offset_seconds',
                    human_alignment_accepted=True, independent_millisecond_accuracy_certified=False)
    save(job / 'owner-decision.json', decision)
    aligned = {}
    for input_name, output_name in [('tempo_events', 'tempo_events'), ('meter_events', 'meter_events'),
                                    ('quarters', 'quarter_events'), ('bars', 'bar_events')]:
        aligned[output_name] = []
        for event in review[input_name]:
            row = dict(event, master_seconds=event['project_seconds'] + offset)
            if input_name == 'quarters':
                row['master_frame'] = math.floor(row['master_seconds'] * review['sample_rate'] + .5)
            aligned[output_name].append(row)
    accepted = dict(kind='owner_accepted_supplied_source_clock', source_master=geometry,
                    source_clock=copy.deepcopy(clock), raw_clock_sha256=review['clock_sha256'],
                    offset_seconds=offset, offset_decimal_seconds=decimal,
                    transform=decision['transform'], time_scale=1., human_alignment_accepted=True,
                    audio_relative_fields=['master_seconds'], project_seconds_are_unshifted_source_context=True,
                    additional_offset_to_apply_when_consuming_master_fields_seconds=0,
                    **aligned, support_seconds=support, outside_support='unknown_not_a_no_grid_reference',
                    owner_approved_audio_span_seconds=[0., review['duration_seconds']], source_extent_preserved=True,
                    independent_millisecond_accuracy_certified=False,
                    acceptance_record=str((job / 'acceptance.json').relative_to(SAMPLES)))
    save(job / 'tempo-owner-accepted-v1.json', accepted)
    rate, frames = review['sample_rate'], review['sample_frames']
    t = np.arange(math.floor(rate * .025 + .5)) / rate
    normal = (.18 * np.exp(-220 * t) * np.cos(2 * np.pi * 1500 * t)).astype('float32')
    accent = (.30 * np.exp(-220 * t) * np.cos(2 * np.pi * 2200 * t)).astype('float32')
    click = np.zeros(frames, dtype='float32')
    for event in aligned['quarter_events']:
        start = event['master_frame']
        if not 0 <= start < frames:
            continue
        tone = accent if event['bar_start'] else normal
        length = min(len(tone), frames - start)
        click[start:start + length] += tone[:length]
    pcm = np.clip(np.floor(click.astype('float64') * 32768 + .5), -32768, 32767).astype('int16')
    sf.write(job / 'click-approved.wav', pcm, rate, subtype='PCM_16')
    music, _ = sf.read(job / 'master.wav', dtype='float32', always_2d=True)
    sf.write(job / 'listen-approved.wav', music * .4 + click[:, None] * .65, rate, subtype='FLOAT')
    originals = [dict(asset(BATCH / r['path']), archive_member=r['archive_member']) for r in review['clock_files']]
    record = dict(**decision, title=review['title'], slug=slug, status='owner_accepted_alignment',
                  master=asset(job / 'master.wav', review['audio_sha256']),
                  raw_clock=asset(job / 'raw-clock.json', review['clock_sha256']),
                  accepted_reference=asset(job / 'tempo-owner-accepted-v1.json'),
                  source_reference_files=originals, supplied_map_support_seconds=support,
                  outside_support='unknown_not_no_grid', original_audio_geometry_unchanged=True,
                  artifacts={name: asset(job / name) for name in ('click-approved.wav', 'listen-approved.wav')},
                  source_integrity_rechecked_at_finalization=False, tests_or_verification_run=False,
                  source_cleanup_performed=False)
    save(job / 'acceptance.json', record)
    review.update(initial_offset_seconds=offset, accepted_offset_seconds=offset, human_alignment_accepted=True,
                  acceptance_revision='owner-20261005-first2-v1',
                  acceptance_record=str((job / 'acceptance.json').relative_to(BATCH)),
                  accepted_map=str((job / 'tempo-owner-accepted-v1.json').relative_to(BATCH)),
                  approved_click=str((job / 'click-approved.wav').relative_to(BATCH)),
                  approved_audition=str((job / 'listen-approved.wav').relative_to(BATCH)),
                  description='사용자가 현재 시작값으로 오프셋을 확정했습니다. 원본 제작 지도와 음원은 그대로 보존했습니다.')
    save(job / 'review-data.json', review)
    status = json.loads((job / 'preparation-status.json').read_text())
    status.update(status='owner_accepted_alignment', offset_seconds=offset,
                  owner_acceptance_pending=False, tests_or_verification_run=False)
    save(job / 'preparation-status.json', status)
    print(json.dumps(dict(owner_accepted=slug, offset_seconds=offset), ensure_ascii=False), flush=True)
    return record


def main():
    timestamp = datetime.now(timezone.utc).isoformat()
    evidence = BATCH / 'evidence/pre-owner-acceptance-first2'
    if not evidence.exists():
        evidence.mkdir(parents=True)
        for name in ('catalog.json', 'assets.json'):
            shutil.copy2(SAMPLES / name, evidence / ('samples-' + name))
        for slug in VALUES:
            (evidence / slug).mkdir()
            for name in ('review-data.json', 'preparation-status.json'):
                shutil.copy2(BATCH / slug / name, evidence / slug / name)
    records = [finalize(slug, decimal, timestamp) for slug, decimal in VALUES.items()]
    catalog_path = SAMPLES / 'catalog.json'
    catalog = json.loads(catalog_path.read_text())
    for record in records:
        if any(row['id'] == record['slug'] for row in catalog['tracks']):
            continue
        review = json.loads((BATCH / record['slug'] / 'review-data.json').read_text())
        catalog['tracks'].append(dict(id=record['slug'], title=record['title'], role='finished_recording_development',
            audio=record['master'], reference=record['accepted_reference'], sample_rate=review['sample_rate'],
            sample_frames=review['sample_frames'], duration_seconds=review['duration_seconds'],
            reference_support_seconds=record['supplied_map_support_seconds'],
            qualification=dict(reference_tier='owner_reviewed_supplied_source_map', full_song_alignment_accepted=True,
                scope_note='Reviewed alignment offset; supplied map extent and unknown margins are preserved',
                independent_millisecond_timing_certified=False), known_development_material=True,
            exposure_note='Source collection and alignment listening; no model prediction or evaluation',
            independent_original_click_millisecond_accuracy_certified=False,
            accepted_reference_is_already_audio_relative=True, additional_reference_offset_seconds=0,
            original_clocks=[{k: r[k] for k in ('path', 'bytes', 'sha256')} for r in record['source_reference_files']],
            owner_review_records=[asset(BATCH / record['slug'] / 'acceptance.json')],
            original_clock_to_audio_offset_metadata=dict(total_seconds=record['offset_seconds'],
                already_applied_in_accepted_tempo_map=True, additional_offset_to_apply_when_consuming_accepted_map_seconds=0)))
    counts = Counter(row['role'] for row in catalog['tracks'])
    catalog.update(finished_recordings=counts['finished_recording_development'],
                   formal_sample_role_counts={k: v for k, v in counts.items() if k.startswith('formal_') or k == 'finished_recording_development'},
                   formal_samples=sum(v for k, v in counts.items() if k.startswith('formal_') or k == 'finished_recording_development'),
                   count_note='Formal samples include 25 complete recordings, ten original-recording excerpts and one approved synthetic recording.',
                   latest_owner_enrollment=dict(decision_date_local='2026-10-05', registered_samples=2,
                       approved_ids=list(VALUES), receipt='ntm-intake/20261005-linear3-v1/accepted-catalog.json'))
    save(catalog_path, catalog)
    inventory_path = SAMPLES / 'assets.json'
    inventory = json.loads(inventory_path.read_text())
    registered = {r['path'] for r in inventory['assets']}
    for record in records:
        job = BATCH / record['slug']
        files = [(job / 'master.wav', record['master']['sha256']),
                 (job / 'raw-clock.json', record['raw_clock']['sha256'])]
        files += [(job / name, None) for name in ('master-original.mp3', 'tempo-owner-accepted-v1.json',
                  'owner-decision.json', 'acceptance.json', 'click-approved.wav', 'listen-approved.wav')]
        files += [(SAMPLES / r['path'], r['sha256']) for r in record['source_reference_files']]
        for path, recorded_hash in files:
            row = asset(path, recorded_hash)
            if row['path'] in registered:
                continue
            inventory['assets'].append(dict(**row, category='retained_ntm_source_or_owner_approved_sample_asset',
                private_distribution=True, retained=True, registered_owner_approved=True,
                source_batch='ntm-intake/20261005-linear3-v1', checksum_recorded_for_inventory=True,
                source_integrity_rechecked_at_enrollment=False))
            registered.add(row['path'])
    retained = {r['path']: r for r in inventory['assets'] if r.get('copied') or r.get('retained')}
    inventory.update(unique_copied_files=len(retained), unique_copied_bytes=sum(r['bytes'] for r in retained.values()))
    save(inventory_path, inventory)
    selection = json.loads((BATCH / 'selection.json').read_text())
    excluded = [s for s in selection['songs'] if s.get('disposition') == 'owner_excluded']
    pending = [s for s in selection['songs'] if s['slug'] not in VALUES and s not in excluded]
    summary_status = 'two_owner_accepted_one_owner_excluded' if excluded else 'first_two_owner_accepted_last_pending'
    save(BATCH / 'accepted-catalog.json', dict(status=summary_status,
         owner_statement=STATEMENT, songs=[dict(title=r['title'], slug=r['slug'], audio=r['master'],
         reference=r['accepted_reference'], acceptance=asset(BATCH / r['slug'] / 'acceptance.json')) for r in records],
         pending_songs=[s['slug'] for s in pending],
         excluded_songs=[dict(title=s['title'], slug=s['slug'], exclusion_record=s['exclusion_record']) for s in excluded],
         owner_acceptance_pending=bool(pending), tests_or_verification_run=False, source_cleanup_performed=False))
    batch = json.loads((BATCH / 'batch.json').read_text())
    batch.update(status=summary_status, owner_accepted_sources=2, pending_sources=len(pending), excluded_sources=len(excluded),
                 owner_acceptance_pending=bool(pending),
                 tests_or_verification_run=False, source_cleanup_performed=False)
    save(BATCH / 'batch.json', batch)
    print(json.dumps(dict(formal_samples=catalog['formal_samples'], finished_recordings=catalog['finished_recordings'],
                         added_tests=False, cleanup_performed=False)), flush=True)


if __name__ == '__main__':
    main()
