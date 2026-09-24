"""One-song finished-master / full-ZIP / clock-alignment preparation pipeline.

Full archive download and all-member CRC validation precede selection. Only
pipeline-owned temporary files may be deleted; supplied local inputs are never
modified. Failed qualification stops at a recorded exception, not a guessed map.
"""
import argparse
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
import zipfile

import numpy as np
import soundfile as sf
import soxr

from audit_source_alignment import audit, AlignmentConfig
from build_alignment_review import render_clicks
from inspect_inputs import sha256
from midi_reference import clocks_agree
from prepare_multitrack_sample import read_tempo_map


RESERVE = 10_000_000_000
MAX_ARCHIVE = 30_000_000_000
MAX_MEMBER = 1_000_000_000
MAX_METADATA = 30_000_000
VERSION = 1


class Attention(RuntimeError):
    """A predefined exception code safe to expose without a bearer URL."""


def save(path, value):
    path = Path(path)
    tmp = path.with_name(path.name+'.writing')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(path)


def space(path, needed=0, reserve=RESERVE):
    if shutil.disk_usage(path).free < needed+reserve:
        raise Attention('disk_reserve_reached')


def full_download(url, destination, *, max_bytes=MAX_ARCHIVE, reserve=RESERVE):
    """Full GET, with version-pinned resume; never issue selective ZIP reads."""
    destination = Path(destination)
    receipt = destination.with_name(destination.name+'.transfer.json')
    partial = destination.with_name(destination.name+'.partial')
    if destination.exists():
        if receipt.exists():
            r = json.loads(receipt.read_text())
            if r.get('complete') and sha256(destination) == r.get('sha256'):
                return r
        raise Attention('existing_download_without_valid_receipt')
    if urlsplit(url).scheme != 'https':
        raise Attention('https_asset_required')
    position = partial.stat().st_size if partial.exists() else 0
    previous = json.loads(receipt.read_text()) if receipt.exists() else {}
    headers = {'Accept-Encoding': 'identity', 'User-Agent': 'Joljak local reference preparation'}
    if position:
        if not previous.get('etag') or previous.get('complete'):
            raise Attention('partial_download_requires_version_review')
        headers.update(Range=f'bytes={position}-', **{'If-Range': previous['etag']})
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        raise Attention(f'asset_http_{e.code}_refresh_login_or_link') from None
    except Exception:
        raise Attention('asset_connection_failed_resume_available') from None
    with response:
        if position:
            total = previous['bytes']
            if (response.status != 206 or response.headers.get('Content-Range') != f'bytes {position}-{total-1}/{total}'
                    or response.headers.get('ETag') != previous['etag']):
                raise Attention('partial_download_identity_changed')
        else:
            if response.status != 200 or not response.headers.get('Content-Length'):
                raise Attention('full_download_length_unavailable')
            total = int(response.headers['Content-Length'])
        if not 0 < total <= max_bytes:
            raise Attention('asset_exceeds_size_budget')
        space(destination.parent, total-position, reserve)
        metadata = {'bytes': total, 'etag': response.headers.get('ETag'), 'complete': False,
                    'strategy': 'complete_file_download_with_optional_suffix_resume'}
        save(receipt, metadata)
        reported = time.monotonic()
        with partial.open('ab' if position else 'wb') as out:
            while True:
                try:
                    chunk = response.read(min(4*1024*1024, total-position+1))
                except Exception:
                    raise Attention('asset_transfer_interrupted_resume_available') from None
                if not chunk:
                    break
                if position+len(chunk) > total:
                    raise Attention('asset_body_exceeds_declared_length')
                space(destination.parent, len(chunk), reserve)
                out.write(chunk); position += len(chunk)
                if time.monotonic()-reported >= 10:
                    print(json.dumps({'stage': 'download', 'asset': destination.name, 'percent': round(100*position/total,1)}), flush=True)
                    reported = time.monotonic()
            out.flush(); os.fsync(out.fileno())
    if position != total:
        raise Attention('asset_transfer_truncated_resume_available')
    metadata.update(complete=True, sha256=sha256(partial))
    partial.replace(destination); save(receipt, metadata)
    return metadata


