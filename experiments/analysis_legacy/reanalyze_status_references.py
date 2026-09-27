"""Reaudit preserved references and corpus assets without changing musical labels.

All alternate-label scores are diagnostics from already saved predictions. The
primary GTZAN sensitivity excludes conflicting feature clusters; it never picks
an annotation by its agreement with a model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
import subprocess
from pathlib import Path
import zipfile

import numpy as np
import soundfile as sf

from audit_status_references import reference_content, validate
from inspect_inputs import sha256
from prepare_public_corpus import read_published_beats
from synthetic_groove import event_metrics

TOLERANCES=(.01,.02,.03,.07)
AUDIO_SUFFIXES={'.wav','.mp3','.flac','.aif','.aiff','.ogg','.m4a'}
MAP_SUFFIXES={'.mid','.midi','.rpp','.cpr','.ptx','.song','.smt'}
ARCHIVE_SUFFIXES={'.zip','.rar','.gz','.npz'}


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def artifact(path):
    return {'path':str(path),'sha256':sha256(path)}


def map_consistency(reference):
    """Internal arithmetic only; does not certify acoustic/musical correspondence."""
    tempos=reference.get('tempo_events') or []
    if not tempos:return {'status':'not_applicable_no_tempo_map'}
    def quarter_at(time):
        total=0.
        for index,event in enumerate(tempos):
            start=event['time_seconds']
            if time<=start:break
            stop=tempos[index+1]['time_seconds'] if index+1<len(tempos) else time
            total+=(min(time,stop)-start)*event['bpm_quarter']/60.
        return total
    quarters=np.array([quarter_at(t) for t in reference['beats_seconds']])
    residual=np.abs(np.diff(quarters)-1.)
    downbeat_residual=[];meters=reference.get('meter_events') or []
    for time in reference.get('downbeats_seconds') or []:
        candidates=[e for e in meters if e['time_seconds']<=time+1e-9]
        if not candidates:continue
        meter=candidates[-1]
        phase=(quarter_at(time)-quarter_at(meter['time_seconds']))/(4*meter['numerator']/meter['denominator'])
        downbeat_residual.append(abs(phase-round(phase)))
    return {'status':'internal_arithmetic_checked_not_musical_certification',
        'quarter_interval_max_error':float(residual.max()) if len(residual) else None,
        'downbeat_declared_reset_phase_max_error':max(downbeat_residual,default=None),
        'quarter_interval_consistent_1e_5':bool(np.all(residual<1e-5)),
        'downbeat_consistent_1e_5':all(v<1e-5 for v in downbeat_residual)}


def capability_counts(rows):
    return {'reference_count':len(rows),
        **{key:sum(row['score_capabilities'][key] for row in rows)
           for key in ('beat_events','downbeat_events','tempo_change_scoring','meter_change_scoring')},
        **{kind+'_change_positive_in_support':sum(bool(row['reference_content'][kind]['changes_in_support']) for row in rows)
           for kind in ('tempo','meter')},
        **{kind+'_actual_change_events_in_support':sum(len(row['reference_content'][kind]['changes_in_support']) for row in rows)
           for kind in ('tempo','meter')}}


def audit_references(audit_root):
    catalog_path=audit_root/'catalog-scored-audio.json';catalog=read_json(catalog_path)
    decision_path=audit_root/'reference-review-batch1-v2/owner-decisions.json'
    decisions=read_json(decision_path);by_id={t['id']:t for t in catalog['tracks']};rejected={}
    if decisions.get('model_predictions_included') is not False:raise ValueError('reference decisions are not prediction blind')
    for item in decisions['items']:
        track=by_id[item['id']]
        if item['audio_sha256']!=track['input']['sha256'] or item['reference_sha256']!=track['reference']['sha256']:
            raise ValueError('owner decision hash mismatch')
        if item['decision']!='reject_current_reference_for_accuracy_scoring':raise ValueError('unsupported owner decision')
        rejected[item['id']]=item
    semantic=read_json('data/runs/reference-audit/babyslakh-v1/report.json')
    semantic_flags={t['id']:t['qualification']['review_flags'] for t in semantic['tracks']}
    rows=[]
    for track in catalog['tracks']:
        row=validate(track,semantic_flags.get(track['id']))
        reference=read_json(track['reference']['path'])
        row.update(audio=track['input'],reference=track['reference'],group_id=track.get('group_id'),
            retained_for_primary_scores=track['id'] not in rejected,
            owner_decision=rejected.get(track['id']),internal_consistency=map_consistency(reference),
            confidence_status='retained_declared_reference_with_tier_limits' if track['id'] not in rejected else 'owner_rejected_do_not_score',
            reference_caveats={k:reference[k] for k in ('annotation_caveat','source_alignment','meter_reference_status',
                'downbeat_label_status','recorded_to_this_click_status','full_song_listening_passed','listening_coverage',
                'unit','outside_click_span_status','mapped_tail_status') if k in reference})
        if track.get('acceptance'):
            acceptance_path=Path(track['acceptance']['path']);accepted=read_json(acceptance_path)
            map_path=acceptance_path.parent/'tempo-aligned.json';aligned=read_json(map_path)
            quarters=aligned.get('quarter_events',aligned.get('quarters'))
            selected=[q for q in quarters if 0<=q['master_seconds']<row['audio_geometry']['duration_seconds']]
            row['owner_map_preservation']={'acceptance':artifact(acceptance_path),'aligned_map':artifact(map_path),
                'aligned_map_hash_matches_acceptance':sha256(map_path)==accepted['aligned_map']['sha256'],
                'quarter_times_exactly_preserved':[q['master_seconds'] for q in selected]==reference['beats_seconds'],
                'downbeat_times_exactly_preserved':[q['master_seconds'] for q in selected if q.get('accent')]==reference['downbeats_seconds'],
                'offset_seconds':accepted['offset_seconds'],'status':accepted['status']}
        rows.append(row)
    retained=[r for r in rows if r['retained_for_primary_scores']]
    return {'schema_version':2,'catalog':artifact(catalog_path),'owner_decisions':artifact(decision_path),
        'policy':'Owner rejections remain excluded; retained does not mean semantically certified. Constant maps can score false changes.',
        'change_policy':'Actual changes require different values and lo < event time < hi. Repeated meter declarations are separately retained as possible bar resets.',
        'all_supplied_capability_counts':capability_counts(rows),'retained_capability_counts':capability_counts(retained),
        'retained_by_cohort':{cohort:capability_counts([r for r in retained if r['cohort']==cohort]) for cohort in sorted({r['cohort'] for r in retained})},
        'rejected_ids':sorted(rejected),'tracks':rows,'structural_failures':[r['id'] for r in rows if not r['valid']],
        'new_owner_review_questions':[],
        'owner_review_note':'No new decisive musical question established. Do not repeat the three rejected-reference reviews or four accepted NTM offsets.'}


def classify_annotation_pair(a,b,timing_limit=.010):
    """Classify published labels without predictions or a correctness preference."""
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    for values in (a,b):
        if values.ndim!=2 or values.shape[1]!=2 or not np.isfinite(values).all() or np.any(np.diff(values[:,0])<=0):
            raise ValueError('invalid published annotation')
    ratio=len(b)/len(a) if len(a) else None
    if a.shape==b.shape and np.array_equal(a,b):kind='identical_parsed_labels'
    elif a.shape==b.shape and np.array_equal(a[:,1],b[:,1]) and np.max(abs(a[:,0]-b[:,0]),initial=0)<=timing_limit:
        kind='same_events_timing_difference_at_most_10ms'
    elif ratio is not None and any(abs(ratio-target)<=.1*target for target in (.5,2.)):
        kind='pulse_count_half_or_double_conflict'
    elif a.shape==b.shape and np.array_equal(a[:,0],b[:,0]):kind='bar_position_label_conflict'
    elif len(a)!=len(b):kind='event_count_conflict'
    else:kind='event_timing_or_bar_position_conflict'
    conflict=kind not in ('identical_parsed_labels','same_events_timing_difference_at_most_10ms')
    return {'classification':kind,'conflicting':conflict,'retained_event_count':len(a),'alternative_event_count':len(b),
        'count_ratio':ratio,'same_index_max_timing_difference_seconds':float(np.max(abs(a[:,0]-b[:,0]),initial=0)) if len(a)==len(b) else None,
        'timing_only_limit_seconds':timing_limit}


def score_annotation(prediction,annotation,duration):
    values=np.asarray(annotation,dtype=float);out={}
    for key,truth in [('beats_seconds',values[:,0]),('downbeats_seconds',values[values[:,1]==1,0])]:
        estimated=np.asarray(prediction[key],dtype=float)
        truth=truth[(truth>=0)&(truth<=duration)];estimated=estimated[(estimated>=0)&(estimated<=duration)]
        out[key]={str(tolerance):event_metrics(truth,estimated,tolerance) for tolerance in TOLERANCES}
    return out


def saved_score_summary(rows):
    output={}
    for method in ('official_minimal','legacy_dbn','clock_pipeline'):
        downbeat_rows=[r for r in rows if r['scores'][method]['annotated_span']['downbeats_seconds'] is not None]
        output[method]={'track_count':len(rows),'downbeat_track_count':len(downbeat_rows),
            'macro_beat_f1':{str(tolerance):float(np.mean([r['scores'][method]['annotated_span']['beats_seconds'][str(tolerance)]['f1'] for r in rows])) if rows else None for tolerance in TOLERANCES},
            'macro_downbeat_f1':{str(tolerance):float(np.mean([r['scores'][method]['annotated_span']['downbeats_seconds'][str(tolerance)]['f1'] for r in downbeat_rows])) if downbeat_rows else None for tolerance in TOLERANCES}}
    return output


def audit_gtzan(audit_root):
    catalog_path=audit_root/'gtzan-all/catalog.json';catalog=read_json(catalog_path)
    prediction_path=audit_root/'beat-this-gtzan985/report.json';report=read_json(prediction_path)
    predictions={t['id']:t for t in report['tracks']};tracks={t['id']:t for t in catalog['tracks']}
    annotations={p.stem:p for p in Path('data/corpus/public/gtzan-development/published-annotations').glob('*/gtzan/annotations/beats/*.beats')}
    pairs=[];archive_path=Path('data/corpus/public/gtzan-development/published-features/gtzan.npz')
    with zipfile.ZipFile(archive_path) as archive:
        for excluded in catalog['excluded']:
            if excluded['reason']!='duplicate exact feature bytes':continue
            retained=excluded['duplicate_of'];alternative=excluded['id'];pa=annotations[retained];pb=annotations[alternative]
            a=np.loadtxt(pa,ndmin=2);b=np.loadtxt(pb,ndmin=2);details=classify_annotation_pair(a,b)
            ha=hashlib.sha256(archive.read(retained+'/track.npy')).hexdigest()
            hb=hashlib.sha256(archive.read(alternative+'/track.npy')).hexdigest()
            if ha!=hb or ha!=tracks[retained]['input']['sha256'] or ha!=predictions[retained]['input_sha256']:
                raise ValueError('duplicate feature or saved prediction identity mismatch')
            pairs.append({'retained_id':retained,'alternative_id':alternative,'feature_sha256':ha,
                'retained_annotation':artifact(pa),'alternative_annotation':artifact(pb),
                'byte_identical_annotations':pa.read_bytes()==pb.read_bytes(),**details,
                'diagnostic_only_no_preferred_label':True,
                'saved_prediction_scores':{method:{'retained_labels':score_annotation(prediction,a,tracks[retained]['duration_seconds']),
                    'alternative_labels':score_annotation(prediction,b,tracks[retained]['duration_seconds'])}
                    for method,prediction in predictions[retained]['variants'].items()}})
    conflict_ids={p['retained_id'] for p in pairs if p['conflicting']}
    nonidentical={p['retained_id'] for p in pairs if p['classification']!='identical_parsed_labels'}
    return {'schema_version':1,'catalog':artifact(catalog_path),'saved_predictions':artifact(prediction_path),
        'feature_archive':artifact(archive_path),'inference_rerun':False,
        'policy':'No alternative label is chosen using model scores. Exclude conflicting exact-feature clusters in the primary reference-sensitivity view; preserve all historical scores.',
        'conflict_policy':'Count/pulse/bar conflicts or same-index timing difference above10ms. Also disclose sensitivity excluding every nonidentical annotation cluster;10ms is a disclosure boundary, not truth certification.',
        'pair_classification_counts':dict(Counter(p['classification'] for p in pairs)),
        'conflicting_retained_ids':sorted(conflict_ids),'all_nonidentical_retained_ids':sorted(nonidentical),
        'supplementary_original_985':saved_score_summary(report['tracks']),
        'primary_reference_sensitivity_excluding_conflicting_clusters':saved_score_summary([r for r in report['tracks'] if r['id'] not in conflict_ids]),
        'sensitivity_excluding_all_nonidentical_label_clusters':saved_score_summary([r for r in report['tracks'] if r['id'] not in nonidentical]),
        'pairs':pairs,'remaining_limit':'Exact feature uniqueness is not composition independence; no original audio is available for resolving the human annotation conflicts.'}


def classify_audio(path,catalog_record=None):
    name=path.name.lower();text=str(path).lower()
    if catalog_record:
        cohort=catalog_record['cohort']
        return {'babyslakh':'synthetic_mix','groove':'drum_performance','legacy_regression':'historical_regression',
            'ntm_user_reference':'finished_master','daybreak':'producer_reference_mix',
            'forestry_creator':'producer_instrumental','forestry_observed_click':'producer_instrumental','walker':'producer_instrumental'}.get(cohort,'catalog_analysis_audio')
    if 'listen-aligned' in name or 'music-with-' in name or 'audition' in name:return 'generated_review_mix'
    if 'click' in name:return 'generated_click' if 'aligned' in name else 'source_click'
    if 'master-original' in name:return 'original_encoding_of_catalog_master'
    if '/stems/' in text:return 'instrument_stem'
    if name=='reference mix.wav':return 'producer_reference_mix'
    if any(word in name for word in ('drum','guitar','bass','synth','pad ','zombass')):return 'instrument_stem'
    return 'unclassified_audio_requires_catalog_association'


def decode_audio(path):
    """Read the complete decoded stream; count/finiteness is not listening QC."""
    try:
        with sf.SoundFile(path) as handle:
            expected=handle.frames;rate=handle.samplerate;channels=handle.channels;count=0;finite=True
            while True:
                block=handle.read(65536,dtype='float32',always_2d=True)
                if not len(block):break
                count+=len(block);finite=finite and bool(np.isfinite(block).all())
        status='complete' if count==expected and finite and count>0 else 'frame_or_finiteness_failure'
        if finite and count>0 and count!=expected and path.suffix.lower()=='.mp3':
            status='decoded_stream_complete_header_frame_estimate_differs'
        return {'status':status,
            'header_frames':expected,'decoded_frames':count,'sample_rate':rate,'channels':channels,'all_samples_finite':finite}
    except (RuntimeError,ValueError,OSError) as error:
        return {'status':'decode_failed','error_type':type(error).__name__,'error':str(error)}


def is_appledouble(path):
    if not path.name.startswith('._'):return False
    with path.open('rb') as stream:return stream.read(4)==b'\x00\x05\x16\x07'


def ffmpeg_frame_count(path,channels):
    command=['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),'-map','0:a:0',
        '-f','f32le','-acodec','pcm_f32le','-']
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    count=0
    while data:=process.stdout.read(1024*1024):count+=len(data)
    error=process.stderr.read().decode('utf-8',errors='replace');code=process.wait()
    return {'exit_code':code,'decoded_frames':count//(4*channels),
        'sample_bytes_divisible':count%(4*channels)==0,'error':error,
        'purpose':'Independent complete decode length; header difference alone does not establish damaged audio.'}


def scan_assets(audit_root,roots,reuse_assets=None):
    inv_path=audit_root/'inventory.json';inventory=read_json(inv_path)
    known={str(Path(t['input_path']).resolve()):t for t in inventory['audio']}
    reused={r['path']:r for r in read_json(reuse_assets)['files']} if reuse_assets else {}
    declared_hashes={t['input_sha256']:t['id'] for t in inventory['audio']}
    rows=[];audio=[];maps=[];incomplete=[];archives=[];seen_paths=set();errors=[];empty_directories=[]
    for root in roots:
        for base,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if not Path(base,d).is_symlink()]
            if not dirs and not files:empty_directories.append(str(base))
            for name in sorted(files):
                path=Path(base,name)
                if path.is_symlink():continue
                resolved=str(path.resolve())
                if resolved in seen_paths:continue
                seen_paths.add(resolved)
                try:size=path.stat().st_size
                except OSError as error:errors.append({'path':str(path),'error':str(error)});continue
                suffix=path.suffix.lower();row={'path':str(path),'bytes':size,'suffix':suffix}
                if is_appledouble(path):
                    row.update(asset_class='filesystem_metadata_sidecar',sha256=sha256(path),counted_as_audio=False)
                elif suffix in AUDIO_SUFFIXES:
                    record=known.get(resolved);digest=sha256(path)
                    cached=reused.get(str(path))
                    if cached and cached.get('sha256')==digest and cached.get('decode'):
                        decoded=dict(cached['decode'])
                        if (decoded['status']=='frame_or_finiteness_failure' and suffix=='.mp3'
                                and decoded.get('all_samples_finite') and decoded.get('decoded_frames',0)>0):
                            decoded['status']='decoded_stream_complete_header_frame_estimate_differs'
                        decoded['reused_from']=artifact(reuse_assets)
                    else:decoded=decode_audio(path)
                    if decoded['status']=='decoded_stream_complete_header_frame_estimate_differs':
                        decoded['ffmpeg_check']=ffmpeg_frame_count(path,decoded['channels'])
                        decoded['ffmpeg_frame_count_agrees']=decoded['ffmpeg_check']['decoded_frames']==decoded['decoded_frames']
                    row.update(asset_class='audio',sha256=digest,role=classify_audio(path,record),
                        catalog_id=record['id'] if record else declared_hashes.get(digest),
                        catalog_path_match=record is not None,not_a_new_independent_track=True,
                        decode=decoded)
                    if record:row['frozen_hash_matches']=digest==record['input_sha256']
                    audio.append(row)
                elif suffix in MAP_SUFFIXES:
                    row.update(asset_class='midi_or_project',sha256=sha256(path));maps.append(row)
                elif suffix=='.incomplete-transfer':
                    row.update(asset_class='incomplete_transfer',sha256=sha256(path),
                        decoded_as_audio=False,counted_as_new_track=False);incomplete.append(row)
                elif suffix in ARCHIVE_SUFFIXES:
                    row.update(asset_class='archive_or_feature_container',sha256=sha256(path))
                    if suffix in ('.zip','.npz'):
                        try:
                            with zipfile.ZipFile(path) as archive:
                                members=archive.infolist();row['archive_member_count']=len(members)
                                row['contained_audio_count']=sum(Path(m.filename).suffix.lower() in AUDIO_SUFFIXES for m in members)
                                row['contained_map_count']=sum(Path(m.filename).suffix.lower() in MAP_SUFFIXES for m in members)
                                row['member_roster']=[{'name':m.filename,'bytes':m.file_size,'crc32':m.CRC} for m in members]
                            row['archive_status']='roster_read_no_extraction_no_additional_track_claim'
                        except zipfile.BadZipFile:row['archive_status']='invalid_zip'
                    else:row['archive_status']='preserved_not_extracted_or_admitted'
                    archives.append(row)
                elif suffix=='.json':
                    row['asset_class']='annotation_or_metadata'
                    try:content=read_json(path)
                    except (ValueError,OSError):content=None
                    if isinstance(content,dict) and any(k in content for k in ('tempo_events','beats_seconds','quarter_events')):
                        row.update(asset_class='tempo_or_beat_map_json',sha256=sha256(path));maps.append(row)
                else:row['asset_class']='annotation_or_metadata' if suffix in ('.beats','.yaml','.split') else 'other_supporting_file'
                rows.append(row)
    hashes=defaultdict(list)
    for row in audio:hashes[row['sha256']].append(row['path'])
    duplicate_groups=[{'sha256':key,'paths':values} for key,values in hashes.items() if len(values)>1]
    for row in maps:
        path=Path(row['path']);parent=path.parent
        # This is only association evidence, never a musical-origin claim.
        local_audio=[a['path'] for a in audio if Path(a['path']).parent==parent]
        row['same_directory_audio']=local_audio
        row['association_status']='sibling_audio_present_association_not_certified' if local_audio else 'no_sibling_audio_check_package_or_catalog'
        row['counted_as_new_track']=False
        if 'animal-metadata' in str(path):row['association_status']='known_orphan_map_no_acquired_full_mix'
        elif 'i-wonder-as-i-wander' in str(path):row['association_status']='map_only_candidate_no_acquired_audio_in_package'
    return {'schema_version':1,'frozen_inventory':artifact(inv_path),'scan_roots':[str(p) for p in roots],
        'scope':'Every regular file below these corpus/source roots, without following symlink directories. Generated data/runs, model caches and archive/legacy code are not corpus roots. Archives are inventoried but not extracted.',
        'regular_file_count':len(rows),'audio_file_count':len(audio),'distinct_audio_byte_hash_count':len(hashes),
        'catalog_audio_path_count':sum(a['catalog_path_match'] for a in audio),
        'catalog_audio_hash_mismatches':[a['path'] for a in audio if a.get('frozen_hash_matches') is False],
        'missing_catalog_paths':[r['input_path'] for key,r in known.items() if key not in seen_paths],
        'audio_role_counts':dict(Counter(a['role'] for a in audio)),
        'decode_status_counts':dict(Counter(a['decode']['status'] for a in audio)),
        'unclassified_audio':[a['path'] for a in audio if a['role']=='unclassified_audio_requires_catalog_association'],
        'exact_audio_duplicate_groups':duplicate_groups,'map_or_project_count':len(maps),
        'incomplete_input_count':len(incomplete),'archive_count':len(archives),
        'scan_errors':errors,'empty_directories':empty_directories,'files':rows,
        'interpretation':'File count and byte uniqueness are not song independence. Stems, clicks, review renders and original encodings do not enlarge the analysis-track cohort.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-root',type=Path,default=Path('data/runs/status-audit/2026-09-25-v1'))
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--scan-root',action='append',type=Path)
    parser.add_argument('--reuse-assets',type=Path,help='Reuse complete decode evidence only when current audio bytes still match.')
    args=parser.parse_args()
    if args.output_dir.exists():raise ValueError('output directory must be new to preserve snapshots')
    roots=args.scan_root or [Path('data/corpus'),Path('/mnt/d/NailTheMix')]
    references=audit_references(args.audit_root)
    gtzan=audit_gtzan(args.audit_root)
    assets=scan_assets(args.audit_root,roots,args.reuse_assets)
    write_json(args.output_dir/'references.json',references)
    write_json(args.output_dir/'gtzan-annotation-conflicts.json',gtzan)
    write_json(args.output_dir/'corpus-assets.json',assets)
    write_json(args.output_dir/'manifest.json',{'schema_version':1,
        'sources':{name:artifact(Path(__file__).with_name(name)) for name in ('reanalyze_status_references.py','audit_status_references.py')},
        'references':artifact(args.output_dir/'references.json'),
        'gtzan':artifact(args.output_dir/'gtzan-annotation-conflicts.json'),
        'assets':artifact(args.output_dir/'corpus-assets.json'),
        'reference_maps_modified':False,'predictions_modified':False,'inference_rerun':False})
    print(json.dumps({'retained':references['retained_capability_counts'],
        'gtzan_conflicts':len(gtzan['conflicting_retained_ids']),
        'audio_files':assets['audio_file_count'],'decode':assets['decode_status_counts'],
        'hash_mismatches':assets['catalog_audio_hash_mismatches']},ensure_ascii=False))


if __name__=='__main__':main()
