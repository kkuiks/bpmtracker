"""Prepare a DAW candidate-review descriptor from existing source-clock records.

Reads only batch/source JSON. No acquisition, archive scan, audio decode/hash,
model run, alignment verification, acceptance or enrollment occurs here.
"""
import argparse
import json
import math
from pathlib import Path

if __package__:
    from .storage import SAMPLES, assert_candidate_allowed, save
else:
    from storage import SAMPLES, assert_candidate_allowed, save


def member(relative):
    path=(SAMPLES/relative).resolve()
    if not path.is_relative_to(SAMPLES.resolve()) or not path.is_file():
        raise RuntimeError("candidate_asset_must_exist_inside_data_samples")
    return path


def selected_records(batch, index):
    if 'tracks' in index:
        library=json.loads((SAMPLES/'ntm-library-index.json').read_text())
        identities={s['slug']:s for s in library['recordings']}
        assets=json.loads((batch/'assets.json').read_text())['assets']
        result=[]
        for item in index['tracks']:
            if item.get('group')!='candidate':
                continue
            if item['id'] not in identities:
                raise RuntimeError('candidate_not_in_source_registry')
            song=identities[item['id']]
            assert_candidate_allowed(song,'review')
            packet_path=member((batch/item['packet_url']).relative_to(SAMPLES))
            packet=json.loads(packet_path.read_text())
            if packet['id']!=song['slug'] or packet.get('group')!='candidate':
                raise RuntimeError('candidate_packet_identity_mismatch')
            geometry=None
            if not packet.get('available_map'):
                audio=member(packet['audio_path']);recorded=assets[packet['audio_url']]
                stat=audio.stat()
                if Path(recorded['path']).resolve()!=audio or stat.st_size!=recorded['size'] or stat.st_mtime_ns!=recorded['mtime_ns']:
                    raise RuntimeError('source_only_audio_geometry_snapshot_changed')
                geometry={k:packet[k] for k in ('duration_seconds','sample_rate','sample_frames','channels')}
                geometry['source_metadata']=packet_path.relative_to(SAMPLES).as_posix()
            result.append((song,dict(review=packet['reference_path'],audio=packet['audio_path'],
                geometry=geometry,description=packet.get('notes',''))))
        return result
    selection=json.loads((batch/'selection.json').read_text())
    identities={s['slug']:s for s in selection['songs']}
    result=[]
    for item in index.get('songs',[]):
        item_slug=next((s for s in identities if s in Path(item['review']).parts),None)
        if not item_slug:
            raise RuntimeError('review_record_has_no_selected_session_identity')
        result.append((identities[item_slug],item))
    for item in index.get('source_only_songs',[]):
        song=identities.get(item.get('slug'))
        if song is None:
            raise RuntimeError('source_only_record_has_no_selected_session_identity')
        assert_candidate_allowed(song,'review')
        home=SAMPLES/'ntm'/song['slug']/'collection'
        geometry_path=home/'master-geometry.json'
        geometry=json.loads(geometry_path.read_text()) if geometry_path.exists() else None
        result.append((song,dict(review=(home/'preparation-status.json').relative_to(SAMPLES).as_posix(),
            audio=item['audio'],geometry=geometry,description=item.get('description',''))))
    return result


def prepare_descriptor(batch, slug=None, out=None):
    batch=batch.resolve()
    if not batch.is_relative_to(SAMPLES.resolve()):
        raise RuntimeError("review_batch_must_stay_inside_data_samples")
    index=json.loads((batch/'index-data.json').read_text())
    catalog=json.loads((SAMPLES/'catalog.json').read_text())
    enrolled={t['id'] for t in catalog['tracks']}
    enrolled_session_homes={Path(t['audio']['path']).parts[1] for t in catalog['tracks']
        if len(Path(t['audio']['path']).parts)>1 and Path(t['audio']['path']).parts[0]=='ntm'}
    rows=[];unavailable=[];already_accepted=[]
    for song,item in selected_records(batch,index):
        item_slug=song['slug']
        if slug is not None and item_slug!=slug:
            continue
        assert_candidate_allowed(song,'review')
        path=member(item['review']);review=json.loads(path.read_text())
        if item_slug in enrolled or item_slug in enrolled_session_homes or review.get('human_alignment_accepted'):
            already_accepted.append(item_slug)
            continue
        if not review.get('tempo_events') or not review.get('meter_events') or not review.get('quarters') or not review.get('bars'):
            geometry=item.get('geometry')
            if not geometry:
                unavailable.append(dict(slug=item_slug,title=song['title'],reason='source_clock_missing_and_audio_geometry_not_prepared'))
                continue
            duration=geometry.get('duration_seconds')
            if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
                raise RuntimeError('source_only_record_requires_finite_duration')
            member(item['audio'])
            rows.append(dict(id=item_slug,slug=item_slug,session_id=song.get('session_id'),title=song['title'],
                audio_path=item['audio'],reference_path=item['review'],review_mode='source_only',
                source_audio_geometry=geometry,duration_seconds=duration,initial_offset_seconds=None,
                status='source_only_pending_owner_review',previously_accepted=False,
                source_clock_available=False,source_offset_alternatives=[],
                description=item.get('description') or 'No supplied tempo/signature clock. Listen to the original recording and save a separate manual draft.'))
            continue
        offset=review.get('initial_offset_seconds',0)
        duration=review.get('duration_seconds')
        extent=review.get('project_end_seconds')
        if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (offset,duration,extent)) or duration<=0:
            raise RuntimeError("candidate_review_requires_finite_offset_duration_and_source_extent")
        member(review['audio'])
        rows.append(dict(id=item_slug,slug=item_slug,session_id=song.get('session_id'),
            title=review['title'],audio_path=review['audio'],reference_path=item['review'],
            initial_offset_seconds=offset,source_time_scale=1.0,
            review_mode='supplied_clock',source_clock_available=True,
            status='candidate_pending_owner_review',previously_accepted=False,
            source_clock_label=review.get('clock_label'),
            source_offset_alternatives=review.get('candidates',[]),
            description=review.get('description','')))
    result=dict(format='joljak-candidate-review',schema_version=1,
        paths_relative_to='data/samples',source_batch=batch.relative_to(SAMPLES).as_posix(),
        recordings=rows,counts=dict(supplied_clock=sum(r['source_clock_available'] for r in rows),
            source_only=sum(not r['source_clock_available'] for r in rows)),
        unavailable=unavailable,already_accepted_use_formal_library=already_accepted,
        acquisition_is_not_enrollment=True,owner_acceptance_pending=bool(rows),
        catalog_and_accepted_references_unchanged=True)
    destination=Path(out).resolve() if out is not None else batch
    if not destination.is_relative_to(SAMPLES.resolve()):
        raise RuntimeError('review_output_must_stay_inside_data_samples')
    destination.mkdir(parents=True,exist_ok=True)
    output=destination/'daw-review.json'
    save(output,result)
    return dict(daw_review=str(output.relative_to(SAMPLES)),candidates_prepared=len(rows),
        counts=result['counts'],unavailable=unavailable,already_accepted=already_accepted,
        next_step='Joljak: Samples > Open candidate review > daw-review.json')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--slug')
    parser.add_argument('--out',type=Path,help='Separate descriptor directory inside data/samples')
    args=parser.parse_args()
    print(json.dumps(prepare_descriptor(args.batch,args.slug,args.out),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
