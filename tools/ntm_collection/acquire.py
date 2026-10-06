"""Download source materials for a fixed three-recording collection batch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / 'samples/ntm-intake/20261002-new3-v1'
PRIVATE = Path('/tmp/joljak-ntm-new3-20261002/private')
SLUGS = [
    ('doug-weier-real-friends-waiting-room', 'Real Friends — Waiting Room', 25935),
    ('taylor-larson-holding-absence-afterlife', 'Holding Absence — Afterlife', 16609),
    ('jeff-braun-bilmuri-hard2tell', 'Bilmuri — HARD2TELL', 28454),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def emit(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


def save(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_url(value):
    p = urlsplit(value)
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def initialize():
    BATCH.mkdir(parents=True, exist_ok=True)
    path = BATCH / 'selection.json'
    record = dict(owner_instruction='Choose and acquire 3 nonoverlapping songs; prefer plausibly constant tempo/meter without pre-download verification',
        songs=[dict(slug=s, title=t, session_id=i) for s,t,i in SLUGS],
        selection_basis='Rock/pop-punk songs plausibly having stable tempo/meter; unverified until archive inspection',
        source_only_reference_preparation=True, analyzer_or_scorer_adopted=False,
        already_reviewed_sources_unchanged=True, storage_reason='Existing D: has about 12GB free; new jobs use the writable workspace with ample capacity')
    if path.exists():
        assert json.loads(path.read_text()) == record
    else:
        existing = json.loads((ROOT/'samples/catalog.json').read_text())['tracks']
        assert not any(any(s == r['id'] or t == r['title'] for r in existing) for s,t,i in SLUGS)
        assert not any((Path('/mnt/d/NailTheMix/processed')/s).exists() or (Path('/mnt/d/NailTheMix/downloads')/s).exists() for s,t,i in SLUGS)
        save(path, record)


def transfer(url, output, kind):
    import requests
    receipt = output.with_name(output.name + '.transfer.json')
    if receipt.exists() and output.exists():
        r = json.loads(receipt.read_text())
        if r.get('complete') and r['bytes'] == output.stat().st_size and r['sha256'] == digest(output):
            emit(kind=kind, reused_verified=True, file=output.name, bytes=r['bytes'])
            return r
        raise ValueError('existing_transfer_receipt_disagrees')
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_name(output.name + '.part')
    start = part.stat().st_size if part.exists() else 0
    previous = json.loads(receipt.read_text()) if receipt.exists() else {}
    headers = {'Accept-Encoding':'identity','User-Agent':'Joljak local reference preparation'}
    if start:
        if not previous.get('etag') or not previous.get('bytes'):
            raise ValueError('partial_transfer_identity_unavailable')
        if start == previous['bytes']:
            previous.update(complete=True,sha256=digest(part),completed_at_utc=now())
            part.replace(output);save(receipt,previous);return previous
        headers.update(Range=f'bytes={start}-', **{'If-Range':previous['etag']})
    begun = time.monotonic()
    with requests.get(url, headers=headers, stream=True, timeout=(30,180)) as r:
        if start:
            if r.status_code != 206 or not r.headers.get('Content-Range','').startswith(f'bytes {start}-'):
                raise ValueError('resumable_server_response_requires_review')
            if r.headers.get('ETag') != previous['etag']:
                raise ValueError('partial_remote_identity_changed')
        elif r.status_code != 200:
            raise ValueError('media_http_'+str(r.status_code))
        remaining = int(r.headers['Content-Length']) if r.headers.get('Content-Length') else None
        total = start + remaining if remaining is not None else None
        if start and total != previous['bytes']:
            raise ValueError('partial_remote_size_changed')
        if total and shutil.disk_usage(output.parent).free < total-start+1024**3:
            raise ValueError('insufficient_storage')
        mode = 'ab' if start else 'wb'; count = start; printed = time.monotonic()
        save(receipt,dict(complete=False,source=safe_url(url),bytes=total,
             etag=r.headers.get('ETag'),started_at_utc=now()))
        with part.open(mode) as f:
            for block in r.iter_content(4*1024*1024):
                if not block: continue
                f.write(block); count += len(block)
                if time.monotonic()-printed > 20:
                    emit(kind=kind, file=output.name, transferred_bytes=count, total_bytes=total)
                    printed = time.monotonic()
        if total is not None and count != total:
            raise ValueError('transfer_size_mismatch')
        values = dict(complete=True, source=safe_url(url), bytes=count, sha256=digest(part),
            content_length_verified=total is not None, etag=r.headers.get('ETag'),
            completed_at_utc=now(), elapsed_seconds=time.monotonic()-begun)
    part.replace(output); save(receipt,values)
    emit(kind=kind, file=output.name, complete=True, bytes=count, seconds=round(values['elapsed_seconds'],2))
    return values


def decode_master(job, encoded):
    wav = job/'master.wav'; receipt=job/'master-geometry.json'
    if receipt.exists() and wav.exists():
        r=json.loads(receipt.read_text())
        assert digest(wav)==r['sha256'] and digest(encoded)==r['encoded_sha256']
        return r
    if wav.exists(): raise ValueError('unreceipted_decoded_master')
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(encoded),'-map','0:a:0',
        '-vn','-c:a','pcm_f32le',str(wav)],capture_output=True)
    if result.returncode: raise ValueError('master_decode_failed')
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries',
        'stream=sample_rate,channels,duration,duration_ts,time_base,codec_name','-of','json',str(wav)],capture_output=True,text=True)
    if probe.returncode:raise ValueError('master_probe_failed')
    stream=json.loads(probe.stdout)['streams'][0]
    rate=int(stream['sample_rate']);frames=int(stream['duration_ts'])
    assert stream['time_base']==f'1/{rate}'
    values=dict(sha256=digest(wav), encoded_sha256=digest(encoded), bytes=wav.stat().st_size,
        sample_rate=rate,sample_frames=frames,channels=int(stream['channels']),
        duration_seconds=frames/rate,subtype='FLOAT',decoded_without_trim_normalization_resampling_or_time_stretch=True)
    save(receipt,values);emit(master_decoded=True,job=job.name,sample_rate=rate,frames=frames,duration_seconds=frames/rate)
    return values


def validate_zip(job, archive):
    target=job/'archive-inventory.json'
    sha=digest(archive)
    if target.exists():
        values=json.loads(target.read_text())
        if values.get('all_member_crc_passed') and values['archive_sha256']==sha:return values
        raise ValueError('archive_inventory_binding_changed')
    begun=time.monotonic();rows=[];printed=time.monotonic()
    with zipfile.ZipFile(archive) as z:
        members=z.infolist()
        for i,member in enumerate(members):
            path=PurePosixPath(member.filename.replace('\\','/'))
            if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe_archive_member')
            if not member.is_dir():
                with z.open(member) as f:
                    for block in iter(lambda:f.read(8*1024*1024),b''):pass
            rows.append(dict(name=member.filename,bytes=member.file_size,compressed_bytes=member.compress_size,
                crc32=f'{member.CRC:08x}',directory=member.is_dir(),suffix=path.suffix.lower()))
            if time.monotonic()-printed>20:
                emit(zip_crc_job=job.name,checked=i+1,total=len(members));printed=time.monotonic()
    values=dict(archive_sha256=sha,archive_bytes=archive.stat().st_size,all_member_crc_passed=True,
        member_count=len(rows),uncompressed_bytes=sum(r['bytes'] for r in rows),
        elapsed_seconds=time.monotonic()-begun,members=rows)
    save(target,values);emit(zip_crc_job=job.name,complete=True,members=len(rows),seconds=round(values['elapsed_seconds'],2))
    return values


def run(mode, authentication):
    from playwright.sync_api import sync_playwright
    initialize();PRIVATE.mkdir(parents=True,exist_ok=True)
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'legacy/data/tools/ntm-collector/browsers')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path=pw.chromium.executable_path)
        context=browser.new_context(storage_state=str(authentication));page=context.new_page();nonce=[]
        def seen(request):
            if request.url.startswith('https://members.urm.academy/'):
                value=request.headers.get('x-wp-nonce')
                if value:nonce[:]=[value]
        page.on('request',seen)
        page.goto('https://members.urm.academy/ntm-sessions/'+SLUGS[0][0]+'/',wait_until='networkidle',timeout=60000)
        headers={'X-WP-Nonce':nonce[0]} if nonce else {}
        for slug,title,ident in SLUGS:
            job=BATCH/slug;job.mkdir(exist_ok=True)
            response=context.request.get('https://members.urm.academy/wp-json/wp/v2/ntm_session?slug='+slug,headers=headers,timeout=45000)
            if response.status!=200:raise ValueError('session_metadata_http_'+str(response.status))
            rows=[r for r in response.json() if r.get('slug')==slug]
            if len(rows)!=1 or rows[0]['id']!=ident:raise ValueError('session_identity_changed')
            item=rows[0];source_page='https://members.urm.academy/ntm-sessions/'+slug+'/'
            master=item.get('songFile')
            if not isinstance(master,str) or urlsplit(master).scheme!='https':raise ValueError('no_provider_master')
            save(job/'source.json',dict(title=title,slug=slug,session_id=ident,source_page=source_page,
                master_source=safe_url(master),access_confirmed=item.get('hasAccess') is True,inspected_at_utc=now(),
                clock_bpm_and_meter_not_prevalidated=True))
            if mode=='masters':
                suffix=Path(urlsplit(master).path).suffix.lower()
                if suffix not in {'.mp3','.wav','.flac','.m4a'}:raise ValueError('unsupported_master_container')
                encoded=job/('master-original'+suffix);transfer(master,encoded,'master');decode_master(job,encoded)
                continue
            files=item.get('sessionFiles') or {}
            if item.get('hasAccess') is not True:raise ValueError('member_login_required')
            if files.get('rateLimited'):raise ValueError('provider_download_limit_active')
            archive=job/'source.zip'
            if archive.exists() and archive.with_name('source.zip.transfer.json').exists():
                previous=json.loads(archive.with_name('source.zip.transfer.json').read_text())
                assert previous['sha256']==digest(archive)
                validate_zip(job,archive);emit(archive_reused=True,job=slug);continue
            options=[r for r in files.get('files',[]) if r.get('type')=='download' and isinstance(r.get('fileIndex'),int)]
            if not options:raise ValueError('no_provider_archive')
            chosen=min(options,key=lambda r:r['fileIndex'])
            transport=PRIVATE/(slug+'-archive-transport.json')
            if (job/'archive-request.json').exists():
                if not transport.exists():raise ValueError('existing_archive_request_transport_unavailable')
                secret=json.loads(transport.read_text());assert secret['session_id']==ident
                link=secret['url'];emit(reusing_existing_authorized_link=True,job=slug)
            else:
                # Obtain an official download link immediately before transfer.
                r=context.request.post(f'https://members.urm.academy/wp-json/urm/v1/sessions/{ident}/download-link',
                    headers=headers,data={'fileIndex':chosen['fileIndex']},timeout=45000)
                if r.status!=200:raise ValueError('archive_link_http_'+str(r.status))
                body=r.json();link=body.get('link')
                if not isinstance(link,str) or urlsplit(link).scheme!='https':raise ValueError('no_authorized_archive_link')
                fd=os.open(transport,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as secret_file:json.dump(dict(session_id=ident,url=link),secret_file)
                save(job/'archive-request.json',dict(session_id=ident,file_index=chosen['fileIndex'],
                    file_label=chosen.get('title'),requested_at_utc=now(),rate_limit_response=body.get('rateLimit'),
                    official_archive_link_requests=1))
                emit(archive_link_requested=True,job=slug,rate_limit_response=body.get('rateLimit'))
            transfer(link,archive,'archive');validate_zip(job,archive)
        context.close();browser.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['masters','archives']);p.add_argument('--auth-state',type=Path,required=True)
    args=p.parse_args()
    try:run(args.mode,args.auth_state)
    except Exception as error:
        # Requests/Playwright error strings may contain bearer URLs; no raw text.
        safe_error=str(error) if type(error) is ValueError and re.fullmatch(r'[a-z0-9_]+',str(error)) else None
        emit(status='collection_needs_attention',error_type=type(error).__name__,reason=safe_error)
        raise SystemExit(2)
