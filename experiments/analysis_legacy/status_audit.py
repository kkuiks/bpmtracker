"""Freeze a complete, reference-explicit snapshot for the Joljak status audit.

This utility inventories existing assets and creates evaluation catalogs. It
never infers, shifts, rescales, or repairs a reference from model predictions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from prepare_public_corpus import read_published_beats


PREFERRED_PUBLIC_CATALOGS = (
    ('babyslakh', Path('data/corpus/public/babyslakh-development/catalog-rendered-clock.json'),
     'synthetic_authored_clock', True),
    ('forestry_creator', Path('data/corpus/public/forestry-pilot-v1/catalog.json'),
     'creator_map_observed_click_alignment', True),
    ('forestry_observed_click', Path('data/corpus/public/forestry-observed-click-v1/catalog.json'),
     'observed_click_beats_only', True),
    ('groove', Path('data/corpus/public/groove-pilot-v1/catalog.json'),
     'publisher_aligned_metronome_midi', True),
    ('walker', Path('data/corpus/public/walker-pilot-v1/catalog.json'),
     'audited_creator_click_beats', True),
    ('daybreak', Path('data/corpus/public/daybreak-candidates-v1/catalog.json'),
     'unverified_mix_map_origin', False),
)

NTM = (
    ('ntm_sleeping-with-sirens_an-ending-in-itself',
     Path('/mnt/d/NailTheMix/SleepingWithSirens_AnEndingInItself'), 'finished_master', 'matt-good'),
    ('ntm_archspire_liminal-cypher',
     Path('/mnt/d/NailTheMix/processed/dave-otero-archspire-liminal-cypher'), 'finished_master', 'dave-otero'),
    ('ntm_state-champs_common-sense',
     Path('/mnt/d/NailTheMix/processed/anton-delost-state-champs-common-sense'), 'finished_master', 'anton-delost'),
    ('ntm_kami-kehoe_die-4-u',
     Path('/mnt/d/NailTheMix/processed/keith-sorrells-kami-kehoe-die-4-u'), 'finished_master', 'keith-sorrells'),
)

METHODS = [
    {'stage':'acoustic_evidence','method':'Beat This final0 official minimal','automatic':True,
     'implementation':'run_beat_this.py / run_corpus_benchmark.py','output':'beat and downbeat events',
     'limits':'50 Hz frames; output is not a tempo/meter map'},
    {'stage':'acoustic_evidence','method':'Beat Transformer fold4 official decoder','automatic':True,
     'implementation':'run_beat_transformer.py','output':'beat and downbeat events',
     'limits':'audio-only; Spleeter frontend; official DBN limits 55-215 BPM and 3/4 bars'},
    {'stage':'pulse_interpretation','method':'historical DBN','automatic':True,
     'implementation':'legacy_dbn.py','output':'regularized beat/downbeat events',
     'limits':'whole-song 3-or-4 meter and fixed pulse-rate bounds'},
    {'stage':'pulse_interpretation','method':'meter-free pulse decoder','automatic':True,
     'implementation':'decode_pulses.py','output':'regularized pulses independent of meter',
     'limits':'pulse musical unit remains unresolved'},
    {'stage':'tempo_map','method':'continuous clock fitter','automatic':True,
     'implementation':'fit_clock.py','output':'piecewise continuous tempo proposal',
     'limits':'assumes usable pulse indexing; can miss short changes'},
    {'stage':'tempo_map','method':'short-change fitter v2','automatic':True,
     'implementation':'fit_clock_v2.py','output':'bounded refined change topology',
     'limits':'requires correctly indexed observations; evaluated in bounded diagnostics'},
    {'stage':'candidate_generation','method':'multi-path clock candidates','automatic':True,
     'implementation':'clock_candidates.py','output':'pulse-level and phase alternatives plus source-only ranking',
     'limits':'ranking is uncalibrated; meter and musical origin unresolved'},
    {'stage':'candidate_generation','method':'partial-region restart','automatic':True,
     'implementation':'clock_candidate_regions.py','output':'supported partial clocks and unknown bridges',
     'limits':'partial output is not a full-song map'},
    {'stage':'optional_refinement','method':'soft integer/half-BPM prior','automatic':True,
     'implementation':'tempo_prior.py','output':'same-topology refit with unrestricted escape',
     'limits':'does not recover pulse unit, missing changes, or meter; no default promoted'},
    {'stage':'optional_refinement','method':'shared phase proposal','automatic':True,
     'implementation':'phase_alignment.py','output':'bounded common phase shift or abstention',
     'limits':'attack timing is not ground-truth beat timing; no default promoted'},
    {'stage':'meter','method':'fixed/variable bar decoder','automatic':True,
     'implementation':'decode_bar_structure.py','output':'2/3/4-pulse bar proposals',
     'limits':'denominator and exact meter-change recovery unresolved'},
    {'stage':'review','method':'interactive correction prototype','automatic':False,
     'implementation':'review_clock.mjs','output':'accepted user map, locks, undo, save/restore, click WAV',
     'limits':'diagnostic/review tool; excluded from automatic performance'},
]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def audio_geometry(path):
    try:
        info = sf.info(path)
        return {'readable':True, 'sample_rate':info.samplerate, 'channels':info.channels,
                'sample_frames':info.frames, 'duration_seconds':info.duration,
                'format':info.format, 'subtype':info.subtype}
    except RuntimeError:
        command=['ffprobe','-v','error','-select_streams','a:0','-show_entries',
                 'stream=sample_rate,channels,duration','-of','json',str(path)]
        result=subprocess.run(command,check=True,capture_output=True,text=True)
        stream=json.loads(result.stdout)['streams'][0]
        return {'readable':True,'sample_rate':int(stream['sample_rate']),'channels':int(stream['channels']),
                'sample_frames':None,'duration_seconds':float(stream['duration']),
                'format':path.suffix.lower().lstrip('.'),'subtype':None}


def normalized_events(events, *, rate=False):
    output=[]
    for event in events:
        time=event.get('master_seconds',event.get('time_seconds'))
        row={'time_seconds':float(time)}
        if rate:
            row['bpm_quarter']=float(event['bpm_quarter'])
            row['microseconds_per_quarter']=event.get('microseconds_per_quarter')
        else:
            row.update(numerator=int(event['numerator']),denominator=int(event['denominator']))
        output.append(row)
    output.sort(key=lambda item:item['time_seconds'])
    if any(b['time_seconds'] <= a['time_seconds'] for a,b in zip(output,output[1:])):
        raise ValueError('reference events must be strictly increasing')
    return output


def ntm_reference(track_id, root, output):
    acceptance_path=root/'acceptance.json'; map_path=root/'tempo-aligned.json'; audio_path=root/'master.wav'
    acceptance=json.loads(acceptance_path.read_text()); aligned=json.loads(map_path.read_text())
    if acceptance['status'] not in ('user_accepted_alignment','user_accepted_full_song_alignment'):
        raise ValueError(f'{track_id}: owner acceptance missing')
    if sha256(audio_path) != acceptance['master']['sha256']:
        raise ValueError(f'{track_id}: accepted master hash mismatch')
    expected=acceptance['aligned_map']['sha256']
    if sha256(map_path) != expected:
        raise ValueError(f'{track_id}: accepted map hash mismatch')
    geometry=audio_geometry(audio_path); duration=geometry['duration_seconds']
    quarters=aligned.get('quarter_events',aligned.get('quarters'))
    if not quarters:
        raise ValueError(f'{track_id}: accepted map lacks quarter events')
    eligible=[q for q in quarters if 0 <= q['master_seconds'] < duration]
    if len(eligible)<2:
        raise ValueError(f'{track_id}: insufficient in-audio quarter events')
    beats=[float(q['master_seconds']) for q in eligible]
    indices=[float(q['quarter_index']) for q in eligible]
    downbeats=[float(q['master_seconds']) for q in eligible if q.get('accent')]
    reference={'kind':'owner_accepted_producer_tempo_map','reference_tier':'user_reviewed_tempo_map',
        'acceptance_path':str(acceptance_path),'acceptance_sha256':sha256(acceptance_path),
        'accepted_by':'project_owner','accepted_offset_seconds':acceptance['offset_seconds'],
        'full_song_listening_passed':acceptance.get('full_song_listening_passed'),
        'listening_coverage':acceptance.get('listening_coverage'),
        'source_audio_sha256':sha256(audio_path),'source_origin_shift_seconds':acceptance['offset_seconds'],
        'alignment_fitted_to_predictions':False,'beats_seconds':beats,'quarter_indices':indices,
        'downbeats_seconds':downbeats,'tempo_events':normalized_events(aligned['tempo_events'],rate=True),
        'meter_events':normalized_events(aligned['meter_events']),
        'evaluation_support_seconds':[beats[0],beats[-1]],
        'mapped_tail_status':'outside last accepted quarter is not scored',
        'annotation_caveat':'Scored against the exact owner-approved producer map. No independent original-click millisecond error bound is claimed.'}
    target=output/'references'/(track_id+'.json');write_json(target,reference)
    record={'id':track_id,'dataset':'ntm_user_reference','genre':'finished_production_master',
        'group_id':track_id,'input':{'kind':'audio','path':str(audio_path),'sha256':sha256(audio_path)},
        'reference':{'path':str(target),'sha256':sha256(target)},
        'duration_seconds':duration,'sample_rate':geometry['sample_rate'],'sample_frames':geometry['sample_frames'],
        'model_overlap':'unknown','target_scope':'finished studio Master with owner-approved supplied tempo map alignment',
        'qualification_status':'user_reviewed_tempo_map','reference_tier':'user_reviewed_tempo_map',
        'evaluation_admission':'status_audit_owner_reference',
        'tempo_event_count':len(reference['tempo_events']),'meter_event_count':len(reference['meter_events']),
        'downbeat_labels':bool(downbeats),'acceptance':{'path':str(acceptance_path),'sha256':sha256(acceptance_path)}}
    return record, reference, geometry


def full_gtzan_catalog(output):
    source=Path('data/corpus/public/gtzan-development')
    annotation_root=source/'published-annotations'
    annotations=sorted(annotation_root.glob('*/gtzan/annotations/beats/*.beats'))
    archive=source/'published-features/gtzan.npz'
    records=[];excluded=[];seen={}
    with zipfile.ZipFile(archive) as features:
        members=set(features.namelist())
        for annotation in annotations:
            name=annotation.stem;member=f'{name}/track.npy'
            if member not in members:
                excluded.append({'id':name,'reason':'published feature member missing'});continue
            raw=features.read(member);digest=hashlib.sha256(raw).hexdigest()
            if digest in seen:
                excluded.append({'id':name,'reason':'duplicate exact feature bytes','duplicate_of':seen[digest]});continue
            feature_path=output/'features'/(name+'.npy');feature_path.parent.mkdir(parents=True,exist_ok=True)
            feature_path.write_bytes(raw)
            array=np.load(feature_path,allow_pickle=False)
            if array.ndim!=2 or array.shape[1]!=128 or not np.isfinite(array).all():
                raise ValueError(f'{name}: invalid published feature')
            beats,downbeats=read_published_beats(annotation)
            reference={'kind':'published_human_beat_annotation','source_annotation':str(annotation),
                'source_annotation_sha256':sha256(annotation),'annotation_version':'beat_this_annotations v1.1',
                'beats_seconds':beats,'downbeats_seconds':downbeats,'tempo_events':None,'meter_events':None,
                'evaluation_support_seconds':[0,len(array)/50],'source_origin_shift_seconds':0,
                'annotation_caveat':'Human beat/downbeat labels; no waveform, exact tempo map, or metronome qualification.'}
            label=output/'labels'/(name+'.json');write_json(label,reference)
            records.append({'id':name,'dataset':'gtzan','genre':name.split('_')[1],
                'input':{'kind':'spectrogram','path':str(feature_path),'sha256':digest,'fps':50},
                'reference':{'path':str(label),'sha256':sha256(label)},'duration_seconds':len(array)/50,
                'group_id':name,'model_overlap':'publisher excludes GTZAN from final0 training',
                'target_scope':'supplementary beat/downbeat evaluation; original waveform and exact tempo map unavailable'})
            seen[digest]=name
    catalog={'schema_version':1,'dataset':'gtzan','role':'complete_available_supplementary_beat_probe',
        'selection':'all acquired annotations with matching distinct published feature bytes; no prediction-based selection',
        'acquired_annotation_count':len(annotations),'feature_archive_sha256':sha256(archive),
        'tracks':records,'excluded':excluded}
    write_json(output/'catalog.json',catalog)
    return catalog


def public_inventory():
    records=[];scoreable=[];unscored=[];seen={}
    for cohort,path,tier,can_score in PREFERRED_PUBLIC_CATALOGS:
        catalog=json.loads(path.read_text())
        for track in catalog['tracks']:
            source=Path(track['input']['path']);key=track['input']['sha256']
            if key in seen:
                raise ValueError(f'preferred catalogs duplicate audio: {track["id"]} and {seen[key]}')
            seen[key]=track['id']
            if sha256(source)!=key:raise ValueError(f'{track["id"]}: input hash mismatch')
            geometry=audio_geometry(source)
            reference=track.get('reference')
            reference_ok=False
            if reference:
                reference_ok=Path(reference['path']).is_file() and sha256(reference['path'])==reference['sha256']
                if not reference_ok:raise ValueError(f'{track["id"]}: reference hash mismatch')
            row={'id':track['id'],'cohort':cohort,'asset_class':'audio','audio_role':track.get('analysis_input_role',track.get('role','catalog_audio')),
                'input_path':str(source),'input_sha256':key,'geometry':geometry,'reference_tier':tier,
                'reference_path':reference['path'] if reference else None,'reference_verified':reference_ok,
                'score_admitted':bool(can_score and reference_ok),'source_catalog':str(path)}
            records.append(row)
            enriched={**track,'cohort':cohort,'reference_tier':tier}
            (scoreable if row['score_admitted'] else unscored).append(enriched)
    return records,scoreable,unscored,seen


def legacy_inventory(seen):
    catalog_path=Path('data/corpus/legacy/catalog.json');catalog=json.loads(catalog_path.read_text());rows=[]
    for track in catalog['audio']:
        source=Path(track['path']);digest=track['sha256']
        if digest in seen:raise ValueError(f'legacy duplicate: {track["id"]}')
        if sha256(source)!=digest:raise ValueError(f'legacy hash mismatch: {track["id"]}')
        rows.append({'id':'legacy_'+track['id'],'cohort':'legacy_regression','asset_class':'audio',
            'audio_role':'historical_regression','input_path':str(source),'input_sha256':digest,
            'geometry':audio_geometry(source),'reference_tier':'historical_unverified_tempo_only' if track['annotations'] else 'none',
            'reference_path':track['annotations'][0] if track['annotations'] else None,'reference_verified':False,
            'score_admitted':False,'source_catalog':str(catalog_path)})
        seen[digest]=track['id']
    return rows


def prepare(output):
    if output.exists():raise ValueError('output directory must be new')
    output.mkdir(parents=True)
    public,scoreable,unscored,seen=public_inventory()
    ntm_records=[]
    for track_id,root,role,producer in NTM:
        record,reference,geometry=ntm_reference(track_id,root,output)
        if record['input']['sha256'] in seen:raise ValueError(f'NTM duplicate: {track_id}')
        seen[record['input']['sha256']]=track_id;record['cohort']='ntm_user_reference';record['producer_group']=producer
        scoreable.append(record);ntm_records.append(record)
        public.append({'id':track_id,'cohort':'ntm_user_reference','asset_class':'audio','audio_role':role,
            'input_path':record['input']['path'],'input_sha256':record['input']['sha256'],'geometry':geometry,
            'reference_tier':'user_reviewed_tempo_map','reference_path':record['reference']['path'],
            'reference_verified':True,'score_admitted':True,'source_catalog':'owner acceptance.json'})
    legacy=legacy_inventory(seen);inventory=public+legacy
    if len(inventory)!=52 or len({r['input_sha256'] for r in inventory})!=52:
        raise ValueError(f'expected 52 unique audio assets, got {len(inventory)}')
    write_json(output/'catalog-scored-audio.json',{'schema_version':1,'role':'status_audit_scored_audio',
        'reference_policy':'Declared public references plus exact project-owner-approved NTM maps; no prediction-derived alignment.',
        'tracks':scoreable,'excluded':[]})
    write_json(output/'catalog-unscored-audio.json',{'schema_version':1,'role':'status_audit_prediction_only_audio',
        'tracks':unscored,'excluded':[]})
    gtzan=full_gtzan_catalog(output/'gtzan-all')
    with (output/'samples.csv').open('x',newline='',encoding='utf-8') as handle:
        fields=['id','cohort','audio_role','input_path','input_sha256','reference_tier','reference_path','reference_verified','score_admitted']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(inventory)
    write_json(output/'inventory.json',{'schema_version':1,'scope':'status audit inputs before inference',
        'audio_asset_count':len(inventory),'unique_audio_hash_count':len(seen),
        'score_admitted_audio_count':len(scoreable),'prediction_only_audio_count':len(inventory)-len(scoreable),
        'gtzan_annotation_count':gtzan['acquired_annotation_count'],'gtzan_scored_feature_count':len(gtzan['tracks']),
        'gtzan_excluded':gtzan['excluded'],'audio':inventory,
        'warnings':['Asset count is not an independent-song count.','GTZAN has no local waveform or exact tempo map.',
                    'Owner-approved NTM maps are scored as user-reviewed references without claiming original-click millisecond truth.']})
    write_json(output/'methods.json',{'schema_version':1,'goal':'fully automatic full-song tempo/meter maps','methods':METHODS,
        'no_single_production_default':True})
    source_files=('status_audit.py','run_corpus_benchmark.py','run_crossed_benchmark.py','compare_clock_candidates.py',
                  'grid_metrics.py','clock_candidates.py','fit_clock.py','decode_pulses.py','decode_bar_structure.py',
                  'tempo_prior.py','phase_alignment.py')
    write_json(output/'frozen-configuration.json',{'schema_version':1,'source_hashes':{
        name:sha256(Path(__file__).with_name(name)) for name in source_files},
        'beat_this_checkpoint':{'path':'data/models/beat-this/final0.ckpt','sha256':sha256('data/models/beat-this/final0.ckpt')},
        'beat_transformer_checkpoint':{'path':'data/models/beat-transformer/fold_4_trf_param.pt','sha256':sha256('data/models/beat-transformer/fold_4_trf_param.pt')},
        'prediction_reference_separation':True,'settings_tuned_for_this_audit':False})
    print(json.dumps({'output':str(output),'audio':len(inventory),'scoreable_audio':len(scoreable),
                      'gtzan':len(gtzan['tracks']),'gtzan_excluded':len(gtzan['excluded'])},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.output_dir)


if __name__=='__main__':main()
