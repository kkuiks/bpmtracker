"""Finalize only the three explicitly owner-approved offsets and owned cleanup."""
from datetime import datetime,timezone
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path,PurePosixPath
import shutil
import stat
import wave
import zipfile
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[2]
BATCH=ROOT/'samples/ntm-intake/20261002-new3-v1'
VALUES={
    'doug-weier-real-friends-waiting-room':('-15.220',-15220.0),
    'taylor-larson-holding-absence-afterlife':('-16.209',-16209.0),
    'jeff-braun-bilmuri-hard2tell':('-2.72425',-2724.25),
}
STATEMENT='세곡 모두 너가 제시한 값 오프셋으로 확정. 정리 부탁해'


def now():return datetime.now(timezone.utc).isoformat()


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(path)


def info(path):return dict(path=str(path.resolve()),bytes=path.stat().st_size,sha256=digest(path))


def asset(path):
    values=info(path);values['path']=str(path.relative_to(ROOT/'samples'));return values


def assert_regular(path):
    assert path.resolve()==path.absolute() and stat.S_ISREG(path.lstat().st_mode),str(path)


def snapshot():
    destination=BATCH/'evidence/pre-owner-approval'
    if destination.exists():return
    for path in ['batch.json','README.md','completion-validation.json']:
        target=destination/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(BATCH/path,target)
    for slug in VALUES:
        for name in ['review-data.json','report.json']:
            target=destination/slug/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(BATCH/slug/name,target)
    for name in ['catalog.json','assets.json']:
        shutil.copy2(ROOT/'samples'/name,destination/('samples-'+name))


