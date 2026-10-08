"""Enroll an explicitly owner-approved supplied clock from a selected batch.

An exact owner statement and chosen offset are required. Existing raw sources
stay untouched; accepted audio-relative fields apply the offset exactly once.
This performs registration/rendering, not integrity audits or model inference.
"""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import Counter
import argparse
import copy
import hashlib
import json
import math
import shutil

import numpy as np
import soundfile as sf

if __package__:
    from .storage import SAMPLES, assert_candidate_allowed, bind_selected, library_root, save, storage_lock, update_record
else:
    from storage import SAMPLES, assert_candidate_allowed, bind_selected, library_root, save, storage_lock, update_record


def finalize(batch, slug, decimal_offset, statement):
    selection = json.loads((batch / 'selection.json').read_text())
    song = next(row for row in selection['songs'] if row['slug'] == slug)
    assert_candidate_allowed(song, 'review')
    bind_selected(batch, [song])
    job = library_root() / slug / 'collection'
    review = json.loads((job / 'review-data.json').read_text())
    offset = float(decimal_offset)
    if not math.isfinite(offset): raise RuntimeError('invalid_owner_offset')
    if review.get('human_alignment_accepted'):
        if abs(review['accepted_offset_seconds'] - offset) > 1e-10:
            raise RuntimeError('accepted_reference_revision_requires_version_preservation')
        return dict(status='existing_owner_acceptance_reused', slug=slug)
    if not statement.strip(): raise RuntimeError('owner_statement_required')
    clock = json.loads((job / 'raw-clock.json').read_text())
    geometry = json.loads((job / 'master-geometry.json').read_text())
    if not clock['meter_events']: raise RuntimeError('supplied_meter_required_for_finalization')
    evidence = batch / 'evidence' / ('pre-owner-acceptance-' + slug)
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ('review-data.json', 'preparation-status.json'):
        if not (evidence / name).exists(): shutil.copy2(job / name, evidence / name)
    for name in ('catalog.json', 'assets.json'):
        if not (evidence / ('samples-' + name)).exists(): shutil.copy2(SAMPLES / name, evidence / ('samples-' + name))
    timestamp = datetime.now(timezone.utc).isoformat()
    date = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    support = [[max(0., review['source_range_start_seconds'] + offset),
                min(review['duration_seconds'], review['project_end_seconds'] + offset)]]
    decision = dict(authority='explicit_owner_listening_statement', owner_statement=statement,
        decision_date_local=date, recorded_at_utc=timestamp, slug=slug, title=song['title'],
        scope='The owner approved this recording at its current proposed offset; whole-recording convention with supplied-clock coverage preserved.',
        offset_decimal_seconds=decimal_offset, offset_seconds=offset,
        transform='t_master = t_project + offset_seconds', human_alignment_accepted=True,
        formal_sample_enrollment_authorized=True, independent_millisecond_accuracy_certified=False,
        reviewed_regions_not_individually_reported=True)
    save(job / 'owner-decision.json', decision)
    aligned = {}
    for before, after in (('tempo_events','tempo_events'),('meter_events','meter_events'),('quarters','quarter_events'),('bars','bar_events')):
        aligned[after] = []
        for event in review[before]:
            row = dict(event, master_seconds=event['project_seconds'] + offset)
            if before == 'quarters': row['master_frame'] = math.floor(row['master_seconds'] * review['sample_rate'] + .5)
            aligned[after].append(row)
    def asset(path, known_hash=None):
        path = Path(path)
        if known_hash is None:
            with path.open('rb') as stream: known_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        return dict(path=str(Path('ntm') / slug / 'collection' / path.relative_to(job)),
                    bytes=path.stat().st_size, sha256=known_hash)
    accepted = dict(kind='owner_accepted_supplied_source_clock', source_master=geometry,
        source_clock=copy.deepcopy(clock), raw_clock_sha256=review['clock_sha256'],
        offset_seconds=offset, offset_decimal_seconds=decimal_offset, transform=decision['transform'], time_scale=1.,
        human_alignment_accepted=True, audio_relative_fields=['master_seconds'],
        project_seconds_are_unshifted_source_context=True,
        additional_offset_to_apply_when_consuming_master_fields_seconds=0,
        **aligned, support_seconds=support, outside_support='unknown_not_a_no_grid_reference',
        owner_approved_audio_span_seconds=[0.,review['duration_seconds']], source_extent_preserved=True,
        independent_millisecond_accuracy_certified=False,
        acceptance_record=str(Path('ntm') / slug / 'collection/acceptance.json'))
    save(job / 'tempo-owner-accepted-v1.json', accepted)
    rate, frames = review['sample_rate'], review['sample_frames']
    t = np.arange(math.floor(rate * .025 + .5)) / rate
    normal = (.18 * np.exp(-220*t) * np.cos(2*np.pi*1500*t)).astype('float32')
    accent = (.30 * np.exp(-220*t) * np.cos(2*np.pi*2200*t)).astype('float32')
    click = np.zeros(frames, dtype='float32')
    for event in aligned['quarter_events']:
        start = event['master_frame']
        if not 0 <= start < frames: continue
        tone = accent if event['bar_start'] else normal; length = min(len(tone),frames-start)
        click[start:start+length] += tone[:length]
    pcm = np.clip(np.floor(click.astype('float64') * 32768 + .5),-32768,32767).astype('int16')
    sf.write(job / 'click-approved.wav',pcm,rate,subtype='PCM_16')
    music, _ = sf.read(job / 'master.wav',dtype='float32',always_2d=True)
    sf.write(job / 'listen-approved.wav',music*.4+click[:,None]*.65,rate,subtype='FLOAT')
    original_files = [dict(asset(SAMPLES / row['path']),archive_member=row['archive_member'])
                      for row in review['clock_files']]
    record = dict(**decision,status='owner_accepted_alignment',master=asset(job/'master.wav',review['audio_sha256']),
        raw_clock=asset(job/'raw-clock.json',review['clock_sha256']), accepted_reference=asset(job/'tempo-owner-accepted-v1.json'),
        source_reference_files=original_files,supplied_map_support_seconds=support,outside_support='unknown_not_no_grid',
        original_audio_geometry_unchanged=True,
        artifacts={name:asset(job/name) for name in ('click-approved.wav','listen-approved.wav')},
        source_integrity_rechecked_at_finalization=False,tests_or_verification_run=False,source_cleanup_performed=False)
    save(job/'acceptance.json',record)
    catalog = json.loads((SAMPLES/'catalog.json').read_text())
    if any(row['id']==slug for row in catalog['tracks']): raise RuntimeError('sample_already_enrolled_without_matching_acceptance')
    catalog['tracks'].append(dict(id=slug,title=song['title'],role='finished_recording_development',
        audio=record['master'],reference=record['accepted_reference'],sample_rate=rate,sample_frames=frames,
        duration_seconds=review['duration_seconds'],reference_support_seconds=support,
        qualification=dict(reference_tier='owner_reviewed_supplied_source_map',full_song_alignment_accepted=True,
            scope_note='Owner-approved current offset; supplied clock coverage is preserved.',independent_millisecond_timing_certified=False),
        known_development_material=True,exposure_note='Source acquisition and owner listening; no model run or new benchmark enrollment.',
        independent_original_click_millisecond_accuracy_certified=False,accepted_reference_is_already_audio_relative=True,
        additional_reference_offset_seconds=0,original_clocks=[{k:r[k] for k in ('path','bytes','sha256')} for r in original_files],
        owner_review_records=[asset(job/'acceptance.json')],original_clock_to_audio_offset_metadata=dict(total_seconds=offset,
            already_applied_in_accepted_tempo_map=True,additional_offset_to_apply_when_consuming_accepted_map_seconds=0)))
    counts = Counter(row['role'] for row in catalog['tracks'])
    formal = {k:v for k,v in counts.items() if k.startswith('formal_') or k=='finished_recording_development'}
    catalog.update(finished_recordings=counts['finished_recording_development'],formal_sample_role_counts=formal,
        formal_samples=sum(formal.values()),count_note=f"Current formal cohort: {counts['finished_recording_development']} complete recordings, {counts['formal_original_recording_excerpt']} original excerpts and {counts['formal_synthetic_recording']} approved synthetic recording.",
        latest_owner_enrollment=dict(decision_date_local=date,registered_samples=1,approved_ids=[slug],
                                    receipt=str((batch/'accepted-catalog.json').relative_to(SAMPLES))))
    save(SAMPLES/'catalog.json',catalog)
    inventory = json.loads((SAMPLES/'assets.json').read_text());known = {row['path'] for row in inventory['assets']}
    files = [(job/'master.wav',review['audio_sha256']),(job/'raw-clock.json',review['clock_sha256'])]
    files += [(job/name,None) for name in ('master-original.mp3','tempo-owner-accepted-v1.json','owner-decision.json','acceptance.json','click-approved.wav','listen-approved.wav')]
    files += [(job/Path(row['path']).relative_to(slug),None) for row in review['clock_files']]
    for path, sha in files:
        value = asset(path,sha)
        if value['path'] in known: continue
        inventory['assets'].append(dict(**value,category='retained_ntm_source_or_owner_approved_sample_asset',
            private_distribution=True,retained=True,registered_owner_approved=True,source_batch=str(batch.relative_to(SAMPLES)),
            checksum_recorded_for_inventory=True,source_integrity_rechecked_at_enrollment=False))
        known.add(value['path'])
    retained = {row['path']:row for row in inventory['assets'] if row.get('copied') or row.get('retained')}
    inventory.update(unique_copied_files=len(retained),unique_copied_bytes=sum(row['bytes'] for row in retained.values()))
    save(SAMPLES/'assets.json',inventory)
    review.update(initial_offset_seconds=offset,accepted_offset_seconds=offset,human_alignment_accepted=True,
        acceptance_revision='owner-'+date+'-'+slug,acceptance_record=slug+'/acceptance.json',
        accepted_map=slug+'/tempo-owner-accepted-v1.json',approved_click=slug+'/click-approved.wav',
        approved_audition=slug+'/listen-approved.wav',description='사용자가 현재 제안값으로 전곡 오프셋을 확정했습니다. 제공 시계와 원본 음원은 보존했습니다.')
    save(job/'review-data.json',review)
    status = json.loads((job/'preparation-status.json').read_text());status.update(status='owner_accepted_alignment',
        offset_seconds=offset,owner_acceptance_pending=False);save(job/'preparation-status.json',status)
    for row in selection['songs']:
        if row['slug']==slug: row.update(offset_accepted=True,formal_sample_enrolled=True,disposition='owner_accepted')
    selection.update(status='partially_owner_accepted',existing_sample_catalog_changed=True)
    save(batch/'selection.json',selection)
    accepted_rows=[];pending=[]
    for row in selection['songs']:
        receipt = library_root()/row['slug']/'collection/acceptance.json'
        if receipt.exists():
            item=json.loads(receipt.read_text());accepted_rows.append(dict(title=row['title'],slug=row['slug'],
                audio=item['master'],reference=item['accepted_reference'],acceptance=asset(receipt) if row['slug']==slug else
                dict(path=str(Path('ntm')/row['slug']/'collection/acceptance.json'))))
        else: pending.append(row['slug'])
    save(batch/'accepted-catalog.json',dict(status='partially_owner_accepted',songs=accepted_rows,pending_songs=pending,
        owner_acceptance_pending=bool(pending),source_cleanup_performed=False,tests_or_verification_run=False))
    index=json.loads((batch/'index-data.json').read_text());index['owner_acceptance_pending']=bool(pending);save(batch/'index-data.json',index)
    summary=json.loads((batch/'batch.json').read_text());summary.update(status='partially_owner_accepted',
        owner_accepted_sources=len(accepted_rows),pending_sources=len(pending),owner_acceptance_pending=bool(pending))
    save(batch/'batch.json',summary)
    with storage_lock():
        meta_path=library_root()/slug/'recording.json';meta=json.loads(meta_path.read_text())
        meta.update(status='owner_accepted',enrolled_ids=list(dict.fromkeys([*meta.get('enrolled_ids',[]),slug])))
        save(meta_path,meta);update_record(song,batch,'owner_accepted')
    return dict(owner_accepted=slug,offset_seconds=offset,formal_samples=catalog['formal_samples'],
                finished_recordings=catalog['finished_recordings'],catalog_entries=len(catalog['tracks']),
                pending_sources=len(pending),cleanup_performed=False,model_runs_performed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--slug',required=True);parser.add_argument('--offset-seconds',required=True)
    parser.add_argument('--owner-statement-file',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(finalize(args.batch.absolute(),args.slug,args.offset_seconds,args.owner_statement_file.read_text()),ensure_ascii=False))
