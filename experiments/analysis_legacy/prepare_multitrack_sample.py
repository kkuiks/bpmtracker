"""Prepare reproducible rough mixes from an explicitly reviewed aligned ZIP.

This is not a DAW renderer: mono is copied to L/R, stereo is retained, and all
tracks have unity gain. One common, constant attenuation protects both buses.
No source is shifted, trimmed, stretched, resampled, or timed against labels.
"""
import argparse
from collections import Counter
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

import mido
import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from midi_reference import unique_events


BLOCK = 262144


def read_tempo_map(path):
    """A clock-only MIDI need not contain paired instrument note events."""
    midi = mido.MidiFile(path)
    if midi.type not in (0, 1) or midi.ticks_per_beat <= 0:
        raise ValueError('Synchronous PPQ MIDI required')
    tick = 0
    tempos, meters = [], []
    for event in mido.merge_tracks(midi.tracks):
        tick += event.time
        if event.type == 'set_tempo':
            if event.tempo <= 0:
                raise ValueError('Invalid tempo')
            tempos.append((tick, event.tempo))
        elif event.type == 'time_signature':
            meters.append((tick, (event.numerator, event.denominator)))
    if not any(t == 0 for t, _ in tempos) or not any(t == 0 for t, _ in meters):
        raise ValueError('Explicit initial tempo and meter required')
    raw_counts = {'tempo': len(tempos), 'meter': len(meters)}
    tempos = unique_events(tempos, 500000)
    meters = unique_events(meters, (4, 4))

    def seconds(target):
        elapsed = 0.
        for index, (start, value) in enumerate(tempos):
            stop = min(target, tempos[index + 1][0]) if index + 1 < len(tempos) else target
            if stop > start:
                elapsed += (stop - start) * value / 1e6 / midi.ticks_per_beat
            if stop == target:
                break
        return elapsed

    return {'kind': 'supplied_midi_clock_not_qualified_audio_reference',
            'midi_sha256': sha256(path), 'ticks_per_quarter': midi.ticks_per_beat,
            'raw_event_counts': raw_counts,
            'tempo_events': [{'tick': t, 'time_seconds': seconds(t),
                              'microseconds_per_quarter': v, 'bpm_quarter': 60e6 / v} for t, v in tempos],
            'meter_events': [{'tick': t, 'time_seconds': seconds(t),
                              'numerator': n, 'denominator': d} for t, (n, d) in meters],
            'absolute_timing_verified': False, 'evaluation_support_seconds': None,
            'caveat': 'Initial short bars may be pickups; original recording click and source-zero quarter phase remain unverified.'}


def validate_plan(plan):
    if plan.get('layout_reviewed') is not True:
        raise ValueError('An explicitly reviewed source layout is required')
    tracks = plan['tracks']
    if not tracks or len({t['member'] for t in tracks}) != len(tracks):
        raise ValueError('Unique nonempty music track selection required')
    if not any(t['role'] == 'drums' for t in tracks):
        raise ValueError('An explicit drum selection is required')
    for track in tracks:
        member = PurePosixPath(track['member'].replace('\\', '/'))
        if member.is_absolute() or '..' in member.parts or member.suffix.lower() != '.wav':
            raise ValueError('Unsafe or unsupported archive member')
        if track['role'] not in ('drums', 'music') or re.search(r'\b(click|metronome|guide)\b', member.stem, re.I):
            raise ValueError('Reference/guide inputs must not enter music buses')
        if any(track.get(k) != v for k, v in [('position_frames', 0), ('source_offset_frames', 0), ('playback_rate', 1), ('gain', 1), ('pan', 0)]):
            raise ValueError('Only aligned, unity-gain, centered, unstretched sources are supported')
    if plan['sample_rate'] <= 0 or plan['sample_frames'] <= 0:
        raise ValueError('Invalid source geometry')


def signal_stats(audio):
    return {'sample_peak': float(np.max(np.abs(audio))),
            'rms_per_channel': np.sqrt(np.mean(np.square(audio), axis=0)).tolist(),
            'nonfinite_samples': int(np.count_nonzero(~np.isfinite(audio)))}


