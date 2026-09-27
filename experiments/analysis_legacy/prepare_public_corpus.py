"""Audit public assets and freeze a prediction-independent development catalog."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import zipfile

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from midi_reference import read_clock, clocks_agree


def safe_target(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('unsafe archive path')
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('archive escapes output root')
    return target


def extract_archive(archive, output):
    if output.exists():
        raise ValueError('extraction directory must be new')
    metadata = json.loads(archive.with_name(archive.name+'.json').read_text())
    if sha256(archive) != metadata['sha256']:
        raise ValueError('archive differs from recorded download')
    output.mkdir(parents=True)
    count = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                target = safe_target(output, entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('archive links are not accepted')
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(entry) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
    else:
        with tarfile.open(archive, 'r:gz') as source:
            for entry in source:
                target = safe_target(output, entry.name)
                if entry.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif entry.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(entry) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
                else:
                    raise ValueError('archive special files are not accepted')
    (output/'extraction.json').write_text(json.dumps({'archive_sha256':metadata['sha256'],'files':count},indent=2)+'\n')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def read_published_beats(path):
    data=np.loadtxt(path,ndmin=2)
    if data.shape[1] not in (1,2) or not len(data) or not np.isfinite(data).all():
        raise ValueError('expected finite beat times and optional beat numbers')
    times=data[:,0]
    if np.any(np.diff(times)<=0) or np.any(times<0):
        raise ValueError('beat times must be nonnegative and strictly increasing')
    numbers=data[:,1] if data.shape[1]==2 else None
    downbeats=times[numbers==1].tolist() if numbers is not None and np.any(numbers==1) else None
    return times.tolist(),downbeats


def prepare_gtzan(root, per_genre):
    target = root/'gtzan-development'
    if target.exists():
        raise ValueError('dataset target must be new')
    extract_archive(root/'downloads/gtzan-features.zip', target/'published-features')
    extract_archive(root/'downloads/beat-annotations-v1.1.zip', target/'published-annotations')
    annotations = sorted((target/'published-annotations').glob('*/gtzan/annotations/beats/*.beats'))
    groups = {}
    for path in annotations:
        groups.setdefault(path.stem.split('_')[1], []).append(path)
    selected = []
    for genre, paths in sorted(groups.items()):
        ordered = sorted(paths, key=lambda p:hashlib.sha256(('joljak-public-v1:'+p.stem).encode()).hexdigest())
        selected.extend(ordered[:per_genre])
    records = []
    with zipfile.ZipFile(target/'published-features/gtzan.npz') as features:
        for annotation in selected:
            name = annotation.stem
            feature_path = target/'selected-features'/f'{name}.npy'
            feature_path.parent.mkdir(exist_ok=True)
            with feature_path.open('xb') as file:
                file.write(features.read(f'{name}/track.npy'))
            array = np.load(feature_path, allow_pickle=False)
            if array.ndim != 2 or array.shape[1] != 128 or not np.isfinite(array).all():
                raise ValueError('unexpected published spectrogram')
            times,downbeats = read_published_beats(annotation)
            reference = {'kind':'published_human_beat_annotation','source_annotation':str(annotation),
                         'source_annotation_sha256':sha256(annotation),'annotation_version':'beat_this_annotations v1.1',
                         'beats_seconds':times,'downbeats_seconds':downbeats,
                         'tempo_events':None,'meter_events':None,'evaluation_support_seconds':[0,len(array)/50],
                         'source_origin_shift_seconds':0,
                         'annotation_caveat':'Human beat/downbeat labels, not sample-exact DAW tempo events. Waveform not acquired.'}
            label_path=target/'labels'/f'{name}.json'
            write_json(label_path,reference)
            records.append({'id':name,'dataset':'gtzan','genre':name.split('_')[1],
                            'input':{'kind':'spectrogram','path':str(feature_path),'sha256':sha256(feature_path),'fps':50},
                            'reference':{'path':str(label_path),'sha256':sha256(label_path)},
                            'duration_seconds':len(array)/50,'model_overlap':'explicitly excluded from final0 training by publisher',
                            'target_scope':'unqualified mixed genres; metronome use unknown','group_id':name})
    return target, {'schema_version':1,'dataset':'gtzan','role':'development_external_probe_not_final_blind_test',
                    'selection':f'{per_genre} per genre by SHA256(joljak-public-v1:track_id), frozen before inference',
                    'acquired_annotation_count':len(annotations),'source_records':['https://zenodo.org/records/13922116','https://github.com/CPJKU/beat_this_annotations/tree/v1.1'],
                    'tracks':records,'excluded':[],'importer_sha256':sha256(__file__)}


def prepare_babyslakh(root, reuse_extracted=False):
    target = root/'babyslakh-development'
    if reuse_extracted:
        extraction=json.loads((target/'published/extraction.json').read_text())
        if extraction['archive_sha256']!=sha256(root/'downloads/babyslakh.tar.gz'):
            raise ValueError('extraction provenance mismatch')
    else:
        if target.exists():
            raise ValueError('dataset target must be new')
        extract_archive(root/'downloads/babyslakh.tar.gz', target/'published')
    records, excluded, seen = [], [], set()
    for midi_path in sorted((target/'published').rglob('all_src.mid')):
        directory=midi_path.parent
        name='babyslakh_'+directory.name
        try:
            original=read_clock(midi_path)
            group=sha256(midi_path)
            if group in seen:
                excluded.append({'id':name,'reason':'duplicate original MIDI hash','group_id':group})
                continue
            stem_paths=sorted((directory/'MIDI').glob('*.mid'))
            stem_references=[read_clock(path) for path in stem_paths]
            mismatched=[]
            for path,stem_reference in zip(stem_paths,stem_references):
                if not clocks_agree(stem_references[0],stem_reference) or stem_reference['ticks_per_quarter']!=stem_references[0]['ticks_per_quarter']:
                    mismatched.append(path.name)
            if not stem_paths or mismatched:
                raise ValueError(f'rendered MIDI clock disagreement: {mismatched}')
            support=[min(r['note_span_ticks'][0] for r in stem_references),max(r['note_span_ticks'][1] for r in stem_references)]
            reference=read_clock(stem_paths[0],note_span_ticks=support)
            reference['original_midi_sha256']=original['midi_sha256']
            reference['rendered_midi_sources']=[{'path':str(p),'sha256':r['midi_sha256']} for p,r in zip(stem_paths,stem_references)]
            reference['original_clock_identical']=clocks_agree(original,reference)
            reference['original_tempo_quantization_difference_us']=max(abs(a['microseconds_per_quarter']-b['microseconds_per_quarter']) for a,b in zip(original['tempo_events'],reference['tempo_events'])) if len(original['tempo_events'])==len(reference['tempo_events']) else None
            reference['clock_source_policy']='Use exact rendered instrument MIDI clock; aggregate note support over all instruments. Preserve original MIDI separately.'
            if not original['explicit_initial_meter']:
                reference['downbeats_seconds']=None
                reference['downbeat_label_status']='excluded_original_meter_not_explicit'
            audio_path=directory/'mix.wav'
            info=sf.info(audio_path)
            if reference['evaluation_support_seconds'][1] > info.duration+.1:
                raise ValueError('MIDI note span exceeds supplied audio')
            reference['source_audio_sha256']=sha256(audio_path)
            reference['stem_clock_agreement_count']=len(stem_paths)
            reference['source_alignment']='publisher-aligned rendered MIDI; no inferred offset; sample attack latency unverified'
            label_path=target/'labels-rendered-clock'/f'{name}.json'
            write_json(label_path,reference)
            records.append({'id':name,'dataset':'babyslakh','genre':'MIDI_multitrack_render',
                            'input':{'kind':'audio','path':str(audio_path),'sha256':sha256(audio_path)},
                            'reference':{'path':str(label_path),'sha256':sha256(label_path)},
                            'duration_seconds':info.duration,'sample_rate':info.samplerate,'sample_frames':info.frames,
                            'model_overlap':'not named among the 16 published Beat This training datasets; composition overlap not audited',
                            'target_scope':'authored MIDI clock and synthesized multitrack; not a recorded-band accuracy benchmark',
                            'group_id':group,'tempo_event_count':len(reference['tempo_events']),
                            'meter_event_count':len(reference['meter_events']),'downbeat_labels':reference['downbeats_seconds'] is not None})
            seen.add(group)
        except (ValueError,OSError) as error:
            excluded.append({'id':name,'reason':str(error)})
    return target, {'schema_version':1,'dataset':'babyslakh','role':'development_intended_clock_control',
                    'selection':'all 20 released tracks, deduplicated by original MIDI hash; no prediction-based selection',
                    'source_records':['https://zenodo.org/records/4603870','https://github.com/ethman/slakh-utils'],
                    'tracks':records,'excluded':excluded,'importer_sha256':sha256(__file__),
                    'midi_importer_sha256':sha256(Path(__file__).with_name('midi_reference.py'))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',choices=['gtzan','babyslakh'])
    parser.add_argument('--root',type=Path,default=Path('data/corpus/public'))
    parser.add_argument('--per-genre',type=int,default=5)
    parser.add_argument('--reuse-extracted',action='store_true',help='reuse verified BabySlakh extraction while writing a new rendered-clock catalog')
    args=parser.parse_args()
    if not 1 <= args.per_genre <= 100:
        parser.error('per-genre must be between 1 and 100')
    target,catalog=prepare_gtzan(args.root,args.per_genre) if args.dataset=='gtzan' else prepare_babyslakh(args.root,args.reuse_extracted)
    catalog_path=target/('catalog.json' if args.dataset=='gtzan' else 'catalog-rendered-clock.json')
    write_json(catalog_path,catalog)
    print(json.dumps({'catalog':str(catalog_path),'selected':len(catalog['tracks']),'excluded':catalog['excluded']},indent=2))


if __name__=='__main__':
    main()
