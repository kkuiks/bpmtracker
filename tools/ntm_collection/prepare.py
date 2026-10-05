"""Prepare supplied producer clocks and source-only offset auditions for 3 jobs."""
from pathlib import Path,PurePosixPath
import argparse
import hashlib
import io
import json
import math
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import mido
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[2]
BATCH=ROOT/'samples/ntm-intake/20261002-new3-v1'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def emit(**data):print(json.dumps(data,ensure_ascii=False),flush=True)


def midi_clock(path):
    midi=mido.MidiFile(path);ticks=0;seconds=0.;current=500000;tempos=[];meters=[]
    for event in mido.merge_tracks(midi.tracks):
        ticks+=event.time;seconds+=mido.tick2second(event.time,midi.ticks_per_beat,current)
        q=ticks/midi.ticks_per_beat
        if event.type=='set_tempo':
            current=event.tempo
            tempos.append(dict(quarter=q,project_seconds=seconds,bpm=60_000_000/current,microseconds_per_quarter=current))
        if event.type=='time_signature':
            meters.append(dict(quarter=q,project_seconds=seconds,numerator=event.numerator,denominator=event.denominator))
    if not tempos or tempos[0]['quarter']!=0 or not meters or meters[0]['quarter']!=0:
        raise ValueError('supplied_midi_initial_clock_incomplete')
    return dict(tempo_events=tempos,meter_events=meters,project_end_seconds=seconds,
        project_end_quarter=ticks/midi.ticks_per_beat,clock_kind='supplied_producer_midi',
        source_file=path.name,source_sha256=digest(path),initial_bar_quarter=0.,
        extent_basis='supplied MIDI end-of-track; no extension to fit Master')


def rpp_details(path):
    root=dict(tag='ROOT',lines=[],children=[]);stack=[root]
    for raw in path.read_text(errors='replace').splitlines():
        line=raw.strip()
        if line.startswith('<'):
            node=dict(tag=line[1:].split()[0],lines=[],children=[]);stack[-1]['children'].append(node);stack.append(node)
        elif line=='>':
            if len(stack)<2:raise ValueError('malformed_project_nesting')
            stack.pop()
        else:stack[-1]['lines'].append(line)
    if len(stack)!=1:raise ValueError('malformed_project_nesting')
    project=root['children'][0]
    def walk(node):
        yield node
        for child in node['children']:yield from walk(child)
    nodes=list(walk(project));headers=[l.split() for l in project['lines'] if l.startswith('TEMPO ')]
    points=[l for node in nodes if node['tag']=='TEMPOENVEX' for l in node['lines'] if l.startswith('PT ')]
    items=[]
    for node in nodes:
        if node['tag']!='ITEM':continue
        values={l.split()[0]:shlex.split(l)[1:] for l in node['lines'] if l}
        sources=[child for child in walk(node) if child['tag']=='SOURCE']
        files=[shlex.split(l)[1] for child in sources for l in child['lines'] if l.startswith('FILE ')]
        if len(files)!=1 or 'POSITION' not in values or 'LENGTH' not in values:continue
        items.append(dict(filename=PurePosixPath(files[0].replace('\\','/')).name,
            position=float(values['POSITION'][0]),length=float(values['LENGTH'][0]),
            source_offset=float(values.get('SOFFS',['0'])[0]),rate=float(values.get('PLAYRATE',['1'])[0])))
    details=dict(source_file=path.name,source_sha256=digest(path),tempo_headers=headers,
        active_point_count=len(points),items=items,project_end_seconds=max(i['position']+i['length'] for i in items))
    if len(headers)!=1 or points:raise ValueError('nonconstant_project_clock_requires_explicit_decode')
    values=headers[0]
    if len(values)<4:raise ValueError('missing_explicit_project_meter')
    bpm=float(values[1]);n=int(values[2]);d=int(values[3])
    if bpm<=0 or n<=0 or d<=0:raise ValueError('invalid_project_clock')
    details['clock']=dict(tempo_events=[dict(quarter=0.,project_seconds=0.,bpm=bpm)],
        meter_events=[dict(quarter=0.,project_seconds=0.,numerator=n,denominator=d)],
        project_end_seconds=details['project_end_seconds'],project_end_quarter=details['project_end_seconds']*bpm/60,
        initial_bar_quarter=0.,clock_kind='explicit_constant_supplied_reaper_project',
        source_file=path.name,source_sha256=digest(path),extent_basis='supplied REAPER item extent')
    return details