def archive_rows(archive):
    rows = archive.infolist()
    names = [r.filename for r in rows]
    if len(names) != len(set(names)):
        raise Attention('duplicate_archive_member')
    total = 0
    for item in rows:
        name = item.filename.replace('\\','/')
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or ':' in name or any(ord(c)<32 for c in name):
            raise Attention('unsafe_archive_member')
        if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
            raise Attention('archive_link_or_encryption_requires_review')
        total += item.file_size
    if total > 100_000_000_000:
        raise Attention('archive_expansion_budget_exceeded')
    return [r for r in rows if not r.is_dir() and '__MACOSX' not in PurePosixPath(r.filename).parts
            and not PurePosixPath(r.filename).name.startswith('._')]


def extract(archive, info, target, budget, reserve=RESERVE):
    if info.file_size > budget:
        raise Attention('selected_member_exceeds_budget')
    target = Path(target)
    space(target.parent, info.file_size, reserve)
    if target.exists():
        raise Attention('selected_output_already_exists')
    count = 0
    with archive.open(info) as src, target.open('xb') as dst:
        while block := src.read(1024*1024):
            count += len(block)
            if count > info.file_size:
                raise Attention('selected_member_size_mismatch')
            dst.write(block)
    if count != info.file_size:
        raise Attention('selected_member_truncated')
    return {'member': info.filename, 'bytes': count, 'crc32': f'{info.CRC:08x}',
            'sha256': sha256(target), 'path': str(target)}


def stem_selection(rows):
    wavs = [r for r in rows if PurePosixPath(r.filename).suffix.lower() in ('.wav', '.flac')]
    selected = []
    for pattern in (r'(?i)(?:^|[ _-])(?:kick|kik|bd|bass.?drum)(?:[ _.-]|$)',
                    r'(?i)(?:^|[ _-])(?:snare|snr|drums?)(?:[ _.-]|$)'):
        matches = [r for r in wavs if re.search(pattern, PurePosixPath(r.filename).name)
                   and not re.search(r'(?i)click|guide|metronome', r.filename)]
        matches.sort(key=lambda r:(bool(re.search(r'(?i)sample|trig|midi', r.filename)),r.filename.casefold()))
        if matches and matches[0] not in selected:
            selected.append(matches[0])
    return selected


def parse_rpp(text):
    """Read explicit item/source positions and step tempo/meter rows only."""
    root = {'tag':'ROOT','lines':[],'children':[]}; stack=[root]
    for raw in text.splitlines():
        line=raw.strip()
        if line.startswith('<'):
            node={'tag':line[1:].split()[0], 'lines':[], 'children':[]}
            stack[-1]['children'].append(node); stack.append(node)
        elif line=='>':
            if len(stack)==1: raise Attention('invalid_rpp_nesting')
            stack.pop()
        else: stack[-1]['lines'].append(line)
    if len(stack)!=1: raise Attention('invalid_rpp_nesting')
    def walk(n):
        yield n
        for c in n['children']: yield from walk(c)
    nodes=list(walk(root));items=[];points=[]
    for n in nodes:
        if n['tag']=='ITEM':
            values={line.split()[0]:line.split()[1:] for line in n['lines'] if line}
            sources=[c for c in walk(n) if c['tag']=='SOURCE']
            files=[re.match(r'^FILE "(.*)"$',line).group(1) for c in sources for line in c['lines'] if re.match(r'^FILE "(.*)"$',line)]
            if len(sources)!=1 or len(files)!=1 or any(k.startswith('SM') for k in values):
                continue
            try:
                items.append({'name':PurePosixPath(files[0].replace('\\','/')).name,
                              'position':float(values['POSITION'][0]),'source_offset':float(values['SOFFS'][0]),
                              'rate':float(values['PLAYRATE'][0]),'length':float(values['LENGTH'][0])})
            except (KeyError, ValueError, IndexError): continue
        if n['tag']=='TEMPOENVEX':
            for line in n['lines']:
                if line.startswith('PT '):
                    x=line.split()
                    if len(x)<5 or int(x[3])!=1: raise Attention('rpp_tempo_ramp_requires_review')
                    signature=int(x[4])
                    points.append({'time_seconds':float(x[1]),'bpm':float(x[2]),
                                   'numerator':signature & 65535,'denominator':signature >> 16})
    return items,points


