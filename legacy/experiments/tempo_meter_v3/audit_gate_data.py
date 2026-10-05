"""Inventory existing review assets; no admission, acquisition or scoring."""
import argparse
import json
from pathlib import Path
from .probe_resources import digest


def audit(root):
    def read(path):
        return json.loads((root/path).read_text())
    entries=[]
    source_manifests=[]
    primary='data/corpus/primary-references-v6/catalog.json'
    source_manifests.append(primary)
    for row in read(primary)['tracks']:
        entries.append(dict(id=row['id'],role='finished_recording_development',
            audio=row['canonical_audio']['path'],audio_expected=row['canonical_audio']['sha256'],
            reference=row['accepted_tempo_map']['path'],reference_expected=row['accepted_tempo_map']['sha256'],
            qualification=row.get('qualification'),scope_note='Retain original acceptance and scoped policy; not unseen.'))
    for name in ['ntm-three-owner-acceptance-20260930-v1','ntm-deadman-opeth-acceptance-20260930-v1']:
        f='data/runs/reference-audit/'+name+'/accepted-catalog-v1.json';source_manifests.append(f)
        for row in read(f)['rows']:
            ref=Path(row['reference_path']);audio=ref.parent/'master.wav'
            entries.append(dict(id=row['id'],role='finished_recording_development',audio=str(audio),
                audio_expected=row.get('audio_sha256'),reference=str(ref),reference_expected=row['reference_sha256'],
                scope=row.get('scope',row.get('reviewed_audio_span_seconds')),
                scope_note=row.get('meter_interpretation',{})))
    f='data/runs/reference-audit/wage-war-owner-acceptance-20260930-v1/owner-acceptance.json';source_manifests.append(f)
    row=read(f)
    job=Path('/mnt/d/NailTheMix/processed/will-carlson-wage-war-song-of-the-swamp')
    entries.append(dict(id='wage_war',role='finished_recording_development',audio=str(job/'master.wav'),
        audio_expected=row['source_sha256'],reference=str(job/'tempo-owner-accepted-v1.json'),
        reference_expected=row['primary_map_sha256'],scope=row['scope_seconds'],
        scope_note='B is primary; earlier per-song alternative whitelist is not adopted.'))
    f='data/corpus/public/five-source-small-pilot-20260929-v1/accepted-catalog-v1.json';source_manifests.append(f)
    for row in read(f)['rows']:
        folder=root/Path(f).parent
        entries.append(dict(id=row['id'],role=row['role'],audio=str(folder/row['id']/'audio.wav'),
            audio_expected=row['audio_sha256'],reference=str(folder/row['accepted_clock']),
            reference_expected=row['accepted_clock_sha256'],scope=row['support_seconds'],
            qualification=row['evaluation_eligibility']))
    for e in entries:
        if not e.get('audio_expected') and Path(e['reference']).is_file():
            e['audio_expected']=json.loads(Path(e['reference']).read_text()).get('master_sha256')
        for kind in ('audio','reference'):
            p=Path(e[kind]);p=p if p.is_absolute() else root/p
            e[kind]=str(p.resolve());e[kind+'_exists']=p.is_file()
            actual=digest(p) if p.is_file() else None
            e[kind+'_sha256']=actual
            e[kind+'_hash_matches']=actual==e.get(kind+'_expected') if e.get(kind+'_expected') else None
        e['training_admission']='not_granted_by_this_inventory'
    baby=[]
    for name in ['catalog.json','catalog-rendered-clock.json']:
        f='data/corpus/public/babyslakh-development/'+name;source_manifests.append(f)
        cat=read(f)
        fields=[]
        for row in cat['tracks']:
            label=read(row['reference']['path'])
            fields.append(dict(id=row['id'],reference_hash_matches=digest(root/row['reference']['path'])==row['reference']['sha256'],
                beat_events=len(label.get('beats_seconds') or []),bar_events=len(label.get('downbeats_seconds') or []),
                downbeat_label_status=label.get('downbeat_label_status'),grouping_supervision=False,
                absolute_audio_clock_supervision='pending_renderer_and_attack_audit',caveat=label.get('annotation_caveat')))
        baby.append(dict(label_fields=fields,catalog=f,rows=len(cat['tracks']),excluded=cat.get('excluded'),
            audio_files_present=sum((root/r['input']['path']).is_file() for r in cat['tracks']),
            reference_files_present=sum((root/r['reference']['path']).is_file() for r in cat['tracks']),
            rows_with_multiple_tempo_declarations=sum(r.get('tempo_event_count',0)>1 for r in cat['tracks']),
            rows_with_multiple_meter_declarations=sum(r.get('meter_event_count',0)>1 for r in cat['tracks']),
            groups=len({r['group_id'] for r in cat['tracks']}),
            qualification='Metadata declaration counts, not verified audible change counts. Reaudit pulse units, renderer origin and ambiguous 09/12/20 before field-specific training.'))
    return dict(kind='gate1_existing_asset_inventory',rows=entries,
        finished_recordings=sum(e['role']=='finished_recording_development' for e in entries),
        auxiliary=len(entries)-sum(e['role']=='finished_recording_development' for e in entries),
        all_files_present=all(e['audio_exists'] and e['reference_exists'] for e in entries),
        known_hashes_match=all(e[k+'_hash_matches'] is not False for e in entries for k in ('audio','reference')),
        source_manifests=[dict(path=f,sha256=digest(root/f)) for f in source_manifests],
        babyslakh_catalogs=baby,
        next_batch_proposal=[
            'Reuse BabySlakh raw MIDI/audio; inspect 00005 changes and 09/12/20 ambiguity, no automatic field admission.',
            'RWC public audio/annotation expansion after gate 1; P002 alone is currently in accepted intake. Beat annotations do not alone certify denominator or producer clock.',
            'Choose a small version-matched uncommon-meter subset after annotation audit. No audio acquisition claimed.',
            'Twenty reviewed recordings remain development/regression; GuitarSet is auxiliary. New blind cohort is not yet acquired.'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    result=audit(a.root.resolve());a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('finished_recordings','auxiliary','all_files_present','known_hashes_match')}))
    if not result['all_files_present'] or not result['known_hashes_match']:raise SystemExit(1)


if __name__=='__main__':main()
