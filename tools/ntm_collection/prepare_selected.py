"""Extract acquired clocks and prepare audio for interactive alignment review.

An initial offset proposal uses one corresponding source-stem segment. Review
assets retain the original Master geometry and the supplied source clock.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,math,shlex,subprocess,zipfile
import xml.etree.ElementTree as ET
import mido
import numpy as np
import soundfile as sf
if __package__:
    from .storage import bind_selected, note_stage, assert_candidate_allowed, library_root, SAMPLES
else:
    from storage import bind_selected, note_stage, assert_candidate_allowed, library_root, SAMPLES


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.partial')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def midi_clock(path):
    source=mido.MidiFile(path);tick=0;seconds=0.;us=500000;tempos=[];meters=[];smpte=[]
    for msg in mido.merge_tracks(source.tracks):
        tick+=msg.time;seconds+=mido.tick2second(msg.time,source.ticks_per_beat,us);quarter=tick/source.ticks_per_beat
        if msg.type=='set_tempo':
            us=msg.tempo;event=dict(quarter=quarter,project_seconds=seconds,bpm=60e6/us,microseconds_per_quarter=us)
            if tempos and tempos[-1]['quarter']==quarter:tempos[-1]=event
            else:tempos.append(event)
        if msg.type=='time_signature':
            event=dict(quarter=quarter,project_seconds=seconds,numerator=msg.numerator,denominator=msg.denominator)
            if meters and meters[-1]['quarter']==quarter:meters[-1]=event
            else:meters.append(event)
        if msg.type=='smpte_offset':
            smpte.append(dict(quarter=quarter,hours=msg.hours,minutes=msg.minutes,seconds=msg.seconds,
                frames=msg.frames,sub_frames=msg.sub_frames,frame_rate=msg.frame_rate,
                absolute_seconds=msg.hours*3600+msg.minutes*60+msg.seconds+(msg.frames+msg.sub_frames/100)/msg.frame_rate))
    if not tempos:return None
    return dict(clock_kind='supplied_midi',source_file=path.name,source_sha256=digest(path),ppq=source.ticks_per_beat,
                tempo_events=tempos,meter_events=meters,smpte_offset_events=smpte,project_end_seconds=seconds,project_end_quarter=tick/source.ticks_per_beat,
                initial_clock_explicit_at_zero=bool(meters) and tempos[0]['quarter']==meters[0]['quarter']==0,
                implicit_leading_decoder_tempo_microseconds_per_quarter=500000 if tempos[0]['quarter']>0 else None)


def project_time_at(clock,quarter):
    event=next((e for e in reversed(clock['tempo_events']) if e['quarter']<=quarter+1e-9),None)
    if event is None:
        return quarter*clock['implicit_leading_decoder_tempo_microseconds_per_quarter']/1e6
    return event['project_seconds']+(quarter-event['quarter'])*60/event['bpm']


def studio_one_meter(path):
    with zipfile.ZipFile(path) as archive:
        if 'Song/song.xml' not in archive.namelist():return []
        document=archive.read('Song/song.xml').decode('utf-8-sig')
        # Studio One uses x:id without declaring x; bind it for the XML reader.
        if 'xmlns:x=' not in document:
            document=document.replace('<Song ', '<Song xmlns:x="urn:studio-one-attribute" ',1)
        root=ET.fromstring(document)
    return [dict(quarter=float(n.attrib['start']),numerator=int(n.attrib['numerator']),denominator=int(n.attrib['denominator']))
            for n in root.iter() if n.tag.rsplit('}',1)[-1]=='TimeSignatureMapSegment']


def reaper(path):
    root={'tag':'ROOT','lines':[],'children':[]};stack=[root]
    for raw in path.read_text(errors='replace').splitlines():
        line=raw.strip()
        if line.startswith('<'):
            node={'tag':line[1:].split()[0],'lines':[],'children':[]};stack[-1]['children'].append(node);stack.append(node)
        elif line=='>':
            if len(stack)>1:stack.pop()
        else:stack[-1]['lines'].append(line)
    project=root['children'][0]
    def walk(node):
        yield node
        for child in node['children']:yield from walk(child)
    nodes=list(walk(project));header=next((l.split() for l in project['lines'] if l.startswith('TEMPO ')),None)
    points=[l for node in nodes if node['tag']=='TEMPOENVEX' for l in node['lines'] if l.startswith('PT ')]
    items=[]
    for node in nodes:
        if node['tag']!='ITEM':continue
        values={l.split()[0]:shlex.split(l)[1:] for l in node['lines'] if l}
        files=[shlex.split(l)[1] for child in walk(node) if child['tag']=='SOURCE' for l in child['lines'] if l.startswith('FILE ')]
        if files and 'POSITION' in values and 'LENGTH' in values:
            items.append(dict(filename=PurePosixPath(files[0].replace('\\','/')).name,position=float(values['POSITION'][0]),
                length=float(values['LENGTH'][0]),source_offset=float(values.get('SOFFS',['0'])[0]),rate=float(values.get('PLAYRATE',['1'])[0])))
    clock=None
    if header and len(header)>=4 and not points:
        bpm=float(header[1]);n=int(header[2]);d=int(header[3]);end=max((i['position']+i['length'] for i in items),default=0.)
        clock=dict(clock_kind='supplied_reaper_explicit_constant_project',source_file=path.name,source_sha256=digest(path),
             tempo_events=[dict(quarter=0.,project_seconds=0.,bpm=bpm,microseconds_per_quarter=60e6/bpm)],
             meter_events=[dict(quarter=0.,project_seconds=0.,numerator=n,denominator=d)],
             project_end_seconds=end,project_end_quarter=end*bpm/60,initial_clock_explicit_at_zero=True)
    return dict(items=items,clock=clock,active_tempo_point_count=len(points),tempo_header=header)


def analysis_audio(path):
    result=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(path),'-ac','1','-ar','4000','-f','f32le','pipe:1'],capture_output=True,check=True)
    return np.frombuffer(result.stdout,dtype='<f4').astype('float64')


def propose(stem,item,master):
    source=analysis_audio(stem);rate=4000;length=min(8*rate,len(source));start=max(0,min(len(source)-length,int(len(source)*.2)-length//2))
    snippet=source[start:start+length];snippet=snippet-snippet.mean();project=item['position']+(start/rate-item['source_offset'])/item['rate']
    lo=max(0,int((project-60)*rate));hi=min(len(master),int((project+60+length/rate)*rate));target=master[lo:hi]
    if len(target)<length or np.dot(snippet,snippet)<1e-12:return None
    fftlen=1<<(len(target)+length-1).bit_length()
    corr=np.fft.irfft(np.fft.rfft(target,fftlen)*np.fft.rfft(snippet[::-1],fftlen),fftlen)[length-1:len(target)]
    sums=np.r_[0,np.cumsum(target)];squares=np.r_[0,np.cumsum(target**2)]
    variance=squares[length:]-squares[:-length]-(sums[length:]-sums[:-length])**2/length
    score=np.abs(corr)/np.sqrt(np.maximum(variance,1e-18)*np.dot(snippet,snippet));index=int(np.argmax(score))
    return dict(offset_seconds=(lo+index)/rate-project,source_window_start_seconds=start/rate,source_window_duration_seconds=length/rate,
                project_window_start_seconds=project,method='one source-stem waveform segment matched to the supplied Master',
                purpose='requested offset proposal generation only',automatic_acceptance=False,post_generation_alignment_verification_run=False)


def drum_role(filename):
    name=filename.lower()
    if 'vox' in name or 'mouth' in name:return None
    if 'kick' in name or 'kik' in name:return 'kick'
    if 'snare' in name or 'snr' in name:return 'snare'
    return None


def prepare(batch,song):
    assert_candidate_allowed(song,'review')
    job=library_root()/song['slug']/'collection';audio=job/'master.wav';info=sf.info(audio);references=[];midis=[];projects=[];song_meters=[]
    with zipfile.ZipFile(job/'source.zip') as archive:
        names=[i.filename for i in archive.infolist() if not i.is_dir() and '__MACOSX' not in i.filename]
        save(job/'archive-members.json',dict(members=[dict(name=i.filename,bytes=i.file_size) for i in archive.infolist()],zip_wide_crc_scan_run=False))
        for name in names:
            ext=PurePosixPath(name).suffix.lower()
            parts=PurePosixPath(name).parts
            native_start=next((i for i,p in enumerate(parts) if p.lower().endswith('.logicx')),None)
            if native_start is not None:
                # Native project bundles contain clock data without a .mid/.rpp suffix.
                relative=PurePosixPath(*parts[native_start:])
                if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('invalid_native_project_member')
                if ext in {'.wav','.aif','.aiff','.mp3','.flac','.m4a'}:continue
                path=job/'references/native-logic'/str(relative);path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(archive.read(name))
                references.append(dict(label=str(relative),path=str(path.relative_to(SAMPLES)),archive_member=name,native_project_clock_decoded=False))
                continue
            if ext not in {'.mid','.midi','.rpp','.song','.cpr','.ptx'}:continue
            path=job/'references'/f'{len(references):03d}{ext}';path.parent.mkdir(exist_ok=True);path.write_bytes(archive.read(name))
            references.append(dict(label=PurePosixPath(name).name,path=str(path.relative_to(SAMPLES)),archive_member=name))
            if ext in {'.mid','.midi'}:
                clock=midi_clock(path)
                if clock:
                    clock['tempo_source_archive_member']=name
                    midis.append((name,clock))
            elif ext=='.rpp':projects.append(reaper(path))
            elif ext=='.song':
                meters=studio_one_meter(path)
                if meters:song_meters.append((name,path,meters))
        if song_meters:
            name,path,meters=song_meters[0]
            for _,clock in midis:
                if clock['meter_events']:continue
                clock['meter_events']=[dict(**m,project_seconds=project_time_at(clock,m['quarter'])) for m in meters]
                clock['clock_kind']='supplied_midi_tempo_and_studio_one_meter'
                clock['midi_time_signature_events_present']=False
                clock['meter_source_file']=path.name
                clock['meter_source_archive_member']=name
                clock['meter_source_sha256']=digest(path)
                clock['initial_clock_explicit_at_zero']=clock['tempo_events'][0]['quarter']==meters[0]['quarter']==0
        midis=[r for r in midis if r[1]['meter_events']]
        midis.sort(key=lambda r:(0 if 'tempo' in r[0].lower() else 1,0 if r[1]['initial_clock_explicit_at_zero'] else 1))
        clock=midis[0][1] if midis else next((p['clock'] for p in projects if p['clock']),None)
        if clock is None:
            save(job/'preparation-status.json',dict(status='source_clock_needs_further_reading',reference_files=references,tests_run=False));return None
        save(job/'raw-clock.json',clock)
        master=analysis_audio(audio);candidates=[];details=[]
        for project in projects[:1]:
            eligible=[i for i in project['items'] if i['rate']==1 and drum_role(i['filename'])]
            eligible.sort(key=lambda i:(0 if drum_role(i['filename'])=='kick' else 1,i['filename']))
            selected_roles=set()
            for item in eligible:
                role=drum_role(item['filename'])
                if role in selected_roles:continue
                member=next((n for n in names if PurePosixPath(n).name.casefold()==item['filename'].casefold()),None)
                if not member:continue
                path=job/'alignment-stems'/f'{role}{PurePosixPath(member).suffix.lower()}';path.parent.mkdir(exist_ok=True);path.write_bytes(archive.read(member))
                proposal=propose(path,item,master)
                if proposal:
                    details.append(dict(role=role,archive_member=member,proposal=proposal));candidates.append(dict(label=('킥' if role=='kick' else '스네어')+' 시작값',offset_seconds=proposal['offset_seconds']))
                selected_roles.add(role)
                if len(selected_roles)==2:break
    return write_review(batch,song,clock,references,details,candidates)


def prepare_partial(batch,song):
    assert_candidate_allowed(song,'review')
    job=library_root()/song['slug']/'collection'
    extraction=json.loads((job/'partial-reference-extraction.json').read_text())
    references=[dict(label=PurePosixPath(r['archive_member']).name,path=str((job/r['path']).relative_to(SAMPLES)),
                     archive_member=r['archive_member']) for r in extraction['complete_reference_files']]
    reference=next(r for r in references if PurePosixPath(r['archive_member']).suffix.lower() in {'.mid','.midi'})
    clock=midi_clock(SAMPLES/reference['path'])
    if clock is None or not clock['meter_events']:raise RuntimeError('partial_reference_clock_incomplete')
    clock['tempo_source_archive_member']=reference['archive_member']
    clock['source_archive_complete']=False
    clock['source_extraction']='complete supplied MIDI entry from already acquired archive prefix'
    source=json.loads((job/'partial-alignment-source.json').read_text())
    origin=next(e['absolute_seconds'] for e in clock['smpte_offset_events'] if e['quarter']==0)
    item=dict(position=source['bwf_time_reference_seconds']-origin,source_offset=0.,rate=1.)
    proposal=propose(job/source['path'],item,analysis_audio(job/'master.wav'))
    details=[];candidates=[]
    if proposal:
        details=[dict(role='snare',archive_member=source['archive_member'],proposal=proposal,
            stem_project_origin=dict(bwf_time_reference_seconds=source['bwf_time_reference_seconds'],
                midi_smpte_origin_seconds=origin,project_position_seconds=item['position'],
                formula='BWF time reference / native sample rate - MIDI SMPTE project origin'))]
        candidates=[dict(label='스네어 시작값',offset_seconds=proposal['offset_seconds'])]
    return write_review(batch,song,clock,references,details,candidates)


def write_review(batch,song,clock,references,details,candidates):
    assert_candidate_allowed(song,'review')
    job=library_root()/song['slug']/'collection';audio=job/'master.wav';info=sf.info(audio)
    save(job/'raw-clock.json',clock)
    initial=candidates[0]['offset_seconds'] if candidates else 0.
    periods=clock['tempo_events'];meters=clock['meter_events'];quarters=[];bars=[]
    def time_at(q):
        return project_time_at(clock,q)
    for index,event in enumerate(meters):
        end=meters[index+1]['quarter'] if index+1<len(meters) else clock['project_end_quarter'];q=event['quarter'];step=4*event['numerator']/event['denominator']
        while q<end-1e-8:bars.append(dict(quarter=q,project_seconds=time_at(q)));q+=step
    for q in range(0,math.ceil(clock['project_end_quarter'])):
        t=time_at(q)
        if t<clock['project_end_seconds']-1e-8:quarters.append(dict(quarter=q,project_seconds=t,bar_start=any(abs(q-b['quarter'])<1e-8 for b in bars)))
    geometry=dict(sample_rate=info.samplerate,sample_frames=info.frames,channels=info.channels,duration_seconds=info.frames/info.samplerate,
                  sha256=digest(audio),subtype=info.subtype,source_decode='native-rate FLOAT PCM; no trimming, resampling, gain or time stretch')
    save(job/'master-geometry.json',geometry);save(job/'offset-proposals.json',dict(sources=details,post_generation_verification_run=False,owner_acceptance_pending=True))
    description='압축 파일에 포함된 제작 시계로 클릭을 준비했습니다. 제시한 오프셋은 청취 시작값이며 사용자가 확정합니다.'
    if not candidates:description+=' 자동 오프셋 시작값을 얻지 못해 0 ms에서 조정합니다.'
    if clock.get('source_archive_complete') is False:
        description+=' Master와 MIDI는 확보됐으며, 멀티트랙 압축 파일의 남은 다운로드는 제공처 한도로 대기 중입니다.'
    review=dict(title=song['title'],slug=song['slug'],description=description,audio=str(audio.relative_to(SAMPLES)),original_audio=str(audio.relative_to(SAMPLES)),
        raw_clock=str((job/'raw-clock.json').relative_to(SAMPLES)),audio_sha256=geometry['sha256'],clock_sha256=digest(job/'raw-clock.json'),
        sample_rate=info.samplerate,sample_frames=info.frames,channels=info.channels,duration_seconds=geometry['duration_seconds'],
        project_end_seconds=clock['project_end_seconds'],source_range_start_seconds=0.,
        tempo_events=periods,meter_events=meters,quarters=quarters,bars=bars,candidates=candidates,initial_offset_seconds=initial,
        clock_label=('제공 MIDI 템포 + Studio One 박자' if clock['clock_kind']=='supplied_midi_tempo_and_studio_one_meter'
                     else '제공 MIDI 시계' if clock['clock_kind'].startswith('supplied_midi') else '제공 REAPER 프로젝트 시계'),
        clock_files=references,human_alignment_accepted=False,source_archive_complete=clock.get('source_archive_complete',True))
    save(job/'review-data.json',review)
    result=dict(title=song['title'],slug=song['slug'],bpm=[e['bpm'] for e in periods],meter=[f'{e["numerator"]}/{e["denominator"]}' for e in meters],
                offset_seconds=initial,duration_seconds=geometry['duration_seconds'],owner_acceptance_pending=True,tests_or_verification_run=False)
    save(job/'preparation-status.json',dict(status='ready_for_owner_listening',**result));print(json.dumps(result,ensure_ascii=False),flush=True)
    return dict(title=song['title'],review=str((job/'review-data.json').relative_to(SAMPLES)))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path,required=True);parser.add_argument('--slug')
    parser.add_argument('--partial-source',action='store_true');args=parser.parse_args();batch=args.batch
    selection=json.loads((batch/'selection.json').read_text());rows=[]
    if args.slug:
        targets=[s for s in selection['songs'] if s['slug']==args.slug]
        for song in targets or [dict(slug=args.slug)]:assert_candidate_allowed(song,'review')
    bind_selected(batch,[s for s in selection['songs'] if s.get('review_enabled',True) and (args.slug is None or s['slug']==args.slug)])
    prepared_any=False
    for song in selection['songs']:
        if not song.get('review_enabled',True):continue
        path=library_root()/song['slug']/'collection/review-data.json'
        existing=json.loads(path.read_text()) if path.exists() else {}
        if args.slug is None or args.slug==song['slug']:
            if existing.get('human_alignment_accepted'):pass
            elif args.partial_source:prepare_partial(batch,song);prepared_any=True
            else:prepare(batch,song);prepared_any=True
            note_stage(song,batch,'pending_owner_alignment' if (library_root()/song['slug']/'collection/raw-clock.json').exists() else 'source_only')
        if path.exists():rows.append(dict(title=song['title'],review=str(path.relative_to(SAMPLES))))
    pending=any(not json.loads((SAMPLES/r['review']).read_text()).get('human_alignment_accepted') for r in rows)
    if rows and not prepared_any and not pending:
        print(json.dumps(dict(existing_owner_accepted_sources=len(rows),preparation_reused=True,owner_choices_and_cleanup_state_preserved=True)),flush=True);return
    save(batch/'index-data.json',dict(songs=rows,owner_acceptance_pending=pending))
    # The canonical server/frontend serves this descriptor directly.
    active=[s for s in selection['songs'] if s.get('review_enabled',True)]
    save(batch/'batch.json',dict(status='ready_for_owner_listening' if pending else 'active_sources_owner_accepted',prepared_sources=len(rows),
                               archive_downloads_complete=all((library_root()/s['slug']/'collection/source.zip').exists() for s in selection['songs']),
                               excluded_sources=len(selection['songs'])-len(active),
                               tests_or_verification_run=False,owner_acceptance_pending=pending,source_cleanup_performed=False))


if __name__=='__main__':main()
