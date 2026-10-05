"""One-song finished-master / full-ZIP / clock-alignment preparation pipeline.

Full archive download and all-member CRC validation precede selection. Only
pipeline-owned temporary files may be deleted; supplied local inputs are never
modified. Automatic qualification and provisional listening proposals are separate.
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
from ntm_alignment import source_candidates, alignment_signal, coherent_review_proposal
from ntm_consensus import POLICY as CONSENSUS_POLICY, assess_sources, verify_consensus
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


def extract(archive, info, target, budget, reserve=RESERVE, reuse=None):
    if info.file_size > budget:
        raise Attention('selected_member_exceeds_budget')
    target = Path(target)
    space(target.parent, info.file_size, reserve)
    if target.exists():
        if reuse and not target.is_symlink() and reuse['member']==info.filename and reuse['bytes']==info.file_size and reuse['crc32']==f'{info.CRC:08x}' and sha256(target)==reuse['sha256']:
            return dict(reuse,path=str(target))
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
    return source_candidates(rows)


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
                    if len(x)<4: raise Attention('invalid_rpp_tempo_point')
                    try:
                        seconds,bpm,shape=float(x[1]),float(x[2]),int(x[3])
                        # A tempo-only PT row omits the signature; zero means no meter event.
                        signature=int(x[4]) if len(x)>4 else 0
                    except ValueError:
                        raise Attention('invalid_rpp_tempo_point') from None
                    if not math.isfinite(seconds) or not math.isfinite(bpm) or seconds<0 or bpm<=0 or signature<0:
                        raise Attention('invalid_rpp_tempo_point')
                    if shape!=1: raise Attention('rpp_tempo_ramp_requires_review')
                    points.append({'time_seconds':seconds,'bpm':bpm,
                                   'numerator':signature & 65535,'denominator':signature >> 16})
    # A constant project may have an empty tempo envelope and an explicit root TEMPO.
    if not points:
        projects=[n for n in nodes if n['tag']=='REAPER_PROJECT']
        if len(projects)!=1:raise Attention('explicit_rpp_project_required')
        rows=[line.split() for line in projects[0]['lines'] if line.startswith('TEMPO ')]
        rates=[line.split() for line in projects[0]['lines'] if line.startswith('PLAYRATE ')]
        try:
            if len(rows)!=1 or len(rows[0])<4:raise ValueError()
            bpm=float(rows[0][1]);numerator=int(rows[0][2]);denominator=int(rows[0][3])
            if (not math.isfinite(bpm) or bpm<=0 or not 1<=numerator<=255 or
                denominator<=0 or denominator>128 or denominator&(denominator-1)):raise ValueError()
            if len(rates)!=1 or float(rates[0][1])!=1:raise ValueError()
        except (ValueError,IndexError):raise Attention('explicit_constant_rpp_clock_required') from None
        points=[{'time_seconds':0.,'bpm':bpm,'numerator':numerator,'denominator':denominator,
                 'source':'project_tempo_header_without_envelope_points'}]
    return items,points


def constant_rpp_clock(path):
    """Use an explicit constant project clock, with no MIDI conversion or inference."""
    _,points=parse_rpp(Path(path).read_text(encoding='utf-8-sig'))
    if len(points)!=1 or points[0].get('source')!='project_tempo_header_without_envelope_points':
        raise Attention('rpp_without_midi_requires_explicit_constant_clock')
    p=points[0]
    return {'kind':'supplied_rpp_constant_clock_not_qualified_audio_reference',
            'midi_sha256':None,'source_project_sha256':sha256(path),'ticks_per_quarter':960,
            'tick_convention':'Internal quarter index only; not supplied MIDI ticks.',
            'tempo_events':[{'tick':0,'time_seconds':0.,'microseconds_per_quarter':60e6/p['bpm'],'bpm_quarter':p['bpm']}],
            'meter_events':[{'tick':0,'time_seconds':0.,'numerator':p['numerator'],'denominator':p['denominator']}],
            'absolute_timing_verified':False,'evaluation_support_seconds':None,
            'caveat':'Explicit project TEMPO and unity project playback; audio origin still requires alignment.'}


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


def retained_owner_review_manifest(work, expected):
    """Bind every owned temporary input kept for the owner's alignment review."""
    work=Path(work)
    if work.is_symlink() or not work.is_dir():raise Attention('owner_review_inputs_missing')
    if {p.name for p in work.iterdir()} != set(expected):raise Attention('owner_review_input_set_changed')
    manifest={}
    for name in sorted(expected):
        path=work/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file():
            raise Attention('owner_review_input_path_unsafe')
        manifest[name]={'sha256':sha256(path),'bytes':path.stat().st_size}
    return manifest


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