def prepare():
    assert not (BATCH/'cleanup.json').exists(),'Cleanup already recorded; inspect rather than rerun'
    selection=json.loads((BATCH/'selection.json').read_text())['songs']
    assert {r['slug'] for r in selection}==set(VALUES)
    snapshot();targets=[];preserved=[];approved=[]
    for song in selection:
        slug=song['slug'];job=BATCH/slug;decimal,ms=VALUES[slug];offset=float(decimal)
        data=json.loads((job/'review-data.json').read_text());geometry=json.loads((job/'master-geometry.json').read_text())
        assert abs(data['initial_offset_seconds']-offset)<1e-10
        archive=json.loads((job/'archive-inventory.json').read_text());source=json.loads((job/'clock-source-audit.json').read_text())
        assert_regular(job/'source.zip');assert digest(job/'source.zip')==archive['archive_sha256']
        assert archive['all_member_crc_passed'];assert digest(job/'master.wav')==geometry['sha256']
        assert digest(job/'raw-clock.json')==data['clock_sha256']
        for item in source['reference_assets']:
            path=BATCH/item['path'];assert_regular(path);assert digest(path)==item['sha256']
        # Preserve native Logic project data before removing the complete ZIP.
        logic=[]
        with zipfile.ZipFile(job/'source.zip') as z:
            for member in z.infolist():
                parts=PurePosixPath(member.filename).parts
                if member.is_dir() or '__MACOSX' in parts:continue
                positions=[i for i,part in enumerate(parts) if part.lower().endswith('.logicx')]
                if not positions:continue
                relative=PurePosixPath(*parts[positions[0]:])
                assert not relative.is_absolute() and '..' not in relative.parts
                assert relative.suffix.lower() not in {'.wav','.aif','.aiff','.mp3','.flac','.m4a'},'Unexpected unique Logic audio requires review'
                target=job/'references/logic'/str(relative);payload=z.read(member)
                if target.exists():assert target.read_bytes()==payload
                else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
                logic.append(dict(member=member.filename,**asset(target),crc32=f'{member.CRC:08x}',decoded=False))
        save(job/'native-logic-project-preservation.json',dict(files=logic,media_not_self_contained_after_cleanup=True))
        raw=json.loads((job/'raw-clock.json').read_text())
        support=[max(0.,offset),min(data['duration_seconds'],data['project_end_seconds']+offset)]
        assert 0<=support[0]<support[1]<=data['duration_seconds']
        decision=dict(authority='owner_chat_instruction',owner_statement=STATEMENT,decision_date_local='2026-10-02',
            timezone='Asia/Seoul',recorded_at_utc=now(),title=song['title'],slug=slug,offset_seconds=offset,
            offset_decimal_seconds=decimal,offset_milliseconds=ms,transform='t_master = t_project + offset_seconds',
            time_scale=1.,scope='Whole supplied map against the full Master under the standing unspecified-range convention',
            no_individual_listening_windows_invented=True,independent_millisecond_accuracy_certified=False)
        save(job/'owner-decision.json',decision)
        def shifted(event):return dict(event,master_seconds=event['project_seconds']+offset)
        quarters=[dict(shifted(e),master_frame=math.floor((e['project_seconds']+offset)*data['sample_rate']+.5)) for e in data['quarters']]
        bars=[shifted(e) for e in data['bars']]
        accepted=dict(kind='owner_accepted_supplied_source_clock',source_master=geometry,source_clock=raw,
            raw_clock_sha256=data['clock_sha256'],offset_seconds=offset,offset_decimal_seconds=decimal,
            transform='t_master = t_project + offset_seconds',time_scale=1.,human_alignment_accepted=True,
            audio_relative_fields=['master_seconds','master_frame'],project_seconds_are_unshifted_source_context=True,
            additional_offset_to_apply_when_consuming_master_fields_seconds=0,
            tempo_events=[shifted(e) for e in data['tempo_events']],meter_events=[shifted(e) for e in data['meter_events']],
            quarter_events=quarters,bar_events=bars,support_seconds=[support],outside_support='unknown_not_a_no_grid_reference',
            owner_approved_audio_span_seconds=[0.,data['duration_seconds']],
            source_extent_preserved=True,independent_millisecond_accuracy_certified=False,
            acceptance_record=str((job/'acceptance.json').relative_to(ROOT/'samples')))
        save(job/'tempo-owner-accepted-v1.json',accepted)
        frames=data['sample_frames'];rate=data['sample_rate'];count=math.floor(rate*.025+.5);time=np.arange(count)/rate
        normal=(.18*np.exp(-220*time)*np.cos(2*np.pi*1500*time)).astype(np.float32)
        accent=(.30*np.exp(-220*time)*np.cos(2*np.pi*2200*time)).astype(np.float32)
        clicks=np.zeros(frames,dtype=np.float32);positions=[]
        for event in quarters:
            begin=event['master_frame']
            if not 0<=begin<frames:continue
            tone=accent if event['bar_start'] else normal;n=min(count,frames-begin);clicks[begin:begin+n]+=tone[:n];positions.append(begin)
        pcm=np.clip(np.floor(clicks.astype(np.float64)*32768+.5),-32768,32767).astype('<i2')
        old_click=BATCH/'validation'/f'{slug}-click.wav';before,old_rate=sf.read(old_click,dtype='int16')
        assert old_rate==rate and np.array_equal(before,pcm),'Selected decimal offset changes the previously auditioned native clicks'
        click=job/'click-approved.wav'
        with wave.open(str(click),'wb') as writer:
            writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(rate);writer.writeframes(pcm.tobytes())
        actual,actual_rate=sf.read(click,dtype='int16');assert actual_rate==rate and np.array_equal(actual,pcm)
        music,music_rate=sf.read(job/'master.wav',dtype='float32',always_2d=True)
        assert music_rate==rate and music.shape==(frames,data['channels'])
        audition=(music*.4+clicks[:,None]*.65).astype(np.float32)
        sf.write(job/'listen-approved.wav',audition,rate,subtype='FLOAT')
        delivered,delivered_rate=sf.read(job/'listen-approved.wav',dtype='float32',always_2d=True)
        assert delivered_rate==rate and np.array_equal(audition,delivered)
        reference=asset(job/'tempo-owner-accepted-v1.json')
        record=dict(**decision,status='owner_accepted_alignment',human_alignment_accepted=True,
            master=asset(job/'master.wav'),raw_clock=asset(job/'raw-clock.json'),accepted_reference=reference,
            source_reference_files=[dict(asset(BATCH/r['path']),member=r['member'],crc32=r['crc32']) for r in source['reference_assets']],native_logic_files=logic,
            supplied_map_support_seconds=[support],outside_support='unknown_not_no_grid',
            original_audio_geometry_unchanged=True,artifacts={name:asset(job/name) for name in ['click-approved.wav','listen-approved.wav']})
        save(job/'acceptance.json',record)
        data.update(initial_offset_seconds=offset,accepted_offset_seconds=offset,human_alignment_accepted=True,
            acceptance_revision='owner-20261002-v1',acceptance_record=str((job/'acceptance.json').relative_to(BATCH)),
            accepted_map=str((job/'tempo-owner-accepted-v1.json').relative_to(BATCH)),
            approved_click=str(click.relative_to(BATCH)),approved_audition=str((job/'listen-approved.wav').relative_to(BATCH)),
            description='사용자가 제시된 오프셋을 확정했습니다. 다른 위치로 조절하면 미승인 비교값으로 표시됩니다.'+
                (' MIDI와 Studio One의 3/4를 유지하며, 다른 REAPER 헤더 표기는 출처 기록에 보존했습니다.' if not source['reaper_initial_meter_agreement'] else ''))
        save(job/'review-data.json',data)
        job_targets=[(job/'source.zip',archive['archive_sha256'],'owned_full_archive',None)]
        alignment=json.loads((job/'alignment-audit.json').read_text())
        for row in alignment['sources']:
            job_targets.append((BATCH/row['source']['path'],row['source']['sha256'],'owned_extracted_alignment_source',None))
        for suffix in ['click.wav','offset.json']:
            path=BATCH/'validation'/f'{slug}-{suffix}'
            if suffix=='offset.json':
                value=json.loads(path.read_text());assert value['notes']=='browser validation scratch; not owner approval' and value['human_alignment_accepted'] is False
            job_targets.append((path,digest(path),'owned_browser_validation_copy',str(click) if suffix=='click.wav' else None))
        transport=Path('/tmp/joljak-ntm-new3-20261002/private')/(slug+'-archive-transport.json')
        if transport.exists():
            assert json.loads(transport.read_text())['session_id']==song['session_id']
            job_targets.append((transport,digest(transport),'expired_job_owned_signed_link_transport',None))
        for path,sha,category,replacement in job_targets:
            assert_regular(path);assert digest(path)==sha
            if category!='expired_job_owned_signed_link_transport':assert BATCH in path.absolute().parents
            targets.append(dict(**info(path),category=category,slug=slug,replaced_by=replacement))
        for path in job.rglob('*'):
            if path.is_file() and str(path.resolve()) not in {r['path'] for r in targets}:
                assert not path.is_symlink();preserved.append(info(path))
        approved.append(dict(song=song,acceptance=record,review=data,reference=reference,
            native_click_frames_equal_to_previous_browser_export=True,in_source_quarter_count=len(positions)))
        print(json.dumps(dict(finalized=slug,offset_seconds=offset,support_seconds=support,click_frames=frames)),flush=True)
    # Preserve the old 20+1 catalog and add only these three approved data assets.
    cat_path=ROOT/'samples/catalog.json';catalog=json.loads(cat_path.read_text())
    for row in approved:
        song=row['song'];d=row['review'];a=row['acceptance']
        assert not any(t['id']==song['slug'] for t in catalog['tracks'])
        catalog['tracks'].append(dict(id=song['slug'],title=song['title'],role='finished_recording_development',
            audio=a['master'],reference=row['reference'],sample_rate=d['sample_rate'],sample_frames=d['sample_frames'],
            duration_seconds=d['duration_seconds'],reference_support_seconds=a['supplied_map_support_seconds'],
            qualification=dict(reference_tier='owner_reviewed_supplied_source_map',full_song_alignment_accepted=True,
                scope_note='Owner-approved full Master alignment; supplied-map support and unknown margins remain explicit',
                independent_millisecond_timing_certified=False),known_development_material=True,
            exposure_note='Known for acquisition and reference preparation; no analyzer prediction, model fitting or new evaluation policy',
            independent_original_click_millisecond_accuracy_certified=False,accepted_reference_is_already_audio_relative=True,
            additional_reference_offset_seconds=0,original_clocks=[{k:r[k] for k in ['path','bytes','sha256']} for r in a['source_reference_files']+a['native_logic_files']],
            owner_review_records=[asset(BATCH/song['slug']/'acceptance.json')],
            original_clock_to_audio_offset_metadata=dict(total_seconds=a['offset_seconds'],already_applied_in_accepted_tempo_map=True,
                additional_offset_to_apply_when_consuming_accepted_map_seconds=0)))
    catalog['finished_recordings']=23;catalog['auxiliary_clips']=1;save(cat_path,catalog)
    assets_path=ROOT/'samples/assets.json';inventory=json.loads(assets_path.read_text())
    registered={r['path'] for r in inventory['assets']}
    for row in approved:
        job=BATCH/row['song']['slug'];files=[job/'master.wav',job/'master-original.mp3',job/'raw-clock.json',job/'tempo-owner-accepted-v1.json',job/'acceptance.json',job/'owner-decision.json',job/'click-approved.wav',job/'listen-approved.wav']
        files += [ROOT/'samples'/r['path'] for r in row['acceptance']['source_reference_files']]
        files += [ROOT/'samples'/r['path'] for r in row['acceptance']['native_logic_files']]
        for path in files:
            record=asset(path)
            if record['path'] in registered:continue
            category='owner_reviewed_reference' if path.name=='tempo-owner-accepted-v1.json' else 'owner_review_receipt' if path.name in {'acceptance.json','owner-decision.json'} else 'retained_ntm_source_or_review_asset'
            inventory['assets'].append(dict(record,original_path=str(path),category=category,private_distribution=True,
                copied=True,copy_sha256_verified=True,source_batch='ntm-intake/20261002-new3-v1'))
            registered.add(record['path'])
    unique={r['path']:r for r in inventory['assets'] if r.get('copied')}
    inventory['unique_copied_files']=len(unique);inventory['unique_copied_bytes']=sum(r['bytes'] for r in unique.values());save(assets_path,inventory)
    save(BATCH/'accepted-catalog.json',dict(status='owner_accepted_alignment',songs=[dict(title=r['song']['title'],slug=r['song']['slug'],
        audio=r['acceptance']['master'],reference=r['reference'],acceptance=asset(BATCH/r['song']['slug']/'acceptance.json')) for r in approved]))
    save(BATCH/'finalization-validation.json',dict(complete=True,owner_statement=STATEMENT,songs=[dict(slug=r['song']['slug'],
        accepted_offset_seconds=r['acceptance']['offset_seconds'],source_map_support_seconds=r['acceptance']['supplied_map_support_seconds'],
        click_export_native_samples_unchanged=True,master_and_raw_clock_unchanged=True) for r in approved],
        active_finished_recordings=23,active_auxiliary_clips=1,older_catalog_snapshot_preserved=True,
        no_new_evaluation_policy_or_model=True))
    save(BATCH/'cleanup-plan.json',dict(owner_authorization=STATEMENT,prepared_at_utc=now(),targets=targets,
        mutable_status_files=[str((BATCH/slug/'report.json').resolve()) for slug in VALUES],
        target_bytes=sum(r['bytes'] for r in targets),preserved_files=preserved,finalization_verified=True))
    print(json.dumps(dict(cleanup_targets=len(targets),verified_target_bytes=sum(r['bytes'] for r in targets),
        retained_files_verified=len(preserved),approved_finished_samples=23)),flush=True)


