"""Non-destructive audit of rendered MIDI clocks versus musical reference intent.

Agreement of MIDI serialization is not certification that tick zero is a musical
beat or that its quarter duration is the intended performance click. This audit
never shifts labels, drops difficult examples or reads model predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import mido
import numpy as np


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def midi_evidence(path):
    """Retain actual metadata only. No implicit 120 BPM or 4/4 insertion."""
    midi=mido.MidiFile(path)
    tempos=[]; meters=[]; notes=[]; drums=[]
    for track in midi.tracks:
        tick=0
        for event in track:
            tick += event.time
            if event.type=='set_tempo':
                tempos.append({'tick':tick,'microseconds_per_quarter':event.tempo,
                               'bpm_quarter':60e6/event.tempo})
            elif event.type=='time_signature':
                meters.append({'tick':tick,'numerator':event.numerator,'denominator':event.denominator})
            elif event.type=='note_on' and event.velocity:
                notes.append(tick)
                if event.channel==9:
                    drums.append(tick)
    return {'path':str(path),'sha256':sha256(path),'ticks_per_quarter':midi.ticks_per_beat,
            'midi_type':midi.type,'explicit_tempo_events':sorted(tempos,key=lambda e:e['tick']),
            'explicit_meter_events':sorted(meters,key=lambda e:e['tick']),
            'explicit_initial_tempo':any(e['tick']==0 for e in tempos),
            'explicit_initial_meter':any(e['tick']==0 for e in meters),
            'note_grid_diagnostics':note_grid_diagnostics(notes,midi.ticks_per_beat),
            'drum_grid_diagnostics':note_grid_diagnostics(drums,midi.ticks_per_beat)}


def note_grid_diagnostics(ticks, ppq):
    if ppq <= 0:
        raise ValueError('musical PPQ required')
    ticks=np.array(ticks,dtype=float)
    if not len(ticks):
        return {'note_count':0}
    if not np.isfinite(ticks).all() or np.any(ticks < 0):
        raise ValueError('note ticks must be finite and nonnegative')
    subdivision=ppq/4
    phases=ticks%subdivision
    mode=Counter(phases.tolist()).most_common(1)[0][0]
    distance=lambda offset:abs((ticks-offset+subdivision/2)%subdivision-subdivision/2)
    return {'note_count':len(ticks),'first_note_tick':float(min(ticks)),
            'quarter_phase_concentration':float(abs(np.mean(np.exp(2j*np.pi*ticks/ppq)))),
            'sixteenth_phase_concentration':float(abs(np.mean(np.exp(2j*np.pi*ticks/subdivision)))),
            'sixteenth_grid_zero_fraction_within_one_tick':float(np.mean(distance(0)<=1)),
            'sixteenth_grid_mode_offset_ticks':float(mode),
            'sixteenth_grid_mode_fraction_within_one_tick':float(np.mean(distance(mode)<=1)),
            'top_quarter_tick_phases':[{'tick_mod_quarter':float(k),'count':v}
                                       for k,v in Counter((ticks%ppq).tolist()).most_common(8)],
            'interpretation':'Diagnostic note distribution only; no musical phase or beat-unit certification.'}


def qualify(original, rendered, reference):
    flags=['musical_quarter_intent_not_independently_verified',
           'tick_zero_musical_phase_not_independently_verified',
           'synthesized_arrangement_not_recorded_studio_band']
    if not original['explicit_initial_meter']:
        flags.append('original_meter_unspecified')
    if rendered['explicit_initial_meter'] and not original['explicit_initial_meter']:
        flags.append('rendered_meter_must_not_be_attributed_to_original')
    grid=original['note_grid_diagnostics']
    if (grid.get('sixteenth_grid_mode_fraction_within_one_tick',0)
            -grid.get('sixteenth_grid_zero_fraction_within_one_tick',0) > .5):
        flags.append('note_subdivision_phase_offset_requires_review')
    events=original['explicit_tempo_events']
    if (len(events)==1 and events[0]['microseconds_per_quarter']==500000
            and grid.get('sixteenth_phase_concentration',1)<.2):
        flags.append('explicit_120_with_diffuse_note_phase_requires_review')
    return {'reference_tier':'rendered_midi_timebase_control',
            'target_studio_metronome_qualification':'not_applicable_synthetic',
            'musical_beat_unit_status':'unverified','musical_phase_status':'unverified',
            'authored_meter_status':'explicit_original_metadata' if original['explicit_initial_meter'] else 'unknown',
            'existing_downbeat_scoring_status':reference.get('downbeat_label_status'),
            'rendered_clock_alignment_status':'publisher_aligned_serialization_audited',
            'review_flags':flags,'labels_changed':False,'exclude_from_existing_reports':False,
            'prediction_results_used':False,
            'policy':'Keep historical scores unchanged; report this qualification alongside them. '
                     'Diagnostic flags are not findings that a model or label is correct.'}


def audit_catalog(catalog_path):
    catalog_path=Path(catalog_path)
    catalog=json.loads(catalog_path.read_text())
    rows=[]; checked={}
    for track in catalog['tracks']:
        label_path=Path(track['reference']['path'])
        actual=sha256(label_path)
        if actual!=track['reference']['sha256']:
            raise ValueError(f'reference hash mismatch: {track["id"]}')
        reference=json.loads(label_path.read_text())
        original_path=Path(track['input']['path']).parent/'all_src.mid'
        original=midi_evidence(original_path)
        if original['sha256']!=reference['original_midi_sha256']:
            raise ValueError(f'original MIDI hash mismatch: {track["id"]}')
        rendered_path=Path(reference['rendered_midi_sources'][0]['path'])
        rendered=midi_evidence(rendered_path)
        if rendered['sha256']!=reference['rendered_midi_sources'][0]['sha256']:
            raise ValueError(f'rendered MIDI hash mismatch: {track["id"]}')
        checked.update({str(label_path):actual,str(original_path):original['sha256'],str(rendered_path):rendered['sha256']})
        rows.append({'id':track['id'],'group_id':track['group_id'],
                     'original_midi':original,'rendered_midi':rendered,
                     'existing_reference':{'path':str(label_path),'sha256':actual,
                       'kind':reference['kind'],'explicit_initial_meter':reference['explicit_initial_meter'],
                       'meter_events':reference['meter_events'],'source_origin_shift_seconds':reference['source_origin_shift_seconds']},
                     'qualification':qualify(original,rendered,reference)})
    unchanged=all(sha256(path)==digest for path,digest in checked.items())
    if not unchanged:
        raise ValueError('audited input changed during audit')
    return {'schema_version':1,'catalog_path':str(catalog_path),'catalog_sha256':sha256(catalog_path),
            'auditor_sha256':sha256(__file__),'reference_or_prediction_mutation':False,
            'prediction_results_used':False,'verified_unchanged_input_count':len(checked),
            'tracks':rows,'counts':{'tracks':len(rows),
                'original_meter_unspecified':sum(not row['original_midi']['explicit_initial_meter'] for row in rows),
                'note_phase_review':sum('note_subdivision_phase_offset_requires_review' in row['qualification']['review_flags'] for row in rows),
                'diffuse_120_review':sum('explicit_120_with_diffuse_note_phase_requires_review' in row['qualification']['review_flags'] for row in rows)},
            'decision':'No historical labels or scores changed. Musical-grid adjudication remains independent work.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=Path('data/corpus/public/babyslakh-development/catalog-rendered-clock.json'))
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    if args.output_dir.exists():
        parser.error('output directory must be new; preserve earlier audits')
    report=audit_catalog(args.catalog)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'report':str(args.output_dir/'report.json'),**report['counts']}))


if __name__=='__main__':
    main()
