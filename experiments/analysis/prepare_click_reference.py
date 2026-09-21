"""Qualify a constant-tempo creator click with a separately audited mix origin.

This importer never aligns a reference to model output or musical transients.
It requires a source-to-source waveform audit and the paired stem geometry.
Meter/downbeat semantics and original recording-to-click intent remain unknown.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from acquire_reference_corpus import click_onsets, validate_riff_size
from inspect_inputs import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--alignment', type=Path, required=True)
    parser.add_argument('--click', type=Path, required=True)
    parser.add_argument('--declared-bpm', type=float, required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--group', required=True)
    parser.add_argument('--source-page', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or not np.isfinite(args.declared_bpm) or args.declared_bpm <= 0:
        parser.error('new output and positive declared pulse rate required')
    audit = json.loads(args.alignment.read_text())
    if not audit['qualified_constant_offset'] or audit['reference_click_or_model_used']:
        parser.error('qualified source-only offset audit required')
    if audit['configuration']['maximum_frame_spread']/audit['sample_rate'] > .001:
        parser.error('this reference importer requires at most 1ms source-alignment spread')
    mix, stem = audit['mix'], audit['stem']
    if sha256(mix['path']) != mix['sha256'] or sha256(stem['path']) != stem['sha256']:
        parser.error('audited source changed')
    for p in (mix['path'], stem['path'], args.click):
        validate_riff_size(p)
    music_info, stem_info, click_info = sf.info(mix['path']), sf.info(stem['path']), sf.info(args.click)
    if ((stem_info.frames, stem_info.samplerate) != (click_info.frames, click_info.samplerate) or
            music_info.samplerate != audit['sample_rate']):
        parser.error('paired click/stem geometry does not match source audit')
    detected = click_onsets(args.click)
    click = np.asarray(detected['times_seconds'])
    period = 60/args.declared_bpm
    if len(click) < 16 or abs(click[0]) > .002 or np.max(abs(np.diff(click)-period)) > .002:
        parser.error('click is not the declared constant cadence at source zero')
    residual = click-np.arange(len(click))*period
    if np.max(abs(residual)) > .002:
        parser.error('declared cadence drifts from the source click')
    shift = audit['stem_minus_mix_frames']/audit['sample_rate']
    mapped = click-shift
    eligible = (mapped >= 0) & (mapped < music_info.duration)
    reference = {'kind': 'creator_click_wav_with_audited_source_mapping',
        'beats_seconds': mapped[eligible].tolist(), 'quarter_indices': np.flatnonzero(eligible).tolist(),
        'downbeats_seconds': None, 'meter_events': [],
        'tempo_events': [{'time_seconds': -shift, 'bpm_quarter': args.declared_bpm}],
        'evaluation_support_seconds': [float(mapped[eligible][0]), float(mapped[eligible][-1])],
        'unit': 'creator click cadence and filename BPM; quarter interpretation provisional without MIDI/meter metadata',
        'source_mapping': {'stem_seconds': 'mix_seconds + offset_seconds', 'offset_seconds': shift,
                           'alignment_path': str(args.alignment), 'alignment_sha256': sha256(args.alignment)},
        'source_audio_sha256': mix['sha256'], 'click_sha256': sha256(args.click),
        'click_onset_resolution_seconds': detected['onset_resolution_seconds'],
        'source_alignment_gate_seconds': audit['configuration']['maximum_frame_spread']/audit['sample_rate'],
        'annotation_caveat': 'Creator performance assets; original recording-to-click intent not explicitly attested. Reference mapping is source-waveform-derived, not sample-exact original DAW metadata.',
        'outside_click_span_status': 'unverified tail is excluded; no invented continuation',
        'alignment_fitted_to_predictions': False, 'source_audio_modified': False}
    args.output_dir.mkdir(parents=True)
    label = args.output_dir/'reference.json'
    label.write_text(json.dumps(reference, indent=2)+'\n')
    record = {'id': args.id, 'dataset': 'walker_creator_click_pilot', 'group_id': args.group,
        'genre': 'creator_studio_instrumental',
        'input': {'kind': 'audio', 'path': mix['path'], 'sha256': mix['sha256']},
        'reference': {'path': str(label), 'sha256': sha256(label)},
        'duration_seconds': music_info.duration, 'sample_rate': music_info.samplerate, 'sample_frames': music_info.frames,
        'source_page': args.source_page, 'reference_click_path': str(args.click), 'source_stem_path': stem['path'],
        'qualification_status': 'creator_click_with_waveform_verified_origin_at_declared_1ms_scale',
        'model_overlap': 'not audited', 'role': 'new creator recording; no meter/change accuracy claim',
        'redistribution': 'local analysis only; creator free download is not permission to redistribute'}
    (args.output_dir/'catalog.json').write_text(json.dumps({'tracks': [record], 'complete': True,
        'importer_sha256': sha256(__file__)}, indent=2)+'\n')
    (args.output_dir/'reference-audit.json').write_text(json.dumps({'click': detected,
        'maximum_click_grid_residual_seconds': float(np.max(abs(residual))),
        'source_mapping_offset_seconds': shift, 'eligible_clicks': int(eligible.sum()),
        'first_reference_second': float(mapped[eligible][0]), 'last_reference_second': float(mapped[eligible][-1]),
        'source_audio_modified': False, 'model_used': False}, indent=2)+'\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
