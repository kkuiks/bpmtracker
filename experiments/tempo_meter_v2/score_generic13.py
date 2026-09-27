"""Evaluate a frozen generic source-only route on the thirteen reviewed songs.

This process opens accepted references only after the supplied prediction
manifest is complete. It retains the original eleven-song and Walker scorers'
contracts, including false positives, owner source-start equivalence, and the
explicit click-free ending gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from .score_primary8 import (_meter_changes, _source_geometry, read_bound,
                             reference_map, score_arm)
from .score_primary11 import bar_f1_70ms, change_gate
from .score_observational_equivalence_probe import (
    optional_source_start_changes, revised_meter_metric)
from .score_scoped_primary import reference_raw, score_scoped

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'analysis_legacy'))
from music_map_contract import prepare_map

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/corpus/primary-references-v6/catalog.json'


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def frozen(binding: dict) -> dict:
    path=Path(binding['path'])
    if digest(path)!=binding['sha256']:
        raise ValueError(f'prediction hash changed: {path}')
    return json.loads(path.read_text())


def normal_score(reference: dict, prediction: dict, ref_beats: list[float],
                 owner_equivalence: bool) -> dict:
    ref=prepare_map(reference)
    raw=score_arm(ref,prediction,ref_beats,minimum_tempo_change_bpm=1e-6)
    beat=raw['quarter_grid_event_70ms']
    bar=next(item['bar_boundaries']['scores'] for item in raw['music_map_components']['timing_profiles']
             if item['tolerance_seconds']==.07)
    tempo=raw['tempo_change_500ms']['full_change_scores']
    meter=raw['meter_change_500ms']
    optional=[];neutralized=[]
    if owner_equivalence:
        candidate=prepare_map(prediction['map']) if prediction.get('map') else None
        ref_change=_meter_changes(ref,ref['support_seconds'])
        predicted_change=(_meter_changes(candidate,candidate['support_seconds'])
                          if candidate and candidate['support_seconds'] else [])
        optional=optional_source_start_changes(ref)
        meter,neutralized=revised_meter_metric(ref_change,predicted_change,optional)
    scores={
        'quarter_bpm_time_within_1':raw['duration']['quarter_bpm_within_1_reference_fraction'],
        'reviewed_meter_paired_bar_fraction_70ms':raw['reviewed_paired_meter_bar_fraction_at70ms'],
        'declared_quarter_grid_f1_70ms':beat['f1'],
        'bar_boundary_f1_70ms':bar_f1_70ms(raw),
        'tempo_change_f1_or_no_false_positives_500ms':change_gate(tempo),
        'meter_change_f1_or_no_false_positives_500ms':change_gate(meter),
    }
    gates={key:value is not None and value>=.9 for key,value in scores.items()}
    return {
        'scores':scores,'gates':gates,
        'all_gates_pass':raw['map_render_status']=='rendered' and all(gates.values()),
        'beat_counts':{key:beat[key] for key in ('true_positives','false_positives','false_negatives')},
        'bar_counts':{key:bar[key] for key in ('true_positives','false_positives','false_negatives')},
        'tempo_change_counts':{key:tempo[key] for key in ('true_positives','false_positives','false_negatives')},
        'meter_change_counts':{key:meter[key] for key in ('true_positives','false_positives','false_negatives')},
        'optional_source_start_events':optional,
        'neutralized_predicted_events':neutralized,
        'strict_meter_change_gate':change_gate(raw['meter_change_500ms']),
        'coverage_fraction':raw['duration']['coverage_fraction'],
        'full_score':raw,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError('new evaluation output required')
    manifest=json.loads(args.manifest.read_text())
    catalog=json.loads(CATALOG.read_text())
    if (not manifest.get('complete') or manifest.get('references_available_to_runner') is not False or
            len(manifest.get('rows',[]))!=13 or catalog.get('track_count')!=13):
        raise ValueError('frozen thirteen-source predictions and catalog required')
    predictions={row['id']:row for row in manifest['rows']}
    if len(predictions)!=13 or set(predictions)!={row['id'] for row in catalog['tracks']}:
        raise ValueError('prediction/catalog identity mismatch')
    results=[]
    for track in catalog['tracks']:
        source=_source_geometry(track)
        record=predictions[track['id']]
        if source!=record['source']:
            raise ValueError('source audio identity/geometry mismatch')
        accepted=read_bound(track['accepted_tempo_map'])
        read_bound(track['owner_acceptance'])
        selected_binding=record['predictions']['selected']
        selected=frozen(selected_binding)
        tier=track['qualification']['reference_tier']
        if tier=='user_reviewed_scoped_click_map':
            policy=read_bound(track['scoring_policy'])
            score=score_scoped(accepted,policy,selected,source)
            oracle=score_scoped(accepted,policy,
                                {'map':reference_raw(accepted,source),'reference_oracle_control':True},source)
        elif 'music_map' in accepted:
            reference=accepted['music_map']
            score=normal_score(reference,selected,accepted['beats_seconds'],False)
            oracle=normal_score(reference,{'map':reference},accepted['beats_seconds'],False)
        else:
            reference=reference_map(track,accepted,source)
            score=normal_score(reference,selected,accepted['beats_seconds'],True)
            oracle=normal_score(reference,{'map':reference},accepted['beats_seconds'],True)
        if not oracle['all_gates_pass']:
            raise ValueError(f'reference self-score fails: {track["id"]}')
        results.append({
            'id':track['id'],'name':track['name'],'reference_tier':tier,
            'source_sha256':source['sha256'],
            'accepted_map_sha256':track['accepted_tempo_map']['sha256'],
            'prediction_sha256':selected_binding['sha256'],
            'selected_branch':record['selected_branch'],
            'score':score,
            'reference_oracle_control_passed':True,
        })
        print(track['id'],'pass' if score['all_gates_pass'] else 'fail',record['selected_branch'],
              'beat',round(score['scores'].get('declared_quarter_grid_f1_70ms',score['scores'].get('quarter_beat_f1_70ms')),3),
              'bar',round(score['scores'].get('bar_boundary_f1_70ms',score['scores'].get('bar_start_f1_70ms')),3),flush=True)
    args.output.mkdir(parents=True)
    (args.output/'per-track.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    summary={
        'schema_version':1,'catalog_sha256':digest(CATALOG),
        'source_only_prediction_manifest_sha256':digest(args.manifest),
        'scorer_sha256':digest(Path(__file__)),
        'scope':'thirteen already reviewed development songs, with separate Walker free-ending gates',
        'source_only_prediction':True,
        'passed_count':sum(row['score']['all_gates_pass'] for row in results),
        'song_count':len(results),
        'rows':[{key:row[key] for key in ('id','selected_branch','reference_tier','prediction_sha256')} |
                {key:row['score'][key] for key in ('scores','gates','all_gates_pass','beat_counts','bar_counts')}
                for row in results],
        'oracle_controls_passed':all(row['reference_oracle_control_passed'] for row in results),
    }
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('passed',summary['passed_count'],'of',summary['song_count'])


if __name__=='__main__':
    main()
