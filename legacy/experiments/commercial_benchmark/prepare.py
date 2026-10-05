"""Freeze the existing corpus and create protected, metadata-neutral WAV inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import struct

import soundfile as sf


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def chunks(path):
    with Path(path).open('rb') as stream:
        header=stream.read(12)
        if len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE':
            raise ValueError('working-copy adapter supports RIFF WAVE only')
        limit=min(Path(path).stat().st_size,struct.unpack('<I',header[4:8])[0]+8)
        while stream.tell()+8<=limit:
            tag,length=struct.unpack('<4sI',stream.read(8));offset=stream.tell()
            if offset+length>limit:raise ValueError('truncated WAV chunk')
            yield tag,length,offset
            stream.seek(offset+length+(length%2))


def neutral_copy(source, destination, *, resume=False):
    entries=list(chunks(source));kept=[r for r in entries if r[0] in (b'fmt ',b'fact',b'data')]
    if sum(r[0]==b'fmt ' for r in kept)!=1 or sum(r[0]==b'data' for r in kept)!=1:
        raise ValueError('ambiguous WAV format/data chunks')
    total=4+sum(8+length+(length%2) for _,length,_ in kept)
    if total>=2**32:raise ValueError('RIFF output exceeds4GiB')
    audio_hash=hashlib.sha256();expected_hash=hashlib.sha256()
    existing=Path(destination).exists()
    if existing and not resume:raise FileExistsError(destination)
    with Path(source).open('rb') as src:
        dst=None if existing else Path(destination).open('xb')
        def write(data):
            expected_hash.update(data)
            if dst is not None:dst.write(data)
        write(b'RIFF'+struct.pack('<I',total)+b'WAVE')
        for tag,length,offset in kept:
            write(tag+struct.pack('<I',length));src.seek(offset);remaining=length
            while remaining:
                data=src.read(min(remaining,1024*1024))
                if not data:raise ValueError('WAV source changed during copy')
                write(data);remaining-=len(data)
                if tag==b'data':audio_hash.update(data)
            if length%2:write(b'\0')
        if dst is not None:dst.close()
    if digest(destination)!=expected_hash.hexdigest():raise ValueError('existing/new neutral WAV bytes differ')
    old,new=sf.info(source),sf.info(destination)
    if (old.frames,old.samplerate,old.channels,old.subtype)!=(new.frames,new.samplerate,new.channels,new.subtype):
        raise ValueError('WAV sample geometry changed')
    return dict(source_sha256=digest(source),working_sha256=digest(destination),
                pcm_data_sha256=audio_hash.hexdigest(),pcm_bytes_unchanged=True,
                sample_rate=old.samplerate,sample_frames=old.frames,channels=old.channels,
                subtype=old.subtype,removed_chunks=[tag.decode('ascii',errors='replace') for tag,_,_ in entries if tag not in (b'fmt ',b'fact',b'data')],
                source_time_origin_preserved=True,reference_offset_applied=False)


def windows_path(path, distribution):
    value=Path(path).resolve()
    if str(value).startswith('/mnt/') and len(value.parts)>3 and len(value.parts[2])==1:
        return str(PureWindowsPath(value.parts[2].upper()+':/',*value.parts[3:]))
    return str(PureWindowsPath('//wsl.localhost/'+distribution,*value.parts[1:]))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--input',type=Path,default=Path('data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/predictions/manifest.json'))
    p.add_argument('--inventory',type=Path,default=Path('data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/reference-inventory.json'))
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=a.resume);(a.output/'inputs').mkdir(exist_ok=a.resume);(a.output/'evaluation').mkdir(exist_ok=a.resume)
    original=json.loads(a.input.read_text());inventory=json.loads(a.inventory.read_text());qualified={r['id']:r for r in inventory['rows']}
    if not original['complete'] or original['references_available_to_runner']:raise ValueError('frozen source-only cohort required')
    distribution=os.environ['WSL_DISTRO_NAME'];rows=[];bindings=[]
    for index,row in enumerate(original['rows']):
        entry=qualified[row['id']];assert digest(row['audio'])==row['source']['sha256']==entry['audio_expected']
        assert digest(entry['reference'])==entry['reference_expected']
        neutral=a.output/'inputs'/f's{index:02d}.wav';receipt=neutral_copy(row['audio'],neutral,resume=a.resume)
        assert receipt['source_sha256']==row['source']['sha256']
        assert receipt['sample_rate']==row['source']['sample_rate'] and receipt['sample_frames']==row['source']['sample_frames']
        rows.append(dict(id=row['id'],title=row['title'],neutral_name=neutral.name,
                         source=row['source'],original_audio=row['audio'],working_audio=str(neutral.resolve()),
                         windows_working_audio=windows_path(neutral,distribution),working_copy=receipt))
        bindings.append(dict(id=row['id'],role=entry['role'],reference=entry['reference'],reference_sha256=entry['reference_expected'],scope_note=entry.get('scope_note','Individual saved owner-approved scope; see unchanged reference')))
        print(index,row['id'],receipt['removed_chunks'],flush=True)
    assert len(rows)==21
    record=dict(complete=True,input_manifest_sha256=digest(a.input),references_available_to_analyzer=False,
                expected_source_count=21,finished_recordings=20,auxiliary=1,distribution=distribution,
                policy='One source audio only; fresh independent project; no BPM/signature/phase correction or owner map imported',rows=rows)
    (a.output/'inputs.json').write_text(json.dumps(record,indent=2)+'\n')
    (a.output/'evaluation/reference-bindings.json').write_text(json.dumps(dict(rows=bindings,inventory_sha256=digest(a.inventory)),indent=2)+'\n')
    shutil.copyfile(a.inventory,a.output/'evaluation/original-inventory.json')
    protocol=dict(scope='Existing reviewed20 recordings plus auxiliary1; commercial automatic results and owner review artifacts',
                  input_manifest_sha256=digest(a.output/'inputs.json'),inputs_have_no_musical_metadata=True,
                  pcm_and_origin_unchanged=True,originals_preserved=True,
                  product_candidates=['Cubase Pro15.0.30 (owner-owned)','Melodyne Studio (availability not yet established)'],
                  global_settings='Freeze product/version/settings before cohort predictions; default automatic analysis, no per-song answer selection',
                  prediction_input='Neutral PCM working copy with identical sample bytes and sample geometry; no reference or initial-BPM guide',
                  unsupported_components='Unavailable, never filled with owner truth or product UI defaults; full-task success still requires all gates',
                  scoring='Frozen six-score/gate policy and approved scopes; explicitly no-grid tails retained',
                  origin='Bind native project/audio-source start using native metadata; never fit a shift to the owner map',
                  review='Per product/song raw native project, original exported tempo data, adapted map, score and full-length source/click review',
                  no_paid_purchase_authorized=True,model_or_reference_promotion=False,new_corpus=False)
    (a.output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')


if __name__=='__main__':main()