def studio_initial(path):
    with zipfile.ZipFile(path) as z:
        root=ET.fromstring(z.read('metainfo.xml'))
    attributes={e.attrib.get('id'):e.attrib.get('value') for e in root.iter() if 'id' in e.attrib}
    return dict(source_file=path.name,source_sha256=digest(path),
        bpm=float(attributes['Media:Tempo']),numerator=int(attributes['Media:TimeSignatureNumerator']),
        denominator=int(attributes['Media:TimeSignatureDenominator']),
        decoded_scope='initial metainfo tempo and signature only; not an exhaustive variable-map parser')


def extract(z,member,path):
    raw=z.read(member);info=z.getinfo(member)
    assert len(raw)==info.file_size
    if path.exists():assert path.read_bytes()==raw
    else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return dict(member=member,path=str(path.relative_to(BATCH)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),crc32=f'{info.CRC:08x}')


def clock_at(clock,q):
    event=next(e for e in reversed(clock['tempo_events']) if e['quarter']<=q+1e-10)
    return event['project_seconds']+(q-event['quarter'])*60/event['bpm']


def render_events(clock):
    if any(clock['tempo_events'][i]['quarter']>clock['tempo_events'][i+1]['quarter'] for i in range(len(clock['tempo_events'])-1)):
        raise ValueError('nonmonotonic_source_clock')
    bars=[]
    for i,e in enumerate(clock['meter_events']):
        stop=clock['meter_events'][i+1]['quarter'] if i+1<len(clock['meter_events']) else clock['project_end_quarter']
        length=4*e['numerator']/e['denominator'];q=e['quarter']
        while q<stop-1e-8:bars.append(q);q+=length
    quarter_events=[]
    for q in range(math.ceil(clock['tempo_events'][0]['quarter']),math.ceil(clock['project_end_quarter'])):
        t=clock_at(clock,q)
        if t>=clock['project_end_seconds']-1e-8:continue
        quarter_events.append(dict(quarter=q,project_seconds=t,bar_start=any(abs(q-b)<1e-8 for b in bars)))
    assert all(a['project_seconds']<b['project_seconds'] for a,b in zip(quarter_events,quarter_events[1:]))
    return quarter_events,[dict(quarter=q,project_seconds=clock_at(clock,q)) for q in bars]


def signal(path,rate=4000):
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-ac','1','-ar',str(rate),'-f','f32le','pipe:1'],capture_output=True)
    if result.returncode:raise ValueError('audit_signal_decode_failed')
    values=np.frombuffer(result.stdout,dtype='<f4').astype(np.float64)
    if not np.isfinite(values).all():raise ValueError('nonfinite_audit_signal')
    return values


def match_window(x,reference):
    x=x-x.mean();n=len(x);m=len(reference)
    energy=float(np.dot(x,x))
    if energy<1e-10 or m<n:return None
    length=1<<(m+n-2).bit_length()
    corr=np.fft.irfft(np.fft.rfft(reference,length)*np.fft.rfft(x[::-1],length),length)[n-1:m]
    sums=np.concatenate(([0.],np.cumsum(reference)));squares=np.concatenate(([0.],np.cumsum(reference**2)))
    target=squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n
    scores=np.abs(corr)/np.sqrt(np.maximum(target,1e-20)*energy)
    ix=int(np.argmax(scores));return dict(index=ix,correlation=float(scores[ix]))


