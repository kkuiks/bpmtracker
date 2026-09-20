"""Inspect public creator folder listings and acquire explicitly selected assets.

Only public URLs are used, with bounded reads, recorded source hashes and no
recursive audio download. Assets remain in ignored data/. This does not certify
recording-to-click provenance, publication rights or musical annotation quality.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import urllib.parse
import urllib.request


def _varint(data, offset):
    value=0
    for shift in range(0,70,7):
        if offset>=len(data):raise ValueError('truncated protobuf varint')
        byte=data[offset];offset+=1;value|=(byte&127)<<shift
        if not byte&128:return value,offset
    raise ValueError('oversized protobuf varint')


def _length_fields(data):
    offset=0;result=[]
    while offset<len(data):
        tag,offset=_varint(data,offset)
        if tag>>3==0:raise ValueError('invalid protobuf field')
        wire=tag&7
        if wire==0:
            _,offset=_varint(data,offset)
        elif wire in (1,5):
            offset+=8 if wire==1 else 4
        elif wire==2:
            length,offset=_varint(data,offset)
            if offset+length>len(data):raise ValueError('truncated protobuf bytes')
            result.append(data[offset:offset+length]);offset+=length
        else:raise ValueError('unsupported protobuf wire')
        if offset>len(data):raise ValueError('truncated protobuf field')
    return result


def _public_urls(data, depth=0):
    if depth>14:return set()
    urls=set()
    try:fields=_length_fields(data)
    except ValueError:return urls
    for field in fields:
        if field.startswith(b'https://www.dropbox.com/scl/'):
            try:
                text=field.decode('utf-8')
                if not any(ord(c)<32 for c in text):urls.add(text)
            except UnicodeDecodeError:pass
        else:urls.update(_public_urls(field,depth+1))
    return urls


def public_folder_entries(html):
    """Decode public listing data embedded in the downloaded page, no private API."""
    urls=set()
    for key,value in re.findall(r'registerStreamedPrefetch\("([A-Za-z0-9+/=]+)", "([A-Za-z0-9+/=]+)"',html):
        if b'FolderEntriesProps' in base64.b64decode(key):
            urls.update(_public_urls(base64.b64decode(value)))
    result=[]
    for url in sorted(urls):
        parts=urllib.parse.urlsplit(url)
        name=urllib.parse.unquote(parts.path.rsplit('/',1)[-1])
        suffix=Path(name).suffix.lower()
        result.append({'name':name,'url':url,'kind':'file' if suffix in ('.wav','.mid','.midi','.rtf','.txt','.mp3','.flac') else 'folder'})
    if not result:
        raise ValueError('no public folder entries found; upstream listing format may have changed')
    return result


def download(url, output, *, max_bytes=250_000_000):
    output=Path(output)
    if output.exists() or output.with_suffix(output.suffix+'.provenance.json').exists():
        raise ValueError('target already exists; preserve acquired files')
    if max_bytes<=0:raise ValueError('positive byte limit required')
    parts=urllib.parse.urlsplit(url)
    if parts.scheme!='https' or parts.username or parts.password:
        raise ValueError('public HTTPS URLs without credentials only')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(output.suffix+'.partial')
    if temporary.exists():raise ValueError('partial target exists; choose a fresh output')
    request=urllib.request.Request(url,headers={'User-Agent':'Joljak reference audit (public educational assets)'})
    digest=hashlib.sha256();count=0
    try:
        with urllib.request.urlopen(request,timeout=45) as response, temporary.open('xb') as handle:
            content_length=response.headers.get('Content-Length')
            if content_length and int(content_length)>max_bytes:
                raise ValueError('declared asset exceeds byte limit')
            content_type=response.headers.get('Content-Type')
            while True:
                block=response.read(min(1024*1024,max_bytes-count+1))
                if not block:break
                count+=len(block)
                if count>max_bytes:raise ValueError('asset exceeds byte limit')
                handle.write(block);digest.update(block)
        temporary.rename(output)
    except BaseException:
        # Only this call's newly created partial file is removed on failed fetch.
        if temporary.exists():temporary.unlink()
        raise
    metadata={'source_url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),
              'bytes':count,'sha256':digest.hexdigest(),'content_type':content_type,
              'declared_content_length':int(content_length) if content_length else None,
              'http_length_verified':count==int(content_length) if content_length else None,
              'maximum_allowed_bytes':max_bytes,'path':str(output),
              'source_authorization':'publicly accessible; consult creator usage statement separately',
              'public_redistribution_authorized':False}
    output.with_suffix(output.suffix+'.provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if content_length and count!=int(content_length):
        raise ValueError(f'incomplete HTTP body preserved at {output}; not an admitted asset')
    if output.suffix.lower()=='.wav':
        validate_riff_size(output)
    return metadata


def validate_riff_size(path):
    path=Path(path)
    with path.open('rb') as handle:header=handle.read(12)
    if len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE':
        raise ValueError('ordinary RIFF/WAVE required for this acquisition audit')
    expected=struct.unpack_from('<I',header,4)[0]+8
    actual=path.stat().st_size
    if actual!=expected:
        raise ValueError(f'RIFF file incomplete or inconsistent: actual={actual}, declared={expected}; preserve and review')
    return expected


def recover_wav_tail(path):
    """Recover a short public transfer, preserving its prior bytes and provenance.

    Requires exact 206 Content-Range agreement with the source RIFF header. This
    cannot be used to invent audio, shift it, or repair an inconsistent publisher
    file. A complete-but-wrong header is rejected, not silently rewritten.
    """
    path=Path(path)
    with path.open('rb') as handle:header=handle.read(12)
    if len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE':raise ValueError('RIFF/WAVE required')
    expected=struct.unpack_from('<I',header,4)[0]+8;actual=path.stat().st_size
    if actual==expected:return {'status':'already_complete','path':str(path),'bytes':actual}
    if not 0 < actual < expected <= 200_000_000:raise ValueError('unsupported recovery size')
    provenance_path=path.with_suffix(path.suffix+'.provenance.json')
    original=json.loads(provenance_path.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest()!=original['sha256']:raise ValueError('incomplete artifact changed since acquisition')
    url=original['source_url'];pieces=[];position=actual;range_requests=[]
    for _ in range(8):
        if position==expected:break
        request=urllib.request.Request(url,headers={'Range':f'bytes={position}-{expected-1}'})
        with urllib.request.urlopen(request,timeout=45) as response:
            if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {position}-{expected-1}/{expected}':
                raise ValueError('server did not certify exact missing range and total size')
            part=response.read(expected-position+1)
        if len(part)>expected-position:raise ValueError('server returned extra bytes outside requested range')
        range_requests.append({'start':position,'end':expected-1,'received_bytes':len(part)})
        pieces.append(part);position+=len(part)
    tail=b''.join(pieces)
    if len(tail)!=expected-actual:
        raise ValueError(f'recovery range incomplete after bounded retries: {len(tail)}/{expected-actual}')
    backup=path.with_suffix(path.suffix+'.incomplete-transfer')
    backup_provenance=backup.with_suffix(backup.suffix+'.provenance.json')
    repaired=path.with_suffix(path.suffix+'.repaired')
    if any(p.exists() for p in (backup,backup_provenance,repaired)):raise ValueError('recovery target exists; preserve earlier attempt')
    shutil.copyfile(path,repaired)
    with repaired.open('ab') as handle:handle.write(tail)
    validate_riff_size(repaired)
    digest=hashlib.sha256(repaired.read_bytes()).hexdigest()
    path.rename(backup);provenance_path.rename(backup_provenance);repaired.rename(path)
    metadata={**original,'path':str(path),'bytes':expected,'sha256':digest,
              'completed_utc':datetime.now(timezone.utc).isoformat(),
              'completion_validation':'RIFF size and exact HTTP 206 missing byte range agree',
              'recovery_range_requests':range_requests,
              'recovered_tail_bytes':len(tail),'recovered_tail_sha256':hashlib.sha256(tail).hexdigest(),
              'incomplete_transfer_preserved_at':str(backup),'http_length_verified':True,
              'declared_content_length':expected}
    provenance_path.write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def creator_midi_clock(path, duration_seconds):
    """Interpret the supplied MIDI timebase without requiring dummy note events.

    Every explicit signature event is retained. A repeated signature can reset
    the bar count (e.g. after a pickup); such resets are disclosed, not erased.
    No inferred audio offset or default musical tempo/meter is inserted.
    """
    import mido
    import numpy as np
    if not np.isfinite(duration_seconds) or duration_seconds<=0:
        raise ValueError('positive finite audio duration required')
    midi=mido.MidiFile(path)
    if midi.type not in (0,1) or midi.ticks_per_beat<=0:
        raise ValueError('synchronous PPQ MIDI required')
    tick=0;tempo=[];meter=[];markers=[]
    for event in mido.merge_tracks(midi.tracks):
        tick+=event.time
        if event.type=='set_tempo':tempo.append((tick,event.tempo))
        elif event.type=='time_signature':meter.append((tick,event.numerator,event.denominator))
        elif event.type in ('marker','cue_marker'):markers.append((tick,event.text))
    if not tempo or tempo[0][0]!=0:
        raise ValueError('explicit initial creator tempo required')
    if any(value<=0 for _,value in tempo) or any(num<=0 or den<=0 for _,num,den in meter):
        raise ValueError('positive explicit tempo and meter required')
    unique=[]
    for item in tempo:
        if unique and item[0]==unique[-1][0]:
            if item[1]!=unique[-1][1]:raise ValueError('conflicting simultaneous tempo')
            continue
        if unique and item[1]==unique[-1][1]:continue
        unique.append(item)
    tempo=unique
    tempo_ticks=np.array([e[0] for e in tempo],dtype=float)
    rates=np.array([e[1]/1e6/midi.ticks_per_beat for e in tempo])
    origins=np.r_[0.,np.cumsum(np.diff(tempo_ticks)*rates[:-1])]
    def seconds(t):
        values=np.asarray(t,dtype=float)
        indices=np.searchsorted(tempo_ticks,values,side='right')-1
        return origins[indices]+(values-tempo_ticks[indices])*rates[indices]
    end_tick=tempo_ticks[-1]+(duration_seconds-origins[-1])/rates[-1]
    # The last declared tempo can occur beyond this asset's end.
    if duration_seconds < origins[-1]:
        idx=max(0,int(np.searchsorted(origins,duration_seconds,side='right')-1))
        end_tick=tempo_ticks[idx]+(duration_seconds-origins[idx])/rates[idx]
    quarters=np.arange(0,max(0,end_tick)+1e-9,midi.ticks_per_beat)
    down=[];resets=[]
    for i,(start,num,den) in enumerate(meter):
        stop=meter[i+1][0] if i+1<len(meter) else end_tick+1e-9
        if i and abs((start-meter[i-1][0])/(midi.ticks_per_beat*4*meter[i-1][1]/meter[i-1][2])-round((start-meter[i-1][0])/(midi.ticks_per_beat*4*meter[i-1][1]/meter[i-1][2])))>1e-8:
            resets.append({'tick':start,'source_seconds':float(seconds(start)),
                           'reason':'Explicit signature event is not on previous signature bar grid; preserve as creator bar-reset candidate.'})
        down.extend(np.arange(start,min(stop,end_tick+1e-9),midi.ticks_per_beat*4*num/den).tolist())
    return {'kind':'creator_supplied_performance_midi_map','ticks_per_quarter':midi.ticks_per_beat,
            'source_origin_shift_seconds':0,'alignment_fitted_to_predictions':False,
            'tempo_events':[{'tick':int(t),'time_seconds':float(seconds(t)),
                             'microseconds_per_quarter':v,'bpm_quarter':60e6/v} for t,v in tempo],
            'meter_events':[{'tick':int(t),'time_seconds':float(seconds(t)),
                             'numerator':num,'denominator':den} for t,num,den in meter],
            'markers':[{'tick':int(t),'time_seconds':float(seconds(t)),'text':text} for t,text in markers],
            'beats_seconds':seconds(quarters).tolist(),
            'quarter_indices':(quarters/midi.ticks_per_beat).tolist(),
            'downbeats_seconds':seconds(np.unique(down)).tolist() if meter and meter[0][0]==0 else None,
            'bar_reset_candidates':resets,
            'tempo_representation':'Discrete MIDI tempo events; original DAW ramp shape is not inferred.',
            'meter_reference_status':'creator_explicit_events; acoustic accent validation not performed',
            'downbeat_label_status':('creator_bar_grid_with_provisional_pickup_resets' if resets
                                     else 'creator_declared_bar_grid_acoustic_accents_unverified'),
            'recorded_to_this_click_status':'not_explicitly_attested_by_creator; performance_map_pair_provided'}


def click_onsets(path):
    """Fixed-threshold click waveform onset diagnostics, independent of MIDI/model."""
    import numpy as np
    import soundfile as sf
    info=sf.info(path)
    # Millisecond block peaks keep memory small and disclose onset quantization.
    hop=max(1,round(info.samplerate*.001));peaks=[]
    for block in sf.blocks(path,blocksize=hop*4096,dtype='float32',always_2d=True):
        mono=np.max(abs(block),axis=1)
        if len(mono)%hop:mono=np.pad(mono,(0,hop-len(mono)%hop))
        peaks.extend(np.max(mono.reshape(-1,hop),axis=1).tolist())
    peaks=np.array(peaks);maximum=float(max(peaks)) if len(peaks) else 0.
    if maximum==0:raise ValueError('reference click is silent')
    active=np.flatnonzero(peaks>=maximum*.15)
    starts=active[np.r_[True,np.diff(active)>max(1,round(.05*info.samplerate/hop))]]
    return {'times_seconds':(starts*hop/info.samplerate).tolist(),
            'method':'1ms peak envelope, fixed 15% global peak, 50ms inactive gap',
            'onset_resolution_seconds':hop/info.samplerate,'peak_amplitude':maximum,
            'source_frames':info.frames,'sample_rate':info.samplerate}


def prepare_forestry(corpus, output_dir, songs=None):
    """Build a separate pilot catalog only after click/map consistency checks."""
    import numpy as np
    import soundfile as sf
    from grid_metrics import nearest_event_diagnostics
    corpus=Path(corpus);output_dir=Path(output_dir)
    if output_dir.exists():raise ValueError('new preparation output directory required')
    manifest=json.loads((corpus/'selected-audio-manifest.json').read_text())
    rows=[];references=[];audits=[]
    digest=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    available={e['song'] for e in manifest['assets']}
    if songs is not None and not set(songs)<=available:
        raise ValueError('requested song absent from pre-inference selection manifest')
    for slug in sorted(available if songs is None else set(songs)):
        folder=corpus/slug
        music=next(p for p in folder.glob('*.wav') if p.name.startswith('INST'))
        click=next(p for p in folder.glob('*.wav') if p.name.startswith('CLICK'))
        midi=next(folder.glob('*.mid'))
        music_info,click_info=sf.info(music),sf.info(click)
        validate_riff_size(music);validate_riff_size(click)
        if (music_info.frames,music_info.samplerate)!=(click_info.frames,click_info.samplerate):
            raise ValueError(f'{slug}: click and music source duration/rate differ; origin not inferred')
        ref=creator_midi_clock(midi,music_info.duration)
        detected=click_onsets(click)
        if len(detected['times_seconds'])<4:raise ValueError(f'{slug}: insufficient reference clicks')
        click_start,click_end=detected['times_seconds'][0],detected['times_seconds'][-1]
        # Compare the common observable click span, and retain excluded edge
        # counts explicitly. No time shift, rescaling or model-based selection.
        rawbeats=np.array(ref['beats_seconds'])
        inside=(rawbeats>=click_start-.07)&(rawbeats<=click_end+.07)
        click_scores={str(t):nearest_event_diagnostics(rawbeats[inside],detected['times_seconds'],t)
                      for t in (.02,.07)}
        first=None;last=None;frame=0
        for block in sf.blocks(music,blocksize=262144,dtype='float32',always_2d=True):
            support=np.flatnonzero(np.any(block!=0,axis=1))
            if len(support):
                if first is None:first=frame+int(support[0])
                last=frame+int(support[-1])+1
            frame+=len(block)
        if first is None:raise ValueError(f'{slug}: silent music asset')
        music_support=[first/music_info.samplerate,last/music_info.samplerate]
        support=[max(music_support[0],click_start-.02),min(music_support[1],click_end+.02)]
        if support[1]<=support[0]:raise ValueError(f'{slug}: no shared music/click support')
        ref.update({'evaluation_support_seconds':support,
                    'evaluation_support_policy':'Intersection of exact nonzero music span and audible reference-click span, with fixed 20ms click-onset margin; source origin and full map retained.',
                    'music_nonzero_support_seconds':music_support,
                    'click_observable_span_seconds':[click_start,click_end],
                    'outside_click_span_status':'creator map declared but no audible click verification; not silently scored as verified',
                    'source_audio_sha256':digest(music),
                    'midi_sha256':digest(midi),'reference_click_sha256':digest(click),
                    'music_asset_role':'creator-supplied INST instrumental asset; not independently certified full released master',
                    'source_alignment':'creator shared-file origin; no inferred offset; click/MIDI diagnostic below',
                    'annotation_caveat':'Creator performance map and paired reference click, not an explicit statement that recording was made to this click.',
                    'click_map_validation':click_scores})
        qualified=click_scores['0.02']['recall']>=.98
        # Click can include eighth-note subdivisions; precision is disclosed and
        # does not silently coerce the MIDI quarter unit to click onset density.
        row={'id':'forestry_'+slug,'dataset':'forestry_producer_pilot',
             'genre':'creator_supplied_studio_instrumental',
             'input':{'kind':'audio','path':str(music),'sha256':ref['source_audio_sha256']},
             'reference':{'path':str(output_dir/'labels'/f'{slug}.json')},
             'duration_seconds':music_info.duration,'sample_rate':music_info.samplerate,
             'sample_frames':music_info.frames,'group_id':manifest['artist_group'],
             'model_overlap':'not audited; creator/composition overlap with training data unknown',
             'target_scope':'paired creator performance MIDI/click; recording-to-click not explicitly attested',
             'qualification_status':'click_map_consistent_without_offset' if qualified else 'reference_alignment_requires_review',
             'evaluation_admission':'creator_clock_within_declared_support' if qualified else 'diagnostic_only_pending_alignment_review',
             'role':'development_reference_pilot_not_independent_artist_test',
             'reference_click_path':str(click),'reference_midi_path':str(midi),
             'tempo_event_count':len(ref['tempo_events']),'meter_event_count':len(ref['meter_events']),
             'downbeat_labels':ref['downbeats_seconds'] is not None,
             'source_page':'https://www.futureofforestry.com/multitracks-stems',
             'analysis_input_role':'single creator-labeled INST instrumental asset; full released mix membership unverified',
             'reference_input_separation':'CLICK and MIDI are evaluation-only; neither is mixed into analysis input',
             'redistribution':'creator prohibits posting tracks online; local educational analysis only'}
        rows.append(row);references.append(ref)
        audits.append({'id':row['id'],'click_detection':detected,'click_map_scores':click_scores,
                       'quarter_events_outside_observable_click_span':int((~inside).sum()),
                       'quarter_events_inside_observable_click_span':int(inside.sum()),
                       'same_source_frame_count_and_rate':True,'time_shift_applied':0,
                       'midi_source':str(midi),'music_source':str(music),
                       'bar_reset_candidates':ref['bar_reset_candidates']})
    (output_dir/'labels').mkdir(parents=True)
    for row,ref in zip(rows,references):
        path=Path(row['reference']['path']);path.write_text(json.dumps(ref,indent=2)+'\n')
        row['reference']['sha256']=digest(path)
    report={'schema_version':1,'dataset':'forestry_producer_pilot',
            'role':'development_creator_reference_pilot_not_heldout_artist_test',
            'selection_manifest_sha256':digest(corpus/'selected-audio-manifest.json'),
            'importer_sha256':digest(__file__),'source_origin_policy':'unaltered file sample zero; no oracle alignment',
            'tracks':rows,'excluded':[]}
    (output_dir/'catalog.json').write_text(json.dumps(report,indent=2)+'\n')
    (output_dir/'reference-audit.json').write_text(json.dumps({'schema_version':1,'tracks':audits},indent=2)+'\n')
    return {'catalog':str(output_dir/'catalog.json'),'track_count':len(rows),
            'statuses':{r['id']:r['qualification_status'] for r in rows}}


def combine_catalogs(paths, output_dir):
    """Join disjoint pilot subsets without rewriting already frozen references."""
    output_dir=Path(output_dir)
    if output_dir.exists():raise ValueError('new combined catalog directory required')
    rows=[];sources=[];ids=set()
    for path in paths:
        path=Path(path);catalog=json.loads(path.read_text())
        sources.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for row in catalog['tracks']:
            if row['id'] in ids:raise ValueError(f'duplicate track ID across catalogs: {row["id"]}')
            label=Path(row['reference']['path'])
            if hashlib.sha256(label.read_bytes()).hexdigest()!=row['reference']['sha256']:
                raise ValueError('reference hash changed since subset preparation')
            ids.add(row['id']);rows.append(row)
    output_dir.mkdir(parents=True)
    combined={'schema_version':1,'dataset':'forestry_producer_pilot',
              'role':'development_creator_reference_pilot_not_heldout_artist_test',
              'source_catalogs':sources,'reference_files_reused_unchanged':True,
              'tracks':rows,'excluded':[]}
    (output_dir/'catalog.json').write_text(json.dumps(combined,indent=2)+'\n')
    return {'catalog':str(output_dir/'catalog.json'),'track_count':len(rows)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    fetch=sub.add_parser('fetch');fetch.add_argument('url');fetch.add_argument('--output',required=True,type=Path)
    fetch.add_argument('--max-bytes',type=int,default=250_000_000)
    listing=sub.add_parser('list-folder');listing.add_argument('html',type=Path)
    listing.add_argument('--output',type=Path)
    prepare=sub.add_parser('prepare-forestry');prepare.add_argument('--corpus',required=True,type=Path)
    prepare.add_argument('--output-dir',required=True,type=Path)
    prepare.add_argument('--song',action='append',help='prepare an already selected song as soon as its assets arrive')
    recover=sub.add_parser('recover-wav-tail');recover.add_argument('path',type=Path)
    combine=sub.add_parser('combine-catalogs');combine.add_argument('--catalogs',required=True,nargs='+',type=Path)
    combine.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    if args.command=='fetch':
        print(json.dumps(download(args.url,args.output,max_bytes=args.max_bytes),indent=2))
    elif args.command=='prepare-forestry':
        print(json.dumps(prepare_forestry(args.corpus,args.output_dir,args.song),indent=2))
    elif args.command=='recover-wav-tail':
        print(json.dumps(recover_wav_tail(args.path),indent=2))
    elif args.command=='combine-catalogs':
        print(json.dumps(combine_catalogs(args.catalogs,args.output_dir),indent=2))
    else:
        result={'schema_version':1,'source_html':str(args.html),
                'source_html_sha256':hashlib.sha256(args.html.read_bytes()).hexdigest(),
                'entries':public_folder_entries(args.html.read_text())}
        text=json.dumps(result,indent=2)+'\n'
        if args.output:
            with args.output.open('x') as handle:handle.write(text)
        else:print(text)


if __name__=='__main__':
    main()