def cleanup():
    plan=json.loads((BATCH/'cleanup-plan.json').read_text());validation=json.loads((BATCH/'finalization-validation.json').read_text())
    assert plan['owner_authorization']==STATEMENT and plan['finalization_verified'] and validation['complete']
    assert not (BATCH/'cleanup.json').exists(),'Cleanup receipt already exists'
    for row in plan['preserved_files']:
        p=Path(row['path']);assert_regular(p);assert p.stat().st_size==row['bytes'] and digest(p)==row['sha256']
    for row in plan['targets']:
        p=Path(row['path']);assert_regular(p);assert p.stat().st_size==row['bytes'] and digest(p)==row['sha256']
    deleted=[]
    for row in plan['targets']:
        p=Path(row['path']);p.unlink();deleted.append(row)
        save(BATCH/'cleanup-progress.json',dict(status='deleting_verified_owned_inputs',deleted=deleted))
    for slug in VALUES:
        work=BATCH/slug/'_work'
        if work.exists() and not any(work.iterdir()):work.rmdir()
        report=json.loads((BATCH/slug/'report.json').read_text())
        report.update(status='owner_accepted_alignment_and_cleaned',accepted_offset_seconds=float(VALUES[slug][0]),
            offset_requires_owner_listening=False,human_alignment_accepted=True,retained_archive_and_selected_stems=False,
            files_deleted=[r for r in deleted if r['slug']==slug]);save(BATCH/slug/'report.json',report)
    mutable=set(plan.get('mutable_status_files',[]))
    for row in plan['preserved_files']:
        if row['path'] in mutable:continue
        p=Path(row['path']);assert p.is_file() and p.stat().st_size==row['bytes'] and digest(p)==row['sha256']
    assert all(not Path(r['path']).exists() for r in deleted)
    receipt=dict(status='complete',owner_authorization=STATEMENT,completed_at_utc=now(),deleted=deleted,
        deleted_bytes=sum(r['bytes'] for r in deleted),preserved_files_verified=len(plan['preserved_files']),
        prior_samples_and_historical_archive_untouched=True,master_clock_projects_acceptance_and_review_retained=True)
    save(BATCH/'cleanup.json',receipt)
    batch=json.loads((BATCH/'batch.json').read_text());batch.update(status='owner_accepted_alignment_and_cleaned',
        owner_acceptance_pending=False,songs=[json.loads((BATCH/slug/'report.json').read_text()) for slug in VALUES],
        files_deleted=deleted);save(BATCH/'batch.json',batch)
    print(json.dumps(dict(cleanup_complete=True,deleted_files=len(deleted),deleted_bytes=receipt['deleted_bytes'],
        preserved_files_verified=receipt['preserved_files_verified'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','cleanup']);args=parser.parse_args()
    (prepare if args.phase=='prepare' else cleanup)()
