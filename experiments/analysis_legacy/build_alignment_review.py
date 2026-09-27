"""Build a reversible listening review for a supplied map and finished mix.

This does not certify recording-click origin or change an evaluation catalog.
A frozen waveform lag is a candidate, never an automatic musical reference.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf
import soxr

from audit_source_alignment import correlations
from inspect_inputs import sha256
from prepare_multitrack_sample import read_tempo_map


MASTER_GAIN = .4
CLICK_GAIN = .8
PULSE_SECONDS = .025


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def quarter_events(clock, source_duration):
    """Explicitly bounded quarter-click renderer; only quarter-based meters here."""
    tpq = clock['ticks_per_quarter']
    tempos, meters = clock['tempo_events'], clock['meter_events']
    if (not np.isfinite(source_duration) or source_duration <= 0 or tpq <= 0
            or not tempos or not meters or tempos[0]['tick'] or meters[0]['tick']):
        raise ValueError('Explicit initial clock and finite source duration required')
    if any(m['denominator'] != 4 or m['numerator'] <= 0 or m['tick'] % tpq for m in meters):
        raise ValueError('Review renderer supports only quarter-aligned /4 meter events')
    events, ti, mi, q = [], 0, 0, 0
    while True:
        tick = q * tpq
        while ti + 1 < len(tempos) and tempos[ti + 1]['tick'] <= tick:
            ti += 1
        tempo = tempos[ti]
        if tempo['microseconds_per_quarter'] <= 0:
            raise ValueError('Positive tempo required')
        time = tempo['time_seconds'] + (tick-tempo['tick']) / tpq * tempo['microseconds_per_quarter'] / 1e6
        if time >= source_duration:
            break
        while mi + 1 < len(meters) and meters[mi + 1]['tick'] <= tick:
            mi += 1
        meter = meters[mi]
        beat = (tick-meter['tick']) // tpq % meter['numerator'] + 1
        events.append({'source_seconds': time, 'quarter_index': q, 'beat_in_bar': int(beat),
                       'numerator': meter['numerator'], 'accent': beat == 1})
        q += 1
    return events


def event_frame(time, offset, rate):
    # Same half-up rule as the browser, including negative starts.
    return int(np.floor((time + offset) * rate + .5))


def render_clicks(events, offset, rate, frames):
    if not np.isfinite(offset) or rate <= 0 or frames <= 0:
        raise ValueError('Finite offset and valid native geometry required')
    output = np.zeros(frames, dtype=np.float32)
    t = np.arange(int(np.floor(rate * PULSE_SECONDS + .5))) / rate
    regular = (.18*np.exp(-220*t)*np.cos(2*np.pi*1500*t)).astype('float32')
    accent = (.30*np.exp(-220*t)*np.cos(2*np.pi*2200*t)).astype('float32')
    placements = []
    for event in events:
        start = event_frame(event['source_seconds'], offset, rate)
        pulse = accent if event['accent'] else regular
        lo, hi = max(0, start), min(frames, start+len(pulse))
        status = 'omitted' if hi <= lo else ('clipped' if lo != start or hi != start+len(pulse) else 'complete')
        if hi > lo:
            output[lo:hi] += pulse[lo-start:hi-start]
        placements.append({'quarter_index': event['quarter_index'], 'accent': event['accent'],
                           'source_seconds': event['source_seconds'], 'master_seconds': event['source_seconds']+offset,
                           'master_start_frame': start, 'render_status': status})
    return output, placements


def peak_envelope(audio, rate):
    hop = max(1, round(rate*.005))
    values = np.max(np.abs(audio), axis=1) if audio.ndim == 2 else np.abs(audio)
    padded = np.pad(values, (0, (-len(values)) % hop))
    peaks = padded.reshape(-1, hop).max(axis=1)
    scale = max(float(peaks.max()), 1e-12)
    return {'seconds_per_bin': hop/rate, 'normalization_peak': scale,
            'peaks': np.round(peaks/scale, 4).tolist()}


def waveform_checks(master, master_rate, kick, kick_rate, frozen_offset):
    """Inspect fixed offsets and nearby waveform matches without consulting MIDI."""
    mix = soxr.resample(master.mean(axis=1), master_rate, kick_rate, quality='VHQ')
    source = kick.mean(axis=1)
    window = round(5*kick_rate)
    starts = np.linspace(2, min(len(mix), len(source))/kick_rate-8, 9)
    if starts[-1] <= starts[0]:
        raise ValueError('Sources too short for distributed waveform checks')
    rows = []
    margin = round(.015*kick_rate)
    for seconds in starts:
        start = round(seconds*kick_rate)
        target = source[start:start+window].astype('float64')
        target -= target.mean()
        if np.max(np.abs(target)) < 1e-8:
            rows.append({'source_start_seconds': start/kick_rate, 'window_seconds': window/kick_rate,
                         'status': 'no_source_signal', 'fixed_offset_correlations': None,
                         'local_master_minus_source_seconds': None, 'local_peak_correlation': None})
            continue
        fixed = {}
        for label, offset in [('zero', 0), ('waveform_candidate', frozen_offset), ('opposite_direction', -frozen_offset)]:
            pos = start + round(offset*kick_rate)
            chunk = mix[pos:pos+window].astype('float64')
            chunk -= chunk.mean()
            fixed[label] = float(np.dot(chunk, target) / max(1e-20, np.linalg.norm(chunk)*np.linalg.norm(target)))
        center = start + round(frozen_offset*kick_rate)
        lo = center-margin
        scores = correlations(mix[lo:center+window+margin], target)
        best = int(np.argmax(scores))
        rows.append({'source_start_seconds': start/kick_rate, 'window_seconds': window/kick_rate,
                     'status': 'waveform_diagnostic', 'fixed_offset_correlations': fixed,
                     'local_master_minus_source_seconds': (lo+best-start)/kick_rate,
                     'local_peak_correlation': float(scores[best])})
    offsets = [r['local_master_minus_source_seconds'] for r in rows if r['local_master_minus_source_seconds'] is not None]
    return {'role': 'same-song diagnostic, not new independent validation or admission gate',
            'sign': 't_master = t_source + offset_seconds', 'frozen_candidate_seconds': frozen_offset,
            'waveform_only': True, 'reference_or_model_used': False,
            'analysis_rate': kick_rate, 'master_resampler': 'soxr VHQ; in-memory diagnostic only',
            'search_radius_seconds': .015, 'window_selection': '9 evenly spaced source windows; may overlap prior checks',
            'windows': rows, 'usable_windows': len(offsets),
            'local_offset_range_seconds': [min(offsets), max(offsets)] if offsets else None,
            'local_offset_spread_ms': (max(offsets)-min(offsets))*1000 if offsets else None,
            'absolute_timing_verified': False, 'target_evaluation_eligible': False}


def build(master_path, midi_path, kick_path, prior_path, output, title, port=8937, reserve_bytes=10_000_000_000):
    paths = [Path(p) for p in (master_path, midi_path, kick_path, prior_path)]
    master_path, midi_path, kick_path, prior_path = paths
    output = Path(output)
    if output.exists():
        raise ValueError('Output must be a new directory')
    if not output.parent.is_dir() or not 1024 <= port <= 65535:
        raise ValueError('Existing parent directory and valid local server port required')
    hashes = {str(p.resolve()): sha256(p) for p in paths}
    prior = json.loads(prior_path.read_text())
    offset = float(prior['kick_correspondence']['master_minus_source_seconds_median'])
    if not np.isfinite(offset) or not 0 < abs(offset) <= .5:
        raise ValueError('Pilot requires a nonzero frozen waveform candidate within 500ms')
    info = sf.info(master_path)
    expected_bytes = info.frames * (info.channels*4 + 3*(1+info.channels)*3) + 8_000_000
    if shutil.disk_usage(output.parent).free < reserve_bytes + expected_bytes:
        raise ValueError('Insufficient space above free-space reserve')
    master, rate = sf.read(master_path, dtype='float32', always_2d=True)
    kick, kr = sf.read(kick_path, dtype='float32', always_2d=True)
    if master.shape[1] != 2 or not np.isfinite(master).all() or not np.isfinite(kick).all():
        raise ValueError('Finite stereo master and finite source kick required')
    if np.max(np.abs(master))*MASTER_GAIN + .3*CLICK_GAIN >= 1:
        raise ValueError('Chosen common audition gain cannot guarantee headroom')
    clock = read_tempo_map(midi_path)
    events = quarter_events(clock, len(kick)/kr)
    checks = waveform_checks(master, rate, kick, kr, offset)
    output.mkdir()
    write_json(output/'verification.json', {'complete': False})
    shutil.copyfile(master_path, output/'master.wav')
    shutil.copyfile(midi_path, output/'supplied-tempo-map.mid')
    if sha256(output/'master.wav') != hashes[str(master_path.resolve())]:
        raise ValueError('Master copy mismatch')
    write_json(output/'supplied-tempo-map.json', clock)
    write_json(output/'waveform-checks.json', checks)
    variants = []
    all_placements = []
    names = [('original', '원본 위치 · 0 ms', 0.),
             ('candidate', '파형 보정 후보 · 앞당김', offset),
             ('opposite', '반대 방향 비교 · 늦춤', -offset)]
    for name, label, delta in names:
        clicks, placements = render_clicks(events, delta, rate, len(master))
        click_name, listen_name = f'click-{name}.wav', f'listen-{name}.wav'
        sf.write(output/click_name, clicks, rate, subtype='PCM_24')
        audition = master*MASTER_GAIN + clicks[:, None]*CLICK_GAIN
        sf.write(output/listen_name, audition, rate, subtype='PCM_24')
        checksums = {}
        for filename, expected in [(click_name, clicks[:, None]), (listen_name, audition)]:
            actual, actual_rate = sf.read(output/filename, dtype='float32', always_2d=True)
            error = float(np.max(np.abs(actual-expected)))
            if actual_rate != rate or actual.shape != expected.shape or error > 2**-23 or np.max(np.abs(actual)) >= 1:
                raise ValueError(f'Failed audio verification: {filename}')
            checksums[filename] = {'sha256': sha256(output/filename), 'peak': float(np.max(np.abs(actual))),
                                   'max_quantization_error': error, 'sample_frames': len(actual), 'sample_rate': rate}
        variants.append({'id': name, 'label': label, 'offset_seconds': delta,
                         'click_file': click_name, 'listen_file': listen_name,
                         'omitted_pulses': sum(p['render_status'] == 'omitted' for p in placements),
                         'partial_pulses': sum(p['render_status'] == 'clipped' for p in placements), 'files': checksums})
        all_placements.extend({'variant': name, **p} for p in placements)
    with (output/'click-placements.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_placements[0]))
        writer.writeheader(); writer.writerows(all_placements)
    payload = {'schema_version': 1, 'title': title, 'master_file': 'master.wav', 'sample_rate': rate,
               'sample_frames': len(master), 'duration_seconds': len(master)/rate,
               'source_duration_seconds': len(kick)/kr, 'source_hashes': hashes,
               'master_sha256': hashes[str(master_path.resolve())], 'midi_sha256': clock['midi_sha256'],
               'transform': 't_master = t_project + offset_seconds', 'events': events, 'variants': variants,
               'master_gain': MASTER_GAIN, 'click_gain': CLICK_GAIN, 'pulse_seconds': PULSE_SECONDS,
               'absolute_timing_verified': False, 'target_evaluation_eligible': False,
               'waveforms': {'master': peak_envelope(master, rate), 'kick': peak_envelope(kick, kr)}}
    write_json(output/'review.json', payload)
    shutil.copyfile(Path(__file__).with_name('alignment_review_page.html'), output/'index.html')
    instructions = f'''정렬 비교 — {title}

가장 간단한 확인: listen-original.wav / listen-candidate.wav / listen-opposite.wav를 같은 구간에서 비교하세요.
Master에 동일한 음량의 클릭을 합친 청취용 파일입니다. 분석 입력이 아닙니다.
원본=0ms / 파형 후보={offset*1000:+.6f}ms / 반대 방향={-offset*1000:+.6f}ms.
후보는 확정 정답이 아닙니다. 특히 Cubase에서 관찰한 방향과 파형 후보의 방향이 달라 양쪽을 제공합니다.

브라우저: start-review.cmd 실행 후 http://localhost:{port}/ 에 접속.
현재 실험용 WSL/Python이 필요합니다. 최종 Windows 제품 요구사항이 아닙니다.
초기/중간/후반 바로가기와 오프셋 미세 조정을 사용하세요. +는 클릭을 늦추고 -는 앞당깁니다.
선택한 오프셋의 JSON과 클릭 WAV를 각각 저장할 수 있습니다. 원본/정답 카탈로그는 바뀌지 않습니다.

Cubase 비교:
1. master.wav와 click-original.wav, click-candidate.wav, click-opposite.wav를 별도 오디오 트랙에 가져옵니다.
2. 모두 타임라인의 같은 절대 0초에 배치합니다. 파일을 첫 소리 위치에 맞춰 따로 움직이지 마세요.
3. Musical Mode/자동 템포 맞춤을 끄고, Cubase 자체 메트로놈도 끕니다.
4. Master 한 개와 클릭 한 개만 켜서 비교합니다. Master 볼륨을 낮춰 디코딩 peak로 인한 출력 클리핑을 피하세요.
5. 인트로, 약 12초, 60초, 120초, 190초에서 같은 후보가 계속 맞는지 확인합니다.
   음악 연주 자체의 앞뒤 타이밍과 단순 파일 원점 차이를 구별하세요.
6. supplied-tempo-map.mid는 변경하지 않은 원본 지도입니다. 오프셋은 클릭 WAV에 반영되어 있습니다.
   이 MIDI를 가져왔다고 이동된 클릭이 Cubase 그리드에 자동 반영되는 것은 아닙니다.
   원본은 약 175 BPM, 첫 2/4 이후 4/4이며 실제 BPM 변화는 없습니다.

원본 Master MP3/디코딩 WAV/CPR/MIDI는 수정하지 않았습니다. master.wav는 canonical 디코딩 WAV와 바이트가 같습니다.
클릭 파일은 모두 {rate}Hz, {len(master)}프레임이며 모든 출력 시작점은 Master의 0초입니다.
클릭은 제공 소스의 {len(kick)/kr:g}초 범위까지만 생성했으며, 이후 Master 꼬리 구간은 정답 범위로 인증하지 않습니다.
음원은 이동/늘임하지 않았고, 마디·템포 사건의 상대 간격도 바꾸지 않았습니다.
이 패키지는 한 곡의 사람 검토용 후보이며 자동 분석 성능/정밀 정답 인증 결과가 아닙니다.

Cubase 공식 Musical Mode 설명:
https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/sample_editor_tempo_matching_audio/sample_editor_tempo_matching_audio_musical_mode_c.html
'''
    (output/'읽어주세요.txt').write_text(instructions, encoding='utf-8-sig')
    # No dependency on a transient process for replay; uses this WSL distro's system Python.
    distro = os.environ.get('WSL_DISTRO_NAME')
    distro_option = f' -d "{distro}"' if distro else ''
    command = f'wsl.exe{distro_option} python3 -m http.server {port} --bind 127.0.0.1 --directory "{output.resolve()}"'
    (output/'start-review.cmd').write_bytes(('@echo off\r\n' +
        f'echo Open http://localhost:{port}/ in your browser. Close this window to stop.\r\n' + command + '\r\npause\r\n').encode('utf-8'))
    snapshot = output/'source-snapshot'; snapshot.mkdir()
    for file in ['build_alignment_review.py', 'alignment_review_page.html', 'prepare_multitrack_sample.py',
                 'audit_source_alignment.py', 'inspect_inputs.py', 'midi_reference.py', 'test_alignment_review.py']:
        shutil.copyfile(Path(__file__).with_name(file), snapshot/file)
    unchanged = all(sha256(p) == hashes[str(p.resolve())] for p in paths)
    if not unchanged:
        raise ValueError('Source hashes changed during review generation')
    report = {'complete': True, 'input_hashes_unchanged': unchanged, 'master_copy_byte_identical': True,
              'absolute_timing_verified': False, 'target_evaluation_eligible': False, 'catalog_changed': False,
              'source_audio_shifted_or_stretched': False, 'bpm_or_meter_modified': False,
              'master_gain_in_auditions_only': MASTER_GAIN, 'click_gain_in_auditions': CLICK_GAIN,
              'source_hashes': hashes, 'variants': variants, 'waveform_diagnostic': checks,
              'quarter_count': len(events), 'midi_tempo_events': len(clock['tempo_events']),
              'midi_meter_events': len(clock['meter_events']), 'local_server_port': port,
              'numpy_version': np.__version__, 'soundfile_version': sf.__version__, 'soxr_version': soxr.__version__,
              'bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
              'remaining_free_bytes': shutil.disk_usage(output).free}
    write_json(output/'verification.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['master', 'tempo-midi', 'source-kick', 'prior-report', 'output-dir', 'title']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--port', type=int, default=8937)
    args = parser.parse_args()
    report = build(args.master, args.tempo_midi, args.source_kick, args.prior_report, args.output_dir, args.title, args.port)
    print(json.dumps({k: report[k] for k in ['complete', 'quarter_count', 'bytes', 'remaining_free_bytes']}, indent=2))


if __name__ == '__main__':
    main()
