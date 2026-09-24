"""Use observed creator click positions when an accompanying MIDI map drifts.

MIDI supplies quarter identities, not corrected beat times. No model output,
music transient, global offset, or time scaling enters reference qualification.
Exact tempo/meter change scoring is withheld for this reference tier.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from acquire_reference_corpus import click_onsets
from inspect_inputs import sha256


def match_quarters(midi_quarters, click_times, tolerance=.07):
    midi, clicks = np.asarray(midi_quarters, float), np.asarray(click_times, float)
    if (midi.ndim != 1 or clicks.ndim != 1 or len(midi) < 2 or len(clicks) < 2 or
            not np.isfinite(midi).all() or not np.isfinite(clicks).all() or
            np.any(np.diff(midi) <= 0) or np.any(np.diff(clicks) <= 0)):
        raise ValueError('finite increasing event sequences required')
    insertion = np.searchsorted(clicks, midi)
    left, right = np.clip(insertion-1, 0, len(clicks)-1), np.clip(insertion, 0, len(clicks)-1)
    dl, dr = abs(clicks[left]-midi), abs(clicks[right]-midi)
    if np.any((left != right) & (dl <= tolerance) & (dr <= tolerance)):
        raise ValueError('quarter identity is ambiguous between two clicks')
    indices = np.where(dl < dr, left, right)
    differences = clicks[indices]-midi
    if np.any(abs(differences) > tolerance) or np.any(np.diff(indices) <= 0):
        raise ValueError('quarter-to-click mapping is missing or nonunique')
    return indices, differences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('new output required')
    catalog = json.loads(args.catalog.read_text())
    prepared = []
    for record in catalog['tracks']:
        if record['qualification_status'] != 'click_map_consistent_without_offset':
            raise ValueError('first require source geometry and coarse MIDI/click consistency audit')
        if sha256(record['reference']['path']) != record['reference']['sha256']:
            raise ValueError('base reference changed')
        source = json.loads(Path(record['reference']['path']).read_text())
        if (sha256(record['input']['path']) != record['input']['sha256'] or
                sha256(record['reference_click_path']) != source['reference_click_sha256']):
            raise ValueError('paired source assets changed')
        detected = click_onsets(record['reference_click_path'])
        if (detected['source_frames'], detected['sample_rate']) != (record['sample_frames'], record['sample_rate']):
            raise ValueError('paired source geometry differs')
        lo, hi = source['evaluation_support_seconds']
        midi = np.asarray(source['beats_seconds'])
        keep = (midi >= lo) & (midi <= hi)
        indices, differences = match_quarters(midi[keep], detected['times_seconds'])
        observed = np.asarray(detected['times_seconds'])[indices]
        if np.any(observed < lo) or np.any(observed > hi):
            raise ValueError('matched click lies outside declared support')
        reference = {'kind': 'observed_creator_click_quarters', 'beats_seconds': observed.tolist(),
            'quarter_indices': np.asarray(source['quarter_indices'])[keep].tolist(),
            'evaluation_support_seconds': [lo, hi], 'downbeats_seconds': None,
            'tempo_events': None, 'meter_events': None,
            'reference_click_sha256': source['reference_click_sha256'],
            'source_audio_sha256': record['input']['sha256'],
            'quarter_identity_source': deepcopy(record['reference']),
            'quarter_time_source': 'observed supplied click WAV, not extrapolated MIDI tempo events',
            'onset_resolution_seconds': detected['onset_resolution_seconds'],
            'source_origin_shift_seconds': 0, 'alignment_fitted_to_predictions': False,
            'change_scoring_status': 'withheld: supplied MIDI differs from click; exact changes and downbeats not independently qualified',
            'annotation_caveat': 'Creator performance click; original recording-to-click intent not explicitly attested. Click detection resolution is 1ms, not sample-exact certification.'}
        audit = {'id': record['id'], 'quarter_count': len(observed),
            'midi_minus_click_error_ms': {'absolute_p95': float(np.percentile(abs(differences), 95)*1000),
                                        'absolute_max': float(max(abs(differences))*1000)},
            'matched_click_index_steps': sorted(set(np.diff(indices).tolist())),
            'source_midi_map_unchanged': True, 'source_audio_unchanged': True,
            'automatic_predictions_used': False, 'exact_change_scores_withheld': True}
        row = deepcopy(record)
        row.update(dataset='forestry_observed_click_extension', absolute_timing_verified=True,
                   qualification_status='observed_creator_click_quarters_1ms_resolution',
                   evaluation_admission='beat_times_only_no_exact_tempo_meter_change_scores',
                   role='new_song_same_existing_artist_group', downbeat_labels=False)
        row['supplied_midi_tempo_event_count'] = row.pop('tempo_event_count')
        row['supplied_midi_meter_event_count'] = row.pop('meter_event_count')
        prepared.append((row, reference, audit))
    args.output_dir.mkdir(parents=True)
    rows, audits = [], []
    for row, reference, audit in prepared:
        label = args.output_dir/(row['id']+'.json')
        label.write_text(json.dumps(reference, indent=2)+'\n')
        row['reference'] = {'path': str(label), 'sha256': sha256(label)}
        rows.append(row)
        audits.append(audit)
    (args.output_dir/'catalog.json').write_text(json.dumps({'tracks': rows, 'complete': True,
        'base_catalog': {'path': str(args.catalog), 'sha256': sha256(args.catalog)}}, indent=2)+'\n')
    (args.output_dir/'reference-audit.json').write_text(json.dumps({'tracks': audits,
        'qualifier_sha256': sha256(__file__), 'click_extractor_sha256': sha256(Path(__file__).with_name('acquire_reference_corpus.py'))}, indent=2)+'\n')
    print(json.dumps(audits, indent=2))


if __name__ == '__main__':
    main()