def project_origin(rpp_paths, clock, stem_name):
    candidates=[]
    for path in rpp_paths:
        try: items,points=parse_rpp(path.read_text(encoding='utf-8-sig'))
        except (UnicodeError,Attention): continue
        tempo=[];meter=[]
        for p in points:
            if not tempo or p['bpm'] != tempo[-1]['bpm']:tempo.append(p)
            if p['numerator'] and p['denominator'] and (not meter or (p['numerator'],p['denominator'])!=(meter[-1]['numerator'],meter[-1]['denominator'])):meter.append(p)
        if len(tempo)!=len(clock['tempo_events']) or len(meter)!=len(clock['meter_events']):continue
        if any(abs(a['time_seconds']-b['time_seconds'])>.001 or abs(a['bpm']-b['bpm_quarter'])>.001 for a,b in zip(tempo,clock['tempo_events'])):continue
        if any(abs(a['time_seconds']-b['time_seconds'])>.001 or (a['numerator'],a['denominator'])!=(b['numerator'],b['denominator']) for a,b in zip(meter,clock['meter_events'])):continue
        matches=[i for i in items if i['name']==stem_name]
        if len(matches)==1 and matches[0]['rate']==1 and matches[0]['length']>0:
            i=matches[0];candidates.append({'project':str(path), 'file_zero_in_project_seconds':i['position']-i['source_offset'], 'item':i})
    if not candidates or any(abs(c['file_zero_in_project_seconds']-candidates[0]['file_zero_in_project_seconds'])>1e-9 for c in candidates):
        raise Attention('project_source_origin_requires_review')
    return candidates[0]


def clock_events(clock, duration):
    """Quarter pulses with explicit meter-unit beat markers, including /8 meters."""
    tpq=clock['ticks_per_quarter'];tempos=clock['tempo_events'];meters=clock['meter_events']
    def seconds(tick):
        i=max(i for i,e in enumerate(tempos) if e['tick']<=tick)
        e=tempos[i];return e['time_seconds']+(tick-e['tick'])/tpq*e['microseconds_per_quarter']/1e6
    quarters=[];q=0
    while seconds(q*tpq)<duration:
        tick=q*tpq;m=max((e for e in meters if e['tick']<=tick),key=lambda e:e['tick'])
        bar_ticks=tpq*4*m['numerator']/m['denominator']
        phase=(tick-m['tick'])/bar_ticks
        quarters.append({'source_seconds':seconds(tick),'quarter_index':q,'accent':abs(phase-round(phase))<1e-9})
        q+=1
    pulses=[]
    for index,m in enumerate(meters):
        stop=meters[index+1]['tick'] if index+1<len(meters) else float('inf')
        unit=tpq*4/m['denominator'];n=0
        while m['tick']+n*unit<stop:
            t=seconds(m['tick']+n*unit)
            if t>=duration:break
            pulses.append({'source_seconds':t,'quarter_index':len(pulses),'accent':n%m['numerator']==0})
            n+=1
    return quarters,pulses


def cleanup_owned(work, expected):
    """Never recurse, glob-delete, follow symlinks, or delete caller inputs."""
    work=Path(work)
    if work.is_symlink():raise Attention('cleanup_refuses_symlink')
    actual={p.name for p in work.iterdir()}
    if actual != set(expected):raise Attention('cleanup_unexpected_file_preserved')
    for name in sorted(expected):
        path=work/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file():raise Attention('cleanup_refuses_unsafe_path')
    deleted=[]
    for name in sorted(expected):
        path=work/name;deleted.append({'name':name,'bytes':path.stat().st_size});path.unlink()
    work.rmdir();return deleted