def source_offset(path,item,master,master_rate=4000):
    values=signal(path,master_rate)
    if float(np.max(np.abs(values)))<1e-8:return dict(status='silent_source',windows=[])
    size=8*master_rate;results=[]
    for fraction in [.15,.325,.5,.675,.85]:
        start=int(max(0,min(len(values)-size,int(len(values)*fraction)-size//2)))
        excerpt=values[start:start+size]
        if len(excerpt)!=size or float(np.std(excerpt))<1e-8:continue
        project_start=item['position']+(start/master_rate-item['source_offset'])/item['rate']
        lo=max(0,int((project_start-60)*master_rate));hi=min(len(master),int((project_start+60+8)*master_rate))
        candidate=match_window(excerpt,master[lo:hi])
        if candidate is None:continue
        master_start=(lo+candidate['index'])/master_rate
        results.append(dict(source_start_seconds=start/master_rate,project_start_seconds=project_start,
            master_start_seconds=master_start,offset_seconds=master_start-project_start,correlation=candidate['correlation']))
    if not results:return dict(status='no_usable_source_window',windows=[])
    offsets=np.array([r['offset_seconds'] for r in results]);correlations=np.array([r['correlation'] for r in results])
    return dict(status='audition_proposal_only',offset_seconds=float(np.median(offsets)),
        median_correlation=float(np.median(correlations)),offset_spread_seconds=float(np.ptp(offsets)),
        windows=results,diagnostic_sample_rate=master_rate,automatic_acceptance=False,
        note='Direct source waveform matches; instrument processing/pulse aliases can shift candidates. Owner listening decides.')


def prepare(job):
    metadata=json.loads((job/'source.json').read_text());geometry=json.loads((job/'master-geometry.json').read_text())
    archive=json.loads((job/'archive-inventory.json').read_text());assert archive['all_member_crc_passed']
    assert archive['archive_sha256']==digest(job/'source.zip')
    assert geometry['sha256']==digest(job/'master.wav')
    refs=[];midi=[];rpps=[];studios=[];stems=[]
    with zipfile.ZipFile(job/'source.zip') as z:
        names=[i.filename for i in z.infolist() if not i.is_dir() and '__MACOSX' not in i.filename and not PurePosixPath(i.filename).name.startswith('._')]
        for name in names:
            suffix=PurePosixPath(name).suffix.lower()
            if suffix not in {'.mid','.midi','.rpp','.cpr','.ptx','.song','.logicx'}:continue
            output=job/'references'/f'{len(refs):03d}{suffix}'
            receipt=extract(z,name,output);refs.append(receipt)
            if suffix in {'.mid','.midi'}:midi.append(midi_clock(output))
            if suffix=='.rpp':rpps.append(rpp_details(output))
            if suffix=='.song':studios.append(studio_initial(output))
        if len(rpps)!=1:raise ValueError('unique_source_item_project_required')
        project=rpps[0]
        if len(midi)>1:raise ValueError('multiple_midi_clocks_require_source_review')
        clock=midi[0] if midi else project['clock']
        source_initial=clock['tempo_events'][0]['bpm'];signature=clock['meter_events'][0]
        studio_agreements=[r for r in studios if abs(r['bpm']-source_initial)<.01 and
            (r['numerator'],r['denominator'])==(signature['numerator'],signature['denominator'])]
        if not studio_agreements:raise ValueError('initial_studio_project_disagreement_requires_review')
        reaper_signature=project['clock']['meter_events'][0]
        reaper_agrees=(reaper_signature['numerator'],reaper_signature['denominator'])==(signature['numerator'],signature['denominator'])
        save(job/'raw-clock.json',clock)
        provenance=dict(source_clock=clock,reference_assets=refs,reaper_source_items=project,
            studio_initial_metadata=studios,studio_initial_agreement=True,reaper_initial_meter_agreement=reaper_agrees,
            human_alignment_accepted=False,independent_millisecond_accuracy_certified=False,
            no_page_bpm_or_analyzer_prediction_used=True)
        save(job/'clock-source-audit.json',provenance)
        quarter_events,bars=render_events(clock)
        master=signal(job/'master.wav')
        eligible=[i for i in project['items'] if i['rate']==1. and any(r in i['filename'].lower() for r in ['kick','snare','bass'])]
        def rank(i):
            s=i['filename'].lower();return (0 if 'kick' in s else 1 if 'snare' in s else 2,
                1 if any(t in s for t in ['trig','print','di','btm','bottom']) else 0,s)
        chosen=[];roles=set()
        for item in sorted(eligible,key=rank):
            role='kick' if 'kick' in item['filename'].lower() else 'snare' if 'snare' in item['filename'].lower() else 'bass'
            if role in roles:continue
            matches=[n for n in names if PurePosixPath(n).name.casefold()==item['filename'].casefold()]
            if len(matches)!=1:continue
            output=job/'_work'/f'{role}{PurePosixPath(matches[0]).suffix.lower()}'
            receipt=extract(z,matches[0],output);audit=source_offset(output,item,master)
            record=dict(role=role,source=receipt,project_item=item,audit=audit);chosen.append(record);roles.add(role)
            emit(source_alignment_job=job.name,role=role,status=audit['status'],
                offset_seconds=audit.get('offset_seconds'),spread_seconds=audit.get('offset_spread_seconds'))
        proposals=[r for r in chosen if r['audit']['status']=='audition_proposal_only']
        proposals.sort(key=lambda r:(-r['audit']['median_correlation'],r['audit']['offset_spread_seconds']))
        initial=proposals[0]['audit']['offset_seconds'] if proposals else 0.
        candidates=[dict(label={'kick':'킥','snare':'스네어','bass':'베이스'}[r['role']]+' 후보',offset_seconds=r['audit']['offset_seconds'],
            source_role=r['role']) for r in proposals]
        save(job/'alignment-audit.json',dict(source_only=True,canonical_master_unmodified=True,
            diagnostic_resampling_only=True,automatic_alignment_accepted=False,sources=chosen))
        description='제공된 제작 지도를 사용합니다. 파형 후보는 오프셋 청취를 위한 시작값입니다.'
        if not reaper_agrees:description+=' MIDI와 Studio One의 박자표가 일치하며, REAPER 헤더의 다른 표기는 출처 기록에 남겼습니다.'
        relative=lambda path:str(path.relative_to(BATCH))
        review=dict(title=metadata['title'],slug=job.name,description=description,
            audio=relative(job/'master.wav'),original_audio=relative(next(p for p in job.glob('master-original.*') if p.suffix.lower() in {'.mp3','.wav','.flac','.m4a'})),
            raw_clock=relative(job/'raw-clock.json'),audio_sha256=geometry['sha256'],clock_sha256=digest(job/'raw-clock.json'),
            sample_rate=geometry['sample_rate'],sample_frames=geometry['sample_frames'],channels=geometry['channels'],
            duration_seconds=geometry['duration_seconds'],project_end_seconds=clock['project_end_seconds'],
            tempo_events=clock['tempo_events'],meter_events=clock['meter_events'],quarters=quarter_events,bars=bars,
            candidates=candidates,initial_offset_seconds=initial,human_alignment_accepted=False,
            clock_label='제작 MIDI + Studio One 확인' if midi else '제공 REAPER 프로젝트 + Studio One 초기값 확인',
            clock_files=[dict(label=PurePosixPath(r['member']).name,path=r['path']) for r in refs])
        save(job/'review-data.json',review)
        report=dict(status='ready_for_owner_offset_review',title=metadata['title'],source_master=geometry,
            archive_sha256=archive['archive_sha256'],archive_all_member_crc_verified=True,
            selected_clock_source=clock['clock_kind'],quarter_bpm=[e['bpm'] for e in clock['tempo_events']],
            signatures=[f"{e['numerator']}/{e['denominator']}" for e in clock['meter_events']],
            tempo_change_count=len(clock['tempo_events'])-1,meter_change_count=len(clock['meter_events'])-1,
            initial_offset_seconds=initial,producer_project_end_seconds=clock['project_end_seconds'],
            proposed_map_end_in_master_seconds=clock['project_end_seconds']+initial,
            source_metadata_meter_conflict=not reaper_agrees,offset_requires_owner_listening=True,
            retained_archive_and_selected_stems=True,files_deleted=[],no_analyzer_model_or_score_run=True)
        save(job/'report.json',report)
    emit(ready_for_owner_offset_review=True,job=job.name,bpm=report['quarter_bpm'],meter=report['signatures'],initial_offset_seconds=initial)


def main(slug):
    selected=json.loads((BATCH/'selection.json').read_text())['songs']
    jobs=[BATCH/r['slug'] for r in selected if slug is None or r['slug']==slug]
    for job in jobs:prepare(job)
    if all((BATCH/r['slug']/'review-data.json').exists() for r in selected):
        save(BATCH/'index-data.json',dict(songs=[dict(title=r['title'],review=r['slug']+'/review-data.json') for r in selected]))
        save(BATCH/'batch.json',dict(status='ready_for_owner_offset_review',songs=[json.loads((BATCH/r['slug']/'report.json').read_text()) for r in selected],
            source_count=3,official_archive_link_requests=sum(json.loads((BATCH/r['slug']/'archive-request.json').read_text())['official_archive_link_requests'] for r in selected),
            owner_acceptance_pending=True,files_deleted=[],new_sample_benchmark_enrollment=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--slug');args=parser.parse_args();main(args.slug)