def process(archive_path, master_path, output, *, title, metadata=None, reserve=RESERVE, own_archive=False, resume_from=None, review_policy="legacy-single-source"):
    """Process complete local assets. Caller-owned originals are read-only."""
    if review_policy not in ('owner-review-v1','multisource-v1','legacy-single-source'):
        raise Attention('unknown_review_policy')
    out=Path(output);work=out/'_work';refs=out/'references';work.mkdir(exist_ok=True);refs.mkdir(exist_ok=True)
    if any(refs.iterdir()) and resume_from is None:raise Attention('reference_outputs_exist_choose_new_job')
    previous_assets={r['path']:r for key in ['retained_clock_assets','alignment_source_assets'] for r in (resume_from or {}).get(key,[])}
    owned={p.name for p in work.iterdir()} if own_archive else set()
    allowed_owned={'source.zip','source.zip.transfer.json'}|{Path(r['path']).name for r in (resume_from or {}).get('alignment_source_assets',[])}
    if own_archive and owned-allowed_owned:raise Attention('unexpected_download_work_files')
    start=time.monotonic();report={'version':VERSION,'status':'processing','title':title,'source':metadata or {},
        'input_archive_sha256':sha256(archive_path),'input_master_sha256':sha256(master_path),
        'full_archive_present':True,'archive_all_members_crc_passed':False,'automatic_reference_qualification':False,
        'absolute_timing_verified':False,'target_evaluation_eligible':False,'model_inference_performed':False,
        'timings_seconds':{},'pipeline_sha256':sha256(__file__),
        'alignment_helper_sha256':sha256(Path(__file__).with_name('ntm_alignment.py')),
        'review_template_sha256':sha256(Path(__file__).with_name('ntm_review.html')),
        'review_policy':review_policy,'consensus_helper_sha256':sha256(Path(__file__).with_name('ntm_consensus.py'))}
    if resume_from:
        if report['input_archive_sha256']!=resume_from['input_archive_sha256'] or report['input_master_sha256']!=resume_from['input_master_sha256']:
            raise Attention('resume_input_hash_mismatch')
        if not resume_from.get('archive_all_members_crc_passed'):
            raise Attention('resume_requires_previously_verified_full_archive')
        for asset in previous_assets.values():
            path=Path(asset['path'])
            if not path.is_relative_to(out) or path.is_symlink() or not path.is_file() or sha256(path)!=asset['sha256']:
                raise Attention('resume_reference_or_source_changed')
        if (out/'master.wav').exists() and sha256(out/'master.wav')!=resume_from.get('decode',{}).get('canonical_sha256'):
            raise Attention('resume_canonical_master_changed')
        evidence=out/'evidence'/('attempt-'+uuid.uuid4().hex[:12]);evidence.mkdir(parents=True)
        for filename in ['report.json','failure-diagnosis.json','parser-fix-validation.json']:
            if (out/filename).is_file():shutil.copyfile(out/filename,evidence/filename)
        report['previous_attempt']=str(evidence/'report.json')
        report['resumed_without_network_acquisition']=True
    def checkpoint(stage):
        report['stage']=stage;report['elapsed_seconds']=round(time.monotonic()-start,3);save(out/'report.json',report)
        print(json.dumps({'stage':stage,'elapsed_seconds':report['elapsed_seconds']}),flush=True)
    checkpoint('verify_full_zip')
    try:
        with zipfile.ZipFile(archive_path) as archive:
            rows=archive_rows(archive)
            if resume_from is None:
                if archive.testzip() is not None:raise Attention('archive_crc_failed')
                report['archive_validation']='all_members_crc_checked_this_run'
            else:
                report['archive_validation']='prior_all_member_crc_reused_after_full_archive_sha256_identity_check'
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
                records.append(extract(archive,member,target,MAX_METADATA,reserve,reuse=previous_assets.get(str(target))))
                if suffix in ('.mid','.midi'):
                    try:clocks.append((target,read_tempo_map(target)))
                    except (ValueError,EOFError,OSError):pass
                elif suffix=='.rpp':rpp_paths.append(target)
            report['retained_clock_assets']=records
            if not clocks and not mids:
                clocks=[(path,constant_rpp_clock(path)) for path in rpp_paths]
            if not clocks:raise Attention('explicit_tempo_and_meter_source_required')
            if any(not clocks_agree(clocks[0][1],c) for _,c in clocks[1:]):raise Attention('conflicting_source_clocks_require_review')
            clock_path,clock=clocks[0]
            if clock['midi_sha256'] is not None:
                if (out/'tempo-original.mid').exists() and sha256(out/'tempo-original.mid')!=clock['midi_sha256']:raise Attention('original_midi_copy_changed')
                shutil.copyfile(clock_path,out/'tempo-original.mid');clock_asset='tempo-original.mid';clock_label='원본 MIDI'
            else:
                clock_asset=str(clock_path.relative_to(out));clock_label='원본 REAPER 프로젝트'
            provenance={'kind':clock['kind'],'path':str(clock_path),'sha256':sha256(clock_path),
                        'supplied_midi':clock['midi_sha256'] is not None,'tempo_inferred_from_audio':False}
            report['clock_provenance']=provenance;save(out/'tempo-original.json',clock)
            stems=stem_selection(rows)
            if not stems:raise Attention('no_alignment_source_recognized')
            # Bounded source diversity; unrelated archive content is not extracted.
            stem_assets=[]
            for i,member in enumerate(stems):
                target=work/f'alignment-source-{i}{PurePosixPath(member.filename).suffix.lower()}'
                asset=extract(archive,member,target,MAX_MEMBER,reserve,reuse=previous_assets.get(str(target)));owned.add(target.name)
                asset['basename']=PurePosixPath(member.filename).name;stem_assets.append(asset)
        report['alignment_source_assets']=stem_assets
        checkpoint('decode_master')
        canonical=out/'master.wav'
        if resume_from and canonical.exists():report['decode']=resume_from['decode']
        else:report['decode']=decode_master(master_path,canonical,reserve)
        audio,rate=sf.read(canonical,dtype='float32',always_2d=True)
        if not np.isfinite(audio).all():raise Attention('nonfinite_master_samples')
        checkpoint('estimate_constant_offset')
        audits=[];accepted=None;proposals=[];source_options={}
        for asset in stem_assets:
            source,sr=sf.read(asset['path'],dtype='float32',always_2d=True)
            if not np.isfinite(source).all():raise Attention('nonfinite_source_samples')
            signal,signal_info=alignment_signal(source)
            if signal is None:
                audits.append({'source_member':asset['member'],**signal_info,'qualified_constant_offset':False})
                continue
            try:origin=project_origin(rpp_paths,clock,asset['basename'])
            except Attention:
                audits.append({'source_member':asset['member'],'status':'source_origin_unverified','qualified_constant_offset':False})
                continue
            mix=soxr.resample(audio.mean(axis=1),rate,sr,quality='VHQ')
            config=AlignmentConfig(windows=9,window_seconds=15,maximum_offset_seconds=8,
                                   minimum_correlation=.2,minimum_agreeing_windows=7,maximum_frame_spread=round(sr*.001))
            try:result=audit(mix,signal,sr,config)
            except ValueError:continue
            result.update(source_member=asset['member'],source_sample_rate=sr,source_sha256=asset['sha256'],project_origin=origin,signal=signal_info)
            audits.append(result)
            print(json.dumps({'stage':'source_check','source':asset['basename'],'eligible_windows':result['eligible_windows'],'automatic_gate_passed':result['qualified_constant_offset']}),flush=True)
            candidate={'source_duration_seconds':len(source)/sr,
                       'project_duration_seconds':origin['item']['position']+origin['item']['length'],
                       'source_rate':sr,'audit':result}
            source_options[asset['member']]=candidate
            if result['qualified_constant_offset']:
                if accepted is None:
                    accepted={**candidate,'offset_seconds':-result['stem_minus_mix_frames']/sr-origin['file_zero_in_project_seconds'],
                              'automatic_gate_passed':True,'basis':'fixed_waveform_gate'}
                if review_policy=='legacy-single-source':break
            proposal=coherent_review_proposal(result,sr)
            if proposal:
                proposals.append({**candidate,'offset_seconds':-proposal['stem_minus_mix_frames']/sr-origin['file_zero_in_project_seconds'],
                                  'automatic_gate_passed':False,'basis':'coherent_waveform_listening_proposal','proposal':proposal})
        report['audits']=audits
        report['manual_review_proposals']=proposals
        if accepted is None and proposals:
            accepted=max(proposals,key=lambda p:(p['proposal']['consistent_windows'],p['proposal']['median_correlation']))
            report['proposal_offset_spread_seconds']=max(p['offset_seconds'] for p in proposals)-min(p['offset_seconds'] for p in proposals)
        if review_policy in ('owner-review-v1','multisource-v1'):
            initial=assess_sources(audits);verification=[]
            if initial['passed_initial']:
                checkpoint('verify_source_consensus_on_additional_windows')
                for member in initial['supporting_sources']:
                    asset=next(a for a in stem_assets if a['member']==member)
                    source,sr=sf.read(asset['path'],dtype='float32',always_2d=True);signal,_=alignment_signal(source)
                    origin=source_options[member]['audit']['project_origin']
                    mix=soxr.resample(audio.mean(axis=1),rate,sr,quality='VHQ')
                    config=AlignmentConfig(windows=CONSENSUS_POLICY['verification_windows'],window_seconds=15,
                        maximum_offset_seconds=8,minimum_correlation=CONSENSUS_POLICY['verification_minimum_correlation'],
                        minimum_agreeing_windows=CONSENSUS_POLICY['verification_minimum_windows'],maximum_frame_spread=round(sr*.001))
                    check=audit(mix,signal,sr,config)
                    check.update(source_member=member,source_sample_rate=sr,source_sha256=asset['sha256'],project_origin=origin)
                    verification.append(check)
            consensus=verify_consensus(initial,verification);report['source_consensus']=consensus
            if consensus['passed']:
                basis=source_options[consensus['supporting_sources'][0]]
                accepted={**basis,'offset_seconds':consensus['offset_seconds'],'automatic_gate_passed':True,'basis':'multisource-v1'}
            elif accepted is not None:
                accepted={**accepted,'source_gate_passed':accepted['automatic_gate_passed'],
                          'automatic_gate_passed':False,'basis':'source_candidate_pending_consensus_review'}
        if accepted is None:raise Attention('no_supported_alignment_or_coherent_review_proposal')
        offset=accepted['offset_seconds'];report['alignment']=accepted
        auto_accepted=review_policy=='multisource-v1' and accepted['automatic_gate_passed']
        checkpoint('write_aligned_map_and_listening_files')
        quarters,pulses=clock_events(clock,accepted['project_duration_seconds'])
        aligned={'kind':'automatically_aligned_producer_map_for_listening_review','master_sha256':report['decode']['canonical_sha256'],
            'midi_sha256':clock['midi_sha256'],'clock_provenance':provenance,'transform':'t_master = t_project + offset_seconds','offset_seconds':offset,'time_scale':1.,
            'tempo_events':[dict(e,master_seconds=e['time_seconds']+offset) for e in clock['tempo_events']],
            'meter_events':[dict(e,master_seconds=e['time_seconds']+offset) for e in clock['meter_events']],
            'quarter_events':[dict(e,master_seconds=e['source_seconds']+offset,master_frame=math.floor((e['source_seconds']+offset)*rate+.5)) for e in quarters],
            'absolute_timing_verified':False,'target_evaluation_eligible':False,'human_alignment_accepted':False,
            'automatic_alignment_gate_passed':accepted['automatic_gate_passed'],'alignment_basis':accepted['basis'],
            'mapped_source_end_seconds':accepted['project_duration_seconds']+offset,
            'negative_events':'Retained as preceding clock context, not clamped to audio zero.'}
        if auto_accepted:aligned.update(kind='producer_map_with_operational_automatic_acceptance',automatic_alignment_accepted=True,alignment_acceptance='acceptance.json')
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
        save(out/'review-data.json',{'title':title,'sample_rate':rate,'sample_frames':len(audio),
            'duration_seconds':len(audio)/rate,'master_sha256':report['decode']['canonical_sha256'],
            'midi_sha256':clock['midi_sha256'],'clock_provenance':provenance,'clock_asset':clock_asset,'clock_label':clock_label,'offset_seconds':offset,'master_gain':master_gain,
            'automatic_gate_passed':accepted['automatic_gate_passed'],'automatic_alignment_accepted':auto_accepted,'alignment_basis':accepted['basis'],
            'tempo_changes':aligned['tempo_events'][1:],'pulses':pulses,
            'absolute_timing_verified':False,'target_evaluation_eligible':False})
        shutil.copyfile(Path(__file__).with_name('ntm_review.html'),out/'review.html')
        snapshot=out/'source-snapshot';snapshot.mkdir(exist_ok=True)
        for name in ['ntm_full_pipeline.py','ntm_alignment.py','ntm_consensus.py','ntm_review.html','audit_source_alignment.py',
                     'build_alignment_review.py','prepare_multitrack_sample.py','midi_reference.py','inspect_inputs.py']:
            shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
        if sha256(archive_path)!=report['input_archive_sha256'] or sha256(master_path)!=report['input_master_sha256']:
            raise Attention('input_changed_during_processing')
        if auto_accepted:
            save(out/'acceptance.json',{'schema_version':1,'title':title,'status':'automatically_accepted_alignment',
                'accepted_by':'multisource-v1-policy','recorded_at':datetime.now(timezone.utc).isoformat(),
                'offset_seconds':offset,'transform':'t_master = t_project + offset_seconds','time_scale':1.,
                'operational_alignment_accepted':True,'human_alignment_accepted':False,'automatic_alignment_gate_passed':True,
                'absolute_timing_verified':False,'target_evaluation_eligible':False,'strict_timing_error_bound_ms':None,
                'clock_provenance':provenance,'source_consensus':report['source_consensus'],
                'artifacts':{n:{'sha256':sha256(out/n),'bytes':(out/n).stat().st_size} for n in ['master.wav','tempo-aligned.json','click-aligned.wav','listen-aligned.wav']},
                'qualification_note':'Operational source alignment accepted under experimental cross-source checks; not original-click or strict beat reference certification.'})
            report['automatic_alignment_accepted']=True;report['human_alignment_accepted']=False
        report['retained_outputs']={p.name:{'sha256':sha256(p),'bytes':p.stat().st_size} for p in out.iterdir() if p.is_file() and p.name not in ('report.json','.pipeline-owner.json')}
        if review_policy=='owner-review-v1':
            report['retained_owner_review_inputs']=retained_owner_review_manifest(work,owned)
            report['deleted_temporary_files']=[]
            report['temporary_inputs_preserved']=True
            report['automatic_alignment_accepted']=False
            report['human_alignment_accepted']=False
            report['status']='ready_for_owner_alignment_review'
        else:
            # Save complete verified output evidence before deleting this job's temporary assets.
            report['status']='verified_outputs_pending_cleanup';checkpoint('finalize_review_artifacts')
            if accepted['automatic_gate_passed']:
                report['deleted_temporary_files']=cleanup_owned(work,owned)
                report['status']='automatically_accepted_alignment' if auto_accepted else 'ready_for_listening_review'
            else:
                report['deleted_temporary_files']=[]
                report['temporary_inputs_preserved']=True
                report['status']='ready_for_manual_alignment_review'
        report['timings_seconds']['total_processing']=round(time.monotonic()-start,3)
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
        if report_path.exists() and json.loads(report_path.read_text()).get('status') in ('ready_for_owner_alignment_review','ready_for_listening_review','ready_for_manual_alignment_review','user_accepted_alignment','automatically_accepted_alignment'):
            r=json.loads(report_path.read_text())
            if r['status']=='ready_for_owner_alignment_review':
                expected=r.get('retained_owner_review_inputs')
                if not isinstance(expected,dict) or not expected or retained_owner_review_manifest(out/'_work',expected)!=expected:
                    raise Attention('owner_review_input_integrity_changed')
            if all((out/name).is_file() and sha256(out/name)==v['sha256'] for name,v in r['retained_outputs'].items()):
                return {'status':'already_complete','output':str(out)}
        if args.resume and report_path.exists():
            owner=out/'.pipeline-owner.json'
            if not owner.exists() or json.loads(owner.read_text()).get('pipeline_version')!=VERSION:
                raise Attention('resume_requires_owned_job')
            previous=json.loads(report_path.read_text())
            if previous.get('status')!='needs_attention' or (out/'acceptance.json').exists() or (out/'click-aligned.wav').exists():
                raise Attention('resume_processing_requires_unaccepted_failed_job')
            archive=out/'_work/source.zip'
            masters=[p for p in out.glob('master-original.*') if p.suffix.lower() in ('.mp3','.wav','.flac','.m4a')]
            if len(masters)!=1 or not archive.is_file():raise Attention('resume_processing_inputs_missing')
            result=process(archive,masters[0],out,title=args.title or previous['title'],metadata=previous.get('source'),own_archive=True,resume_from=previous,review_policy=getattr(args,'review_policy','owner-review-v1'))
            result['output']=str(out);return result
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
        report=process(archive,master,out,title=args.title or metadata.get('title') or args.slug,metadata=metadata,own_archive=own_archive,review_policy=getattr(args,'review_policy','owner-review-v1'))
        report['output']=str(out);return report
    finally:
        if private_plan is not None and private_plan.exists():private_plan.unlink()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slug',required=True);p.add_argument('--title')
    p.add_argument('--output-root',default='/mnt/d/NailTheMix/processed')
    p.add_argument('--local-master');p.add_argument('--local-archive')
    p.add_argument('--review-policy',choices=['owner-review-v1','multisource-v1','legacy-single-source'],default='owner-review-v1',help='Owner review retains the Master, full ZIP, and extracted sources; older reproduction policies may delete owned inputs')
    p.add_argument('--archive-index',type=int,help='Required only when the provider offers distinct non-mirror packages')
    p.add_argument('--resume',action='store_true',help='Explicitly resume interrupted acquisition or an unaccepted failed job using hash-verified existing inputs')
    args=p.parse_args()
    try:
        r=run(args);print(json.dumps({k:r[k] for k in ['status','reason','output','timings_seconds'] if k in r},ensure_ascii=False,indent=2))
        return 0 if r['status'] in ('ready_for_owner_alignment_review','ready_for_listening_review','ready_for_manual_alignment_review','already_complete','automatically_accepted_alignment') else 2
    except Exception as error:
        # Uncontrolled exceptions may contain authentication URLs: suppress their message/traceback.
        reason=str(error) if isinstance(error,Attention) else type(error).__name__
        print(json.dumps({'status':'needs_attention','reason':reason}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
