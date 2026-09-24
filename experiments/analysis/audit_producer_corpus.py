"""Audit production MIDI metadata without inventing an audio time origin.

The resulting catalog is explicitly prediction-only. Agreement among MIDI files
certifies their shared authored map, not alignment of a mastered mix to that map.
"""
import argparse
import json
from pathlib import Path
import struct

import mido
import soundfile as sf

from acquire_reference_corpus import creator_midi_clock, validate_riff_size
from inspect_inputs import sha256


def wav_metadata(path):
    validate_riff_size(path)
    info = sf.info(path)
    result = {'path': str(path), 'sha256': sha256(path), 'sample_rate': info.samplerate,
              'sample_frames': info.frames, 'channels': info.channels, 'duration_seconds': info.duration,
              'bwf_time_reference_frames': None}
    with Path(path).open('rb') as handle:
        handle.read(12)
        while header := handle.read(8):
            if len(header) != 8:
                raise ValueError('truncated RIFF chunk header')
            name, count = struct.unpack('<4sI', header)
            if name == b'bext':
                prefix = handle.read(min(count, 346))
                if len(prefix) >= 346:
                    result['bwf_time_reference_frames'] = struct.unpack_from('<Q', prefix, 338)[0]
                handle.seek(count-len(prefix), 1)
            else:
                handle.seek(count, 1)
            if count % 2:
                handle.seek(1, 1)
    return result


def midi_metadata(path, audio_duration):
    midi = mido.MidiFile(path)
    clock = creator_midi_clock(path, audio_duration)
    seconds = 0.
    onsets = []
    for message in midi:
        seconds += message.time
        if message.type == 'note_on' and message.velocity > 0:
            onsets.append(seconds)
    signature = {
        'tempo': [(e['tick']/midi.ticks_per_beat, e['microseconds_per_quarter']) for e in clock['tempo_events']],
        'meter': [(e['tick']/midi.ticks_per_beat, e['numerator'], e['denominator']) for e in clock['meter_events']]}
    return {'path': str(path), 'sha256': sha256(path), 'ticks_per_quarter': midi.ticks_per_beat,
            'clock_signature': signature, 'tempo_events_relative_to_midi_zero': clock['tempo_events'],
            'meter_events_relative_to_midi_zero': clock['meter_events'],
            'bar_reset_candidates': clock['bar_reset_candidates'], 'midi_duration_seconds': midi.length,
            'note_on_count': len(onsets), 'first_note_on_seconds': min(onsets) if onsets else None,
            'last_note_on_seconds': max(onsets) if onsets else None,
            'notes_after_mix_duration_under_zero_origin_hypothesis': sum(t > audio_duration for t in onsets),
            'audio_origin_established': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--alignment-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('new output required')
    selection = json.loads((args.source_dir/'selection.json').read_text())
    rows, audits = [], []
    for item in selection['selected']:
        slug = Path(item['archive']).stem
        folder = args.source_dir/(slug+'-assets')
        manifest = folder/'manifest.json'
        acquisition = json.loads(manifest.read_text())
        if not acquisition['complete']:
            raise ValueError('incomplete asset extraction')
        for asset in acquisition['extraction']:
            if sha256(asset['path']) != asset['sha256']:
                raise ValueError('extracted asset changed')
        mix = wav_metadata(folder/'Reference Mix.wav')
        midis = [midi_metadata(p, mix['duration_seconds']) for p in sorted(folder.glob('*.mid'))]
        if len(midis) < 2:
            raise ValueError('at least two production MIDI parts required in this audit')
        agree = all(m['clock_signature'] == midis[0]['clock_signature'] for m in midis[1:])
        clock = midis[0]['clock_signature']
        meter_changes = sum(a[1:] != b[1:] for a, b in zip(clock['meter'], clock['meter'][1:]))
        alignment = [{'path': str(p), 'sha256': sha256(p),
                      'qualified_constant_offset': json.loads(p.read_text())['qualified_constant_offset']}
                     for p in sorted(args.alignment_dir.glob(slug+'-*.json'))]
        row = {'id': item['id'], 'dataset': 'daybreak_production_midi_pending_origin',
               'genre': 'metal_producer_instrumental', 'group_id': item['producer_group'],
               'input': {'kind': 'audio', 'path': mix['path'], 'sha256': mix['sha256']},
               'duration_seconds': mix['duration_seconds'], 'sample_rate': mix['sample_rate'],
               'sample_frames': mix['sample_frames'], 'absolute_timing_verified': False,
               'evaluation_admission': 'prediction_only_pending_independent_audio_midi_origin',
               'recording_role': item['role'], 'model_overlap': 'unaudited',
               'reference_assets_used_as_model_input': False}
        rows.append(row)
        audits.append({'id': row['id'], 'acquisition_manifest': {'path': str(manifest), 'sha256': sha256(manifest)},
            'midis_agree_on_tempo_and_meter': agree, 'midi_parts': midis,
            'declared_quarter_rates_bpm': [60e6/m for _, m in clock['tempo']],
            'declared_tempo_changes': len(clock['tempo'])-1, 'declared_meter_changes': meter_changes,
            'source_wav_metadata': [wav_metadata(p) for p in sorted(folder.glob('*.wav'))],
            'waveform_audits': alignment, 'absolute_timing_verified': False,
            'reason': 'MIDI map agreement and BWF fields do not independently certify the final mix origin. Distorted/processed stems did not pass the tested waveform correspondence gate. No offset is estimated from model predictions.'})
        print(row['id'], 'MIDI agree', agree, 'BPM', audits[-1]['declared_quarter_rates_bpm'],
              'meter changes', meter_changes, 'TIMING NOT ADMITTED', flush=True)
    args.output_dir.mkdir(parents=True)
    for name, value in [('catalog.json', {'tracks': rows, 'complete': True, 'role': 'source_only_inference_catalog'}),
                        ('reference-audit.json', {'tracks': audits, 'source_hash': sha256(__file__),
                          'selection_sha256': sha256(args.source_dir/'selection.json'), 'strict_timing_scores_permitted': False})]:
        (args.output_dir/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
