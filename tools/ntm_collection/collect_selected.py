"""Acquire explicitly selected NTM sources without running integrity test suites.

Normal member metadata and quota responses are required acquisition inputs.
Archive-link requests are issued once per selected session and retained privately.
No ZIP-wide CRC scan, playback check, analyzer, or automatic acceptance is run.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,re,subprocess
from urllib.parse import urlsplit,urlunsplit
from zoneinfo import ZoneInfo
import requests
from playwright.sync_api import sync_playwright
if __package__:
    from .storage import bind_selected, note_stage, assert_candidate_allowed, library_root
else:
    from storage import bind_selected, note_stage, assert_candidate_allowed, library_root

REPO=Path(__file__).resolve().parents[2]
PRIVATE=REPO/'data/private/ntm'


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.partial')
    with temporary.open('w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    temporary.replace(path)


def safe_url(url):
    p=urlsplit(url);return urlunsplit((p.scheme,p.netloc,p.path,'',''))


def emit(**values):print(json.dumps(values,ensure_ascii=False),flush=True)


def transfer(url,path,label):
    receipt_path=path.with_name(path.name+'.transfer.json')
    if path.exists() and receipt_path.exists():
        prior=json.loads(receipt_path.read_text())
        if prior.get('complete'):emit(file=path.name,source=label,reusing_previous_transfer=True);return
    path.parent.mkdir(parents=True,exist_ok=True);part=path.with_name(path.name+'.part')
    start=part.stat().st_size if part.exists() else 0
    headers={'Accept-Encoding':'identity'}
    if start:headers['Range']=f'bytes={start}-'
    response=requests.get(url,headers=headers,stream=True,timeout=(30,180))
    if response.status_code not in ([206] if start else [200]):raise RuntimeError('transfer_http_'+str(response.status_code))
    expected=int(response.headers.get('Content-Length','0'))+start
    digest=hashlib.sha256()
    if start:
        with part.open('rb') as f:
            for data in iter(lambda:f.read(8*1024*1024),b''):digest.update(data)
    import time
    printed=time.monotonic();written=start
    save(receipt_path,dict(complete=False,source=safe_url(url),expected_bytes=expected,bytes=written))
    with part.open('ab' if start else 'wb') as f:
        for data in response.iter_content(4*1024*1024):
            if not data:continue
            f.write(data);digest.update(data);written+=len(data)
            if time.monotonic()-printed>20:
                f.flush()
                save(receipt_path,dict(complete=False,source=safe_url(url),expected_bytes=expected,bytes=written))
                emit(source=label,file=path.name,transferred_bytes=written,expected_bytes=expected);printed=time.monotonic()
        f.flush();os.fsync(f.fileno())
    part.replace(path)
    save(receipt_path,dict(complete=True,source=safe_url(url),bytes=written,expected_bytes=expected,
                           sha256=digest.hexdigest(),checksum_recorded_for_inventory=True,post_transfer_integrity_checks_run=False))
    emit(source=label,file=path.name,downloaded_bytes=written)


def member_master(context,url,path,label,source_page):
    """Use ordinary authenticated member access for protected site uploads."""
    if urlsplit(url).hostname!='members.urm.academy':
        return transfer(url,path,label)
    receipt_path=path.with_name(path.name+'.transfer.json')
    if path.exists() and receipt_path.exists() and json.loads(receipt_path.read_text()).get('complete'):
        emit(file=path.name,source=label,reusing_previous_transfer=True);return
    response=context.request.get(url,headers={'Referer':source_page},timeout=180000)
    if response.status!=200:raise RuntimeError('master_transfer_http_'+str(response.status))
    data=response.body();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.part');temporary.write_bytes(data);temporary.replace(path)
    save(receipt_path,dict(complete=True,source=safe_url(url),bytes=len(data),
        expected_bytes=int(response.headers.get('content-length',len(data))),
        sha256=hashlib.sha256(data).hexdigest(),transport='authenticated_member_browser_request',
        checksum_recorded_for_inventory=True,post_transfer_integrity_checks_run=False))
    response.dispose()
    emit(source=label,file=path.name,downloaded_bytes=len(data))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path,required=True);parser.add_argument('--auth',type=Path,required=True)
    parser.add_argument('--slug');parser.add_argument('--refresh-recorded-link',action='store_true')
    args=parser.parse_args();batch=args.batch;selection=json.loads((batch/'selection.json').read_text())
    if args.slug:
        targets=[s for s in selection['songs'] if s['slug']==args.slug]
        for song in targets or [dict(slug=args.slug)]:assert_candidate_allowed(song)
    if args.slug and any(s['slug']==args.slug and not s.get('collection_enabled',True) for s in selection['songs']):
        raise RuntimeError('owner_excluded_source')
    songs=[s for s in selection['songs'] if s.get('collection_enabled',True) and (args.slug is None or s['slug']==args.slug)]
    if not songs:raise RuntimeError('selection_missing')
    bind_selected(batch,songs)
    # Skip completed transfers whose archives were intentionally removed.
    songs=[s for s in songs if not ((library_root()/s['slug']/'collection/source.zip.transfer.json').exists() and
        json.loads((library_root()/s['slug']/'collection/source.zip.transfer.json').read_text()).get('current_file_disposition')=='intentionally_removed_after_owner_approved_cleanup')]
    if not songs:
        emit(status='selected_sources_already_finalized',new_provider_requests=0);return
    PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(PRIVATE,0o700)
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(REPO/'data/runtime/ntm-collector/browsers')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=p.chromium.executable_path)
        context=browser.new_context(storage_state=str(args.auth));page=context.new_page();nonce=[]
        def seen(request):
            if request.url.startswith('https://members.urm.academy/'):
                value=request.headers.get('x-wp-nonce')
                if value:nonce[:]=[value]
        page.on('request',seen)
        page.goto('https://members.urm.academy/ntm-sessions/'+songs[0]['slug']+'/',wait_until='networkidle',timeout=45000)
        if not nonce:
            value=page.evaluate('window.wpApiSettings?.nonce??null')
            if value:nonce.append(value)
        if not nonce and (PRIVATE/'nonce.json').exists():nonce.append(json.loads((PRIVATE/'nonce.json').read_text())['nonce'])
        headers={'X-WP-Nonce':nonce[0]} if nonce else {}
        for song in songs:
            slug=song['slug'];job=library_root()/slug/'collection';job.mkdir(exist_ok=True)
            response=context.request.get('https://members.urm.academy/wp-json/wp/v2/ntm_session/'+str(song['session_id']),headers=headers,timeout=45000)
            if response.status!=200:raise RuntimeError('session_metadata_http_'+str(response.status))
            item=response.json()
            if not isinstance(item,dict) or item.get('id')!=song['session_id'] or item.get('slug')!=slug:
                raise RuntimeError('session_metadata_identity_mismatch')
            if item.get('hasAccess') is not True:raise RuntimeError('member_login_required')
            save(job/'source.json',dict(title=song['title'],slug=slug,session_id=item['id'],source_page='https://members.urm.academy/ntm-sessions/'+slug+'/',
                 access_confirmed=True,master_source=safe_url(item['songFile']),acquired_date_local=datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()))
            master=item['songFile'];extension=Path(urlsplit(master).path).suffix.lower()
            encoded=job/('master-original'+extension);member_master(context,master,encoded,song['title']+' Master',
                song.get('source_page','https://members.urm.academy/ntm-sessions/'+slug+'/'))
            wav=job/'master.wav'
            if not wav.exists():
                temporary=job/'master.partial.wav'
                subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(encoded),'-map','0:a:0','-vn','-c:a','pcm_f32le',str(temporary)],check=True)
                temporary.replace(wav)
            files=item.get('sessionFiles') or {}
            archive=job/'source.zip';request_path=job/'archive-request.json'
            if archive.exists() and archive.with_name('source.zip.transfer.json').exists():
                note_stage(song,batch,'acquired_pending_clock_preparation');continue
            transport=PRIVATE/(slug+'-transport.json')
            if request_path.exists() and transport.exists():link=json.loads(transport.read_text())['url']
            else:
                prior=json.loads(request_path.read_text()) if request_path.exists() else None
                if prior and not args.refresh_recorded_link:raise RuntimeError('recorded_transport_missing')
                if files.get('rateLimited'):
                    save(job/'resume-status.json',dict(status='provider_download_limit_active',partial_preserved=True,
                         recorded_archive_request=bool(prior),observed_at_utc=datetime.now(timezone.utc).isoformat()))
                    raise RuntimeError('provider_download_limit_active')
                choices=[f for f in files.get('files',[]) if f.get('type')=='download' and isinstance(f.get('fileIndex'),int)]
                option=(next(f for f in choices if f['fileIndex']==prior['file_index']) if prior else min(choices,key=lambda f:f['fileIndex']))
                response=context.request.post(f'https://members.urm.academy/wp-json/urm/v1/sessions/{item["id"]}/download-link',
                        headers=headers,data={'fileIndex':option['fileIndex']},timeout=45000)
                if response.status!=200:raise RuntimeError('archive_link_http_'+str(response.status))
                value=response.json();link=value['link']
                fd=os.open(transport,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(fd,'w') as f:json.dump({'url':link,'session_id':item['id']},f)
                receipt=dict(session_id=item['id'],file_index=option['fileIndex'],file_label=option.get('title'),
                    requested_at_utc=datetime.now(timezone.utc).isoformat(),rate_limit_response=value.get('rateLimit'),
                    official_archive_link_requests=1+(prior.get('official_archive_link_requests',0) if prior else 0))
                if prior:receipt['previous_requests']=[*prior.get('previous_requests',[]),{k:v for k,v in prior.items() if k!='previous_requests'}]
                save(request_path,receipt)
                emit(source=song['title'],archive_link_requested=True,recorded_link_refresh=bool(prior),rate_limit_response=value.get('rateLimit'))
            transfer(link,archive,song['title']+' multitracks')
            note_stage(song,batch,'acquired_pending_clock_preparation')
        context.storage_state(path=str(PRIVATE/'auth-state.json'));os.chmod(PRIVATE/'auth-state.json',0o600)
        browser.close()
    emit(acquisition_complete=True,source_count=len(songs),archive_integrity_tests_run=False)


if __name__=='__main__':
    try:main()
    except Exception as error:
        message=str(error)
        safe=message if re.fullmatch('[a-z0-9_]+',message) else type(error).__name__
        emit(status='collection_needs_attention',reason=safe)
        raise SystemExit(2)
