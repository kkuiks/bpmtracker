"""Qualify a bounded learning pilot without opening the 20-song eval maps."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import soundfile as sf
from .probe_resources import digest

RWC_IDS=(4,5,7,9,11,13,14,15)
REV='0a1a6c31dbe73a7f5d44f7caef8cd0999402a4c2'


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def prepare(root,output,fetch_tool=None):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    sys.path.insert(0,str(root/'experiments/analysis_legacy'))
    from midi_reference import read_clock,clocks_agree
    import mido
    rows=[];audit=[]
    catalog=json.loads((root/'data/corpus/public/babyslakh-development/catalog-rendered-clock.json').read_text())
    for row in catalog['tracks']:
        label_path=root/row['reference']['path'];ref=json.loads(label_path.read_text())
        if digest(label_path)!=row['reference']['sha256']:raise ValueError('label hash changed')
        audio=root/row['input']['path']
        if digest(audio)!=row['input']['sha256']:raise ValueError('audio hash changed')
        clocks=[]
        for binding in ref['rendered_midi_sources']:
            path=root/binding['path']
            if digest(path)!=binding['sha256']:raise ValueError('rendered MIDI hash changed')
            clocks.append(read_clock(path))
        if not clocks or not all(clocks_agree(clocks[0],c) for c in clocks) or not clocks_agree(ref,clocks[0]):
            raise ValueError('render clock disagreement')
        original=read_clock(audio.parent/'all_src.mid')
        meter_ok=bool(original['explicit_initial_meter'] and ref['downbeats_seconds'])
        notes=dict(id=row['id'],stem_count=len(clocks),stem_clocks_agree=True,
                   original_clock_identical=clocks_agree(original,ref),
                   bar_and_meter_supervision=meter_ok,grouping_supervision=False,
                   timing_tier='publisher_render_clock_weak_supervision_not_sample_exact_gold',
                   prediction_based_alignment=False)
        audit.append(notes)
        rows.append(dict(id=row['id'],audio=str(audio.resolve()),audio_sha256=row['input']['sha256'],
            group=row['group_id'],dataset='babyslakh',weight=.5,duration=sf.info(audio).duration,
            labels=dict(beats=ref['beats_seconds'],bars=ref['downbeats_seconds'] if meter_ok else [],
                support=ref['evaluation_support_seconds'],tempo=ref['tempo_events'],
                meter=ref['meter_events'] if meter_ok else [],meter_known=meter_ok),
            provenance=notes))
    failures=[]
    if fetch_tool:
        spec=importlib.util.spec_from_file_location('scoped_public_fetch',fetch_tool)
        fetch=importlib.util.module_from_spec(spec);spec.loader.exec_module(fetch)
        for number in RWC_IDS:
            ident=f'RWC_P{number:03d}';folder=root/'data/corpus/public/v3-rwc-learning-pilot'/ident
            try:
                audio=folder/(ident+'.wav')
                receipt=fetch.extract('rwc',f'RWC-P/{ident}.wav',audio)
                base=f'https://raw.githubusercontent.com/rwc-music/rwc-annotations/{REV}/'
                sources={}
                for suffix,category in [('csv','beats'),('mid','MIDI_aligned')]:
                    sources[suffix]=fetch.download(base+f'01_annotations_preprocessed/{category}/RWC-P/{ident}.{suffix}',folder/(ident+'.'+suffix))
                values=list(csv.DictReader((folder/(ident+'.csv')).open(),delimiter=';'))
                times=np.array([float(x['t']) for x in values]);labels=np.array([int(x['beat']) for x in values])
                if not len(times)>16 or not np.all(np.diff(times)>0):raise ValueError('invalid beat annotations')
                midi=mido.MidiFile(folder/(ident+'.mid'))
                meters={(m.numerator,m.denominator) for track in midi.tracks for m in track if m.type=='time_signature'}
                known=meters=={(4,4)} and set(labels)=={1,2,3,4}
                if not known:raise ValueError('quarter unit / meter is not unambiguously supported')
                intervals=np.diff(times)
                # Supplied aligned quarter annotations, not producer tempo automation.
                tempo=[dict(time_seconds=float(t),bpm_quarter=float(60/g)) for t,g in zip(times[:-1],intervals)]
                rows.append(dict(id=ident,audio=str(audio.resolve()),audio_sha256=receipt['member_sha256'],
                    group=ident,dataset='rwc',weight=.5,duration=sf.info(audio).duration,
                    labels=dict(beats=times.tolist(),bars=times[labels==1].tolist(),support=[float(times[0]),float(times[-1])],
                        tempo=tempo,meter=[dict(time_seconds=float(times[0]),numerator=4,denominator=4)],meter_known=True),
                    provenance=dict(annotation_sources=sources,revision=REV,license='CC BY-NC 4.0',
                        tier='published_aligned_weak_supervision_not_owner_gold',known_beat_this_training_exposure=True)))
                save(folder/'learning-source.json',rows[-1]);print(ident,'qualified learning-only',flush=True)
            except Exception as exc:
                failures.append(dict(id=ident,error=f'{type(exc).__name__}: {exc}'))
                print(ident,failures[-1]['error'],flush=True)
                # An annotation hold is track-local; provider/range failures stop acquisition.
                if isinstance(exc,ValueError) and str(exc)=='quarter unit / meter is not unambiguously supported':
                    continue
                break
    # Stratify real symbolic meter-change works separately; select by group hash,
    # never by model results or by the known 20 evaluation songs.
    validation=set()
    for category in ('variable','constant','unknown'):
        group_rows=[r for r in rows if ('unknown' if not r['labels']['meter_known'] else
            'variable' if len(r['labels']['meter'])>1 else 'constant')==category]
        groups=sorted({r['group'] for r in group_rows},key=lambda g:hashlib.sha256(('v3-split-1:'+g).encode()).hexdigest())
        validation.update(groups[:max(1,len(groups)//5)] if len(groups)>1 else [])
    for row in rows:row['split']='validation' if row['group'] in validation else 'train'
    record=dict(schema_version=1,complete=True,role='small_learning_pilot_not_generalization_benchmark',
        source_audit=audit,acquisition_failures=failures,rows=rows,
        evaluation_primary20_used_for_training=False,grouping_supervision=False,
        caveat='MIDI render clocks and published beat labels are weak field-specific supervision. No sample-exact timing or unseen encoder exposure claim.')
    save(output/'manifest.json',record)
    print(json.dumps(dict(rows=len(rows),train=sum(r['split']=='train' for r in rows),validation=sum(r['split']=='validation' for r in rows),acquisition_failures=failures)))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--fetch-tool',type=Path);a=p.parse_args()
    prepare(Path.cwd(),a.output,a.fetch_tool)

if __name__=='__main__':main()
