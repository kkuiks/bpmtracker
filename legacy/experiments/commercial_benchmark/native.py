"""Source-bound Cubase native exports; UI signature placeholders stay unknown."""
from decimal import Decimal
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis_legacy'))
from experiments.analysis_legacy.music_map_contract import prepare_map


def values(node):
    return {c.get('name'):c.get('value') for c in node if c.get('value') is not None}


def audio_binding(path, row):
    root=ET.parse(path).getroot()
    tracks=root.findall("./list[@name='track']/obj[@class='MAudioTrackEvent']")
    files=root.findall(".//obj[@class='AudioFile']")
    events=root.findall(".//obj[@class='MAudioEvent']")
    if len(tracks)!=1 or len(files)!=1 or len(events)!=1:
        raise ValueError('one source audio track/file/event required')
    source=row['source'];file=values(files[0]);event=values(events[0])
    clip=events[0].find("obj[@class='PAudioClip']")
    domain=clip.find("member[@name='Domain']")
    period=float(values(domain)['Period'])
    node_domain=tracks[0].find("obj[@class='MListNode']/member[@name='Domain']")
    name=clip.find("obj[@class='FNPath']/string[@name='Name']").get('value')
    if (name!=row['neutral_name'] or int(file['FrameCount'])!=source['sample_frames'] or
            float(file['Rate'])!=source['sample_rate'] or
            not math.isclose(period,1/source['sample_rate'],rel_tol=1e-12) or
            float(event['Start'])!=0 or not math.isclose(float(event['Length']),source['sample_frames'],rel_tol=0,abs_tol=1e-6) or
            int(values(node_domain)['Type'])!=1):
        raise ValueError('native audio identity/origin/linear timebase/sample clock mismatch')
    for item in root.findall(".//*[@name='MusicalMode']"):
        if item.get('value') not in ('0',None):raise ValueError('native musical mode active')
    return dict(native_file=name,source_sample_rate=source['sample_rate'],
                source_sample_frames=source['sample_frames'],native_clip_period_seconds=period,
                source_start_seconds=0.,native_project_start_seconds=0.,
                native_event_duration_seconds=float(event['Length'])*period,
                audio_frame_count_unchanged=True,linear_timebase=True,reference_alignment_applied=False)


def tempo_export(path, *, ticks_per_quarter):
    """Read only the observed native Jump schema, never guess tick resolution."""
    tpq=Decimal(str(ticks_per_quarter))
    if tpq<=0:raise ValueError('positive explicit tick resolution required')
    root=ET.parse(path).getroot();events=[];duplicates=0;elapsed=Decimal(0)
    for node in root.findall(".//obj[@class='MTempoEvent']"):
        v=values(node)
        if set(v)-{'BPM','PPQ'}:raise ValueError('unverified tempo event/ramp schema')
        tick=Decimal(v['PPQ']);bpm=Decimal(v['BPM'])
        if not tick.is_finite() or not bpm.is_finite() or tick<0 or bpm<=0:
            raise ValueError('invalid native tempo event')
        if events:
            previous=events[-1]
            if tick==previous['tick']:
                if bpm!=previous['bpm']:raise ValueError('conflicting simultaneous native tempos')
                duplicates+=1;continue
            if tick<previous['tick']:raise ValueError('unordered native tempos')
            elapsed+=(tick-previous['tick'])*Decimal(60)/(tpq*previous['bpm'])
        elif tick!=0:raise ValueError('nonzero native initial clock needs separate origin evidence')
        events.append(dict(tick=tick,bpm=bpm,time=elapsed,quarter=tick/tpq))
    if not events:raise ValueError('native tempo export empty')
    signatures=[values(n) for n in root.findall(".//obj[@class='MTimeSignatureEvent']")]
    if len(signatures)!=1 or signatures[0].get('Numerator')!='1' or signatures[0].get('Denominator')!='4':
        raise ValueError('unexpected automatic signature: inspect native workflow')
    return events,dict(ticks_per_quarter=float(tpq),identical_duplicate_events=duplicates,
                       native_signature_events=signatures,signature_semantics='automatic 1/4 placeholder, not estimated meter',
                       native_interpolation='Jump; observed native event schema contains BPM and PPQ only')


def adapt(smt, track, row, *, ticks_per_quarter):
    binding=audio_binding(track,row)
    events,receipt=tempo_export(smt,ticks_per_quarter=ticks_per_quarter)
    duration=row['source']['sample_frames']/row['source']['sample_rate']
    knots=[dict(pulse=float(e['quarter']),source_seconds=float(e['time'])) for e in events]
    last=events[-1]
    # Native tempo tracks continue with their last Jump rate. Explicitly retain
    # clock context beyond source support; do not fit an end knot to a reference.
    end=max(duration,float(last['time']))+60/float(last['bpm'])
    q=float(last['quarter'])+(end-float(last['time']))*float(last['bpm'])/60
    knots.append(dict(pulse=q,source_seconds=end))
    raw=dict(schema_version=1,source=row['source'],clock_knots=knots,
             quarters_per_pulse=dict(numerator=1,denominator=1),
             bar_anchor_pulse=None,meter_events=None,support_seconds=[[0.,duration]],
             analysis_condition='unhinted',shared_origin_id=None)
    payload=dict(map=prepare_map(raw),native_audio_binding=binding,native_tempo_receipt=receipt,
                 native_tempos=[dict(quarter=float(e['quarter']),source_seconds=float(e['time']),bpm=float(e['bpm'])) for e in events],
                 unavailable=['meter','bar_phase','bar_boundaries','meter_changes','automatic_no_grid_detection'],
                 canonical_source_binding='identical PCM samples and geometry; stripped container metadata changes working-file SHA only',
                 manual_musical_correction=False,reference_alignment_applied=False)
    return payload