def decode_master(encoded, output, reserve=RESERVE):
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_entries',
                          'stream=sample_rate,channels,duration:format=duration','-of','json',str(encoded)],capture_output=True,text=True,check=True)
    data=json.loads(probe.stdout);s=data['streams'][0]
    duration=float(s.get('duration') or data['format']['duration']);rate=int(s['sample_rate']);channels=int(s['channels'])
    expected=math.ceil((duration+5)*rate*channels*4)
    if channels not in (1,2) or expected>1_000_000_000:raise Attention('master_geometry_requires_review')
    space(output.parent,expected,reserve)
    run=subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(encoded),'-map','0:a:0','-c:a','pcm_f32le',str(output)],capture_output=True)
    if run.returncode:raise Attention('master_decode_failed')
    info=sf.info(output)
    return {'encoded_sha256':sha256(encoded),'canonical_sha256':sha256(output),'sample_rate':info.samplerate,
            'sample_frames':info.frames,'channels':info.channels,'subtype':info.subtype,
            'decoder':subprocess.run(['ffmpeg','-version'],capture_output=True,text=True).stdout.splitlines()[0],
            'trimming':False,'resampling':False,'normalization':False}


def process(archive_path, master_path, output, *, title, metadata=None, reserve=RESERVE, own_archive=False):
    """Process complete local assets. Caller-owned originals are read-only."""
    out=Path(output);work=out/'_work';refs=out/'references';work.mkdir(exist_ok=True);refs.mkdir(exist_ok=True)
    if any(refs.iterdir()):raise Attention('reference_outputs_exist_choose_new_job')
    owned={p.name for p in work.iterdir()} if own_archive else set()
    if own_archive and owned-{'source.zip','source.zip.transfer.json'}:raise Attention('unexpected_download_work_files')
    start=time.monotonic();report={'version':VERSION,'status':'processing','title':title,'source':metadata or {},
        'input_archive_sha256':sha256(archive_path),'input_master_sha256':sha256(master_path),
        'full_archive_present':True,'archive_all_members_crc_passed':False,'automatic_reference_qualification':False,
        'absolute_timing_verified':False,'target_evaluation_eligible':False,'model_inference_performed':False,
        'timings_seconds':{},'pipeline_sha256':sha256(__file__) }
    def checkpoint(stage):
        report['stage']=stage;report['elapsed_seconds']=round(time.monotonic()-start,3);save(out/'report.json',report)
        print(json.dumps({'stage':stage,'elapsed_seconds':report['elapsed_seconds']}),flush=True)
    checkpoint('verify_full_zip')
    try:
        with zipfile.ZipFile(archive_path) as archive:
            rows=archive_rows(archive)
            if archive.testzip() is not None:raise Attention('archive_crc_failed')
            report['archive_all_members_crc_passed']=True
            report['timings_seconds']['full_zip_validation']=round(time.monotonic()-start,3)
            save(out/'archive-inventory.json',{'archive_sha256':report['input_archive_sha256'],
                'members':[{'name':i.filename,'bytes':i.file_size,'compressed_bytes':i.compress_size,'crc32':f'{i.CRC:08x}'} for i in rows],
                'all_members_crc_passed':True})
            checkpoint('extract_clock_and_alignment_sources')
            mids=[r for r in rows if PurePosixPath(r.filename).suffix.lower() in ('.mid','.midi')]
            rpps=[r for r in rows if PurePosixPath(r.filename).suffix.lower()=='.rpp']
            chosen_meta=mids+rpps
            if not mids:
                chosen_meta += [r for r in rows if PurePosixPath(r.filename).suffix.lower() in ('.cpr','.smt','.ptx','.song')]
            if sum(r.file_size for r in chosen_meta)>MAX_METADATA:raise Attention('metadata_budget_requires_review')
            records=[];clocks=[];rpp_paths=[]
            for i,member in enumerate(chosen_meta):
                suffix=PurePosixPath(member.filename).suffix.lower();target=refs/f'{i:03d}{suffix}'
                records.append(extract(archive,member,target,MAX_METADATA,reserve))
                if suffix in ('.mid','.midi'):
                    try:clocks.append((target,read_tempo_map(target)))
                    except (ValueError,EOFError,OSError):pass
                elif suffix=='.rpp':rpp_paths.append(target)
            report['retained_clock_assets']=records
            if not clocks:raise Attention('explicit_tempo_and_meter_midi_required')
            if any(not clocks_agree(clocks[0][1],c) for _,c in clocks[1:]):raise Attention('conflicting_midi_clocks_require_review')
            midi,clock=clocks[0];shutil.copyfile(midi,out/'tempo-original.mid');save(out/'tempo-original.json',clock)
            stems=stem_selection(rows)
            if not stems:raise Attention('no_alignment_source_recognized')
            # One minimal source per role; all other archive content was CRC-checked but never extracted.
            stem_assets=[]
            for i,member in enumerate(stems):
                target=work/f'alignment-source-{i}{PurePosixPath(member.filename).suffix.lower()}'
                asset=extract(archive,member,target,MAX_MEMBER,reserve);owned.add(target.name)
                asset['basename']=PurePosixPath(member.filename).name;stem_assets.append(asset)
        report['alignment_source_assets']=stem_assets
        checkpoint('decode_master')
        canonical=out/'master.wav'
        report['decode']=decode_master(master_path,canonical,reserve)
        audio,rate=sf.read(canonical,dtype='float32',always_2d=True)
        if not np.isfinite(audio).all():raise Attention('nonfinite_master_samples')
        checkpoint('estimate_constant_offset')
        audits=[];accepted=None
        for asset in stem_assets:
            source,sr=sf.read(asset['path'],dtype='float32',always_2d=True)
            origin=project_origin(rpp_paths,clock,asset['basename'])
            if not np.isfinite(source).all():raise Attention('nonfinite_source_samples')
            mix=soxr.resample(audio.mean(axis=1),rate,sr,quality='VHQ')
            config=AlignmentConfig(windows=9,window_seconds=15,maximum_offset_seconds=8,
                                   minimum_correlation=.2,minimum_agreeing_windows=7,maximum_frame_spread=round(sr*.001))
            try:result=audit(mix,source.mean(axis=1),sr,config)
            except ValueError:continue
            result.update(source_member=asset['member'],source_sample_rate=sr,project_origin=origin)
            audits.append(result)
            if result['qualified_constant_offset']:
                delta=-result['stem_minus_mix_frames']/sr-origin['file_zero_in_project_seconds']
                accepted={'offset_seconds':delta,'source_duration_seconds':len(source)/sr,
                          'project_duration_seconds':origin['item']['position']+origin['item']['length'],
                          'source_rate':sr,'audit':result}
                break
        report['audits']=audits
        if accepted is None:raise Attention('constant_offset_gate_failed')
        offset=accepted['offset_seconds'];report['alignment']=accepted
        checkpoint('write_aligned_map_and_listening_files')
        quarters,pulses=clock_events(clock,accepted['project_duration_seconds'])
        aligned={'kind':'automatically_aligned_producer_map_for_listening_review','master_sha256':report['decode']['canonical_sha256'],
            'midi_sha256':clock['midi_sha256'],'transform':'t_master = t_project + offset_seconds','offset_seconds':offset,'time_scale':1.,
            'tempo_events':[dict(e,master_seconds=e['time_seconds']+offset) for e in clock['tempo_events']],
            'meter_events':[dict(e,master_seconds=e['time_seconds']+offset) for e in clock['meter_events']],
            'quarter_events':[dict(e,master_seconds=e['source_seconds']+offset,master_frame=math.floor((e['source_seconds']+offset)*rate+.5)) for e in quarters],
            'absolute_timing_verified':False,'target_evaluation_eligible':False,'human_alignment_accepted':False,
            'mapped_source_end_seconds':accepted['project_duration_seconds']+offset,
            'negative_events':'Retained as preceding clock context, not clamped to audio zero.'}
        save(out/'tempo-aligned.json',aligned)
        clicks,placements=render_clicks(pulses,offset,rate,len(audio))
        space(out,len(audio)*(3+audio.shape[1]*3),reserve)
        sf.write(out/'click-aligned.wav',clicks,rate,subtype='PCM_24')
        master_gain=min(.4,.65/max(float(np.max(np.abs(audio))),1e-9));audition=audio*master_gain+clicks[:,None]*.8
        sf.write(out/'listen-aligned.wav',audition,rate,subtype='PCM_24')
        for filename,expected in [('click-aligned.wav',clicks[:,None]),('listen-aligned.wav',audition)]:
            actual,rr=sf.read(out/filename,dtype='float32',always_2d=True)
            if rr!=rate or actual.shape!=expected.shape or np.max(np.abs(actual-expected))>2**-23 or np.max(np.abs(actual))>=1:
                raise Attention('render_verification_failed')
        report['click_render']={'pulses':len(pulses),'quarters':len(quarters),'meter_unit_clicks':True,
                               'omitted':sum(r['render_status']=='omitted' for r in placements),'master_gain':master_gain,
                               'sample_rate':rate,'sample_frames':len(audio),'all_output_samples_verified':True}
        ends=max(0,len(audio)/rate-30)
        page=f'''<!doctype html><meta charset="utf-8"><title>정렬 검토</title><style>body{{font:18px/1.6 system-ui;max-width:850px;margin:50px auto;padding:20px;background:#14202c;color:#eee}}button,a{{font:inherit;margin:5px;color:#8ce2ce}}button{{background:#294354;border:1px solid #699;padding:8px;cursor:pointer}}audio{{width:100%}}</style>
<h1>{html.escape(title)}</h1><p>자동 정렬 후보: 지도 {offset*1000:+.4f}ms · 음원/BPM 간격 유지</p><p>전곡 청취 확인 전입니다. 초반·중반·후반에 같은 보정이 맞는지 확인하세요.</p><audio id="a" controls src="listen-aligned.wav"></audio><p>'''+''.join(f'<button onclick="document.getElementById(\'a\').currentTime={t}">{label}</button>' for label,t in [('초반',0),('중반',len(audio)/rate/2),('후반',ends)])+'''</p><p><a href="master.wav">Master WAV</a> · <a href="click-aligned.wav">보정 클릭 WAV</a> · <a href="tempo-aligned.json">Master 대응 지도</a></p><p>Cubase에서는 Master와 클릭 WAV를 같은 절대 0초에 놓으세요. 원본 MIDI와 원본 음원은 수정하지 않았습니다.</p>'''
        (out/'review.html').write_text(page,encoding='utf-8')
        if sha256(archive_path)!=report['input_archive_sha256'] or sha256(master_path)!=report['input_master_sha256']:
            raise Attention('input_changed_during_processing')
        report['retained_outputs']={p.name:{'sha256':sha256(p),'bytes':p.stat().st_size} for p in out.iterdir() if p.is_file() and p.name not in ('report.json','.pipeline-owner.json')}
        # Save complete verified output evidence before deleting this job's temporary assets.
        report['status']='verified_outputs_pending_cleanup';checkpoint('cleanup_owned_temporary_files')
        report['deleted_temporary_files']=cleanup_owned(work,owned)
        report['status']='ready_for_listening_review';report['timings_seconds']['total_processing']=round(time.monotonic()-start,3)
        checkpoint('complete');return report
    except Exception as error:
        report['status']='needs_attention';report['reason']=str(error) if isinstance(error,Attention) else type(error).__name__;report['temporary_inputs_preserved']=True;checkpoint('stopped')
        return report