def prepare(plan_path, output_dir, reserve_bytes=10_000_000_000):
    plan_path, output_dir = Path(plan_path), Path(output_dir)
    if output_dir.exists():
        raise ValueError('Output must be a new directory')
    plan = json.loads(plan_path.read_text())
    validate_plan(plan)
    archive = Path(plan['archive']['path'])
    if sha256(archive) != plan['archive']['sha256']:
        raise ValueError('Source archive hash mismatch')
    for ref in (plan['tempo_midi'], plan['source_project']):
        if sha256(ref['path']) != ref['sha256']:
            raise ValueError('Reference asset hash mismatch')
    frames, rate = plan['sample_frames'], plan['sample_rate']
    required = frames * 2 * 4 * 2 + 8_000_000
    if shutil.disk_usage(output_dir.parent).free < reserve_bytes + required:
        raise ValueError('Insufficient space above free-space reserve')
    output_dir.mkdir()
    progress = output_dir / 'preparation.json'
    status = {'complete': False, 'plan_sha256': sha256(plan_path), 'source_archive': plan['archive'],
              'source_layout_evidence': plan['source_project'], 'absolute_timing_verified': False,
              'default_promoted': False, 'scoring_performed': False}
    progress.write_text(json.dumps(status, indent=2) + '\n')
    full = np.zeros((frames, 2), dtype=np.float64)
    drums = np.zeros_like(full)
    inputs = []
    with zipfile.ZipFile(archive) as z:
        counts = Counter(z.namelist())
        for index, track in enumerate(plan['tracks']):
            name = track['member']
            if counts[name] != 1:
                raise ValueError('Missing or duplicate archive member')
            info = z.getinfo(name)
            if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError('Archive links/encrypted members are unsupported')
            # Only one uncompressed member is held, never the complete package.
            if info.file_size > max(frames * 2 * 8 + 16_000_000, 32_000_000):
                raise ValueError('Member exceeds declared geometry budget')
            raw = z.read(info)  # Also checks the member CRC.
            with sf.SoundFile(io.BytesIO(raw)) as source:
                if (source.samplerate, len(source)) != (rate, frames) or source.channels not in (1, 2):
                    raise ValueError('Unequal geometry or unsupported channel layout')
                if source.subtype not in ('PCM_16', 'PCM_24', 'PCM_32', 'FLOAT', 'DOUBLE'):
                    raise ValueError('Unsupported source encoding')
                source_info = {'member': name, 'crc32': f'{info.CRC:08x}', 'role': track['role'],
                               'bytes': info.file_size, 'channels': source.channels, 'subtype': source.subtype}
                offset = 0
                for block in source.blocks(blocksize=BLOCK, dtype='float64', always_2d=True):
                    if not np.isfinite(block).all():
                        raise ValueError('Non-finite source samples')
                    stop = offset + len(block)
                    full[offset:stop] += block  # Mono intentionally broadcasts to both channels.
                    if track['role'] == 'drums':
                        drums[offset:stop] += block
                    offset = stop
                if offset != frames:
                    raise ValueError('Incomplete source decode')
                inputs.append(source_info)
            del raw
            if (index + 1) % 10 == 0 or index + 1 == len(plan['tracks']):
                print(json.dumps({'decoded_tracks': index + 1, 'total_tracks': len(plan['tracks'])}), flush=True)
    before = {'full_mix': signal_stats(full), 'drums': signal_stats(drums)}
    if any(s['nonfinite_samples'] for s in before.values()):
        raise ValueError('Non-finite accumulated audio')
    peak = max(s['sample_peak'] for s in before.values())
    if peak == 0:
        raise ValueError('All-silent selection')
    gain = min(1., 10 ** (-1 / 20) / peak)
    outputs = {}
    for name, audio in [('full_mix', full), ('drums', drums)]:
        path = output_dir / (name + '.wav')
        with sf.SoundFile(path, mode='w', samplerate=rate, channels=2, subtype='FLOAT') as out:
            for start in range(0, frames, BLOCK):
                out.write(audio[start:start + BLOCK] * gain)
        # Independently reopen and compare every output sample to the intended sum.
        maximum_error, sample_peak, clipped, offset = 0., 0., 0, 0
        with sf.SoundFile(path) as check:
            if (check.samplerate, len(check), check.channels, check.subtype) != (rate, frames, 2, 'FLOAT'):
                raise ValueError('Output geometry mismatch')
            for block in check.blocks(blocksize=BLOCK, dtype='float64', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError('Non-finite output samples')
                expected = (audio[offset:offset + len(block)] * gain).astype('float32').astype('float64')
                maximum_error = max(maximum_error, float(np.max(np.abs(block - expected))))
                sample_peak = max(sample_peak, float(np.max(np.abs(block))))
                clipped += int(np.count_nonzero(np.abs(block) >= 1.))
                offset += len(block)
        if maximum_error != 0 or clipped or offset != frames:
            raise ValueError('Output verification failed')
        outputs[name] = {'kind': 'audio', 'path': str(path.resolve()), 'sha256': sha256(path),
                         'bytes': path.stat().st_size, 'sample_peak': sample_peak,
                         'samples_at_or_above_full_scale': clipped, 'decode_comparison_max_error': maximum_error}
    references = output_dir / 'reference-assets'
    references.mkdir()
    for ref in (plan['tempo_midi'], plan['source_project']):
        shutil.copyfile(ref['path'], references / Path(ref['path']).name)
    clock = read_tempo_map(plan['tempo_midi']['path'])
    (output_dir / 'tempo-map.json').write_text(json.dumps(clock, indent=2) + '\n')
    shutil.copyfile(plan_path, output_dir / 'source-plan.json')
    record = {'id': plan['id'], 'dataset': 'ntm_rough_mix_diagnostics', 'group_id': plan['group_id'],
              'genre': plan['genre'], 'input': outputs['full_mix'],
              'diagnostic_inputs': {'drums': {**outputs['drums'], 'same_recording_not_independent_sample': True}},
              'sample_rate': rate, 'sample_frames': frames, 'duration_seconds': frames / rate,
              'source_page': plan['source_page'], 'absolute_timing_verified': False,
              'benchmark_role': 'diagnostic_only', 'target_evaluation_eligible': False,
              'evaluation_admission': 'diagnostic_prediction_only_not_target_benchmark',
              'supplied_tempo_map': {'path': str((output_dir / 'tempo-map.json').resolve()),
                                     'sha256': sha256(output_dir / 'tempo-map.json')},
              'audio_role': 'reproducible_unity_sum_rough_mix_not_released_master',
              'reference_used_for_render_timing': False}
    (output_dir / 'catalog.json').write_text(json.dumps({'tracks': [record], 'complete': True}, indent=2) + '\n')
    status.update(complete=True, outputs=outputs, input_tracks=inputs, sample_rate=rate, sample_frames=frames,
                  benchmark_role='diagnostic_only', target_evaluation_eligible=False,
                  duration_seconds=frames / rate, sample_subtype='FLOAT', common_gain=gain,
                  gain_policy='attenuation_only; common gain makes max sample peak across both buses <= -1dBFS',
                  pre_gain_stats=before, source_origin_shift_frames=0, resampling=False, time_stretching=False,
                  mono_policy='duplicate to L/R', stereo_policy='retain supplied L/R',
                  effects='none', per_track_gain='unity', renderer_role='rough sum, not an exact DAW render',
                  script_sha256=sha256(__file__), numpy_version=np.__version__, soundfile_version=sf.__version__)
    progress.write_text(json.dumps(status, indent=2) + '\n')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.plan, args.output_dir)
    print(json.dumps({'complete': result['complete'], 'outputs': result['outputs'],
                      'common_gain': result['common_gain']}), flush=True)


if __name__ == '__main__':
    main()