def run(args):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',args.slug):raise Attention('invalid_slug')
    root=Path(args.output_root);root.mkdir(parents=True,exist_ok=True);out=root/args.slug
    if out.is_symlink():raise Attention('job_directory_symlink_refused')
    resuming=False
    if out.exists():
        report_path=out/'report.json'
        if report_path.exists() and json.loads(report_path.read_text()).get('status')=='ready_for_listening_review':
            r=json.loads(report_path.read_text())
            if all((out/name).is_file() and sha256(out/name)==v['sha256'] for name,v in r['retained_outputs'].items()):
                return {'status':'already_complete','output':str(out)}
        owner=out/'.pipeline-owner.json'
        if args.resume and not report_path.exists() and owner.exists() and json.loads(owner.read_text()).get('pipeline_version')==VERSION:
            resuming=True
        else:raise Attention('existing_incomplete_job_preserved_review_report_or_resume_download')
    space(root)
    if not resuming:
        out.mkdir()
        save(out/'.pipeline-owner.json',{'pipeline_version':VERSION,'run_id':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat()})
    work=out/'_work';work.mkdir(exist_ok=True)
    if work.is_symlink():raise Attention('job_work_symlink_refused')
    transport=None;private_plan=None
    try:
        if bool(args.local_archive)!=bool(args.local_master):raise Attention('provide_both_local_inputs')
        if args.local_archive:
            archive=Path(args.local_archive).resolve();original=Path(args.local_master).resolve();own_archive=False
            metadata={'mode':'existing_full_local_archive','caller_inputs_preserved':True}
            target=out/('master-original'+original.suffix.lower())
            space(out,original.stat().st_size)
            if target.exists():raise Attention('local_master_copy_already_exists')
            shutil.copyfile(original,target);master=target
        else:
            workspace=Path(__file__).resolve().parents[2];runtime=workspace/'data/tools/ntm-collector'
            private_plan=runtime/'private'/('transport-'+uuid.uuid4().hex+'.json')
            command=[str(runtime/'venv/bin/python'),str(Path(__file__).with_name('ntm_member_source.py')),
                '--slug',args.slug,'--auth-state',str(runtime/'private/auth-state.json'),
                '--browser-root',str(runtime/'browsers'),'--output',str(private_plan)]
            if args.archive_index is not None:command.extend(['--file-index',str(args.archive_index)])
            result=subprocess.run(command,capture_output=True,text=True)
            if result.returncode:raise Attention('member_access_or_download_limit_requires_attention')
            transport=json.loads(private_plan.read_text());metadata=transport['metadata']
            suffix=PurePosixPath(urlsplit(transport['master_url']).path).suffix.lower()
            if suffix not in ('.mp3','.wav','.flac','.m4a'):raise Attention('unsupported_master_container')
            master=out/('master-original'+suffix)
            full_download(transport['master_url'],master,max_bytes=500_000_000)
            archive=work/'source.zip';full_download(transport['archive_url'],archive);own_archive=True
        save(out/'source.json',metadata)
        report=process(archive,master,out,title=args.title or metadata.get('title') or args.slug,metadata=metadata,own_archive=own_archive)
        report['output']=str(out);return report
    finally:
        if private_plan is not None and private_plan.exists():private_plan.unlink()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slug',required=True);p.add_argument('--title')
    p.add_argument('--output-root',default='/mnt/d/NailTheMix/processed')
    p.add_argument('--local-master');p.add_argument('--local-archive')
    p.add_argument('--archive-index',type=int,help='Required only when the provider offers distinct non-mirror packages')
    p.add_argument('--resume',action='store_true',help='Resume only an interrupted transfer before processing; failed qualification is never silently retried')
    args=p.parse_args()
    try:
        r=run(args);print(json.dumps({k:r[k] for k in ['status','reason','output','timings_seconds'] if k in r},ensure_ascii=False,indent=2))
        return 0 if r['status'] in ('ready_for_listening_review','already_complete') else 2
    except Exception as error:
        # Uncontrolled exceptions may contain authentication URLs: suppress their message/traceback.
        reason=str(error) if isinstance(error,Attention) else type(error).__name__
        print(json.dumps({'status':'needs_attention','reason':reason}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
