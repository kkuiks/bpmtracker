"""Turn saved accepted quarters into an offline listening pack, without inference."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import zipfile

import numpy as np
import soundfile as sf

from experiments.bpm_initialization_v1.common import METHODS, guard
from experiments.bpm_continuity_v1.common import ROOT, read, write, digest
from experiments.bpm_continuity_v1.evaluate import emitted

HERE = Path(__file__).resolve().parent
LABELS = {
    'MUSIC': '원음만', 'I0_LOCAL6': '기존 6초',
    'I1_WHOLE_RATE_LOCAL6': '전체 곡 BPM', 'I2_LOCAL12': '시작 12초',
    'I3_LOCAL24': '시작 24초', 'REFERENCE': '실험 당시 참조',
}
CASES = [
    {'id': 'src0096', 'start': 20., 'end': 65., 'topic': '클릭이 계속 유지되는 차이',
     'guide': '먼저 전체 곡 BPM을 듣다가 기존 6초로 바꿔보세요. 원음 44.25초 이후에는 기존 클릭이 보류되고 전체 곡 방식은 계속 출력합니다. 12초 방식과 24초 방식도 같은 구간에서 비교할 수 있습니다.',
     'suggested': 'I1_WHOLE_RATE_LOCAL6'},
    {'id': 'src0502', 'start': 20., 'end': 65., 'topic': '작은 BPM 오류와 출력 공백',
     'guide': '기존 6초와 시작 12초는 원음 29.5초 이후 클릭이 끊겼다가 일부 구간에서 돌아옵니다. 전체 곡 BPM과 시작 24초에서는 더 길게 유지됩니다.',
     'suggested': 'I1_WHOLE_RATE_LOCAL6'},
    {'id': 'src0097', 'start': 56., 'end': 80., 'topic': '시작 실패와 남아 있는 출력 공백',
     'guide': '전체 곡 BPM에서도 클릭이 군데군데 보류됩니다. 시작 24초는 곡의 초기 시계를 확정하지 못해 이 구간 전체에서 클릭을 출력하지 않습니다.',
     'suggested': 'I1_WHOLE_RATE_LOCAL6'},
    {'id': 'src0499', 'start': 40., 'end': 60., 'topic': '약 33ms의 클릭 위치 편차',
     'guide': '전체 곡 BPM과 참조를 같은 위치에서 번갈아 들어보세요. 클릭만 모드로 들으면 차이에 집중할 수 있습니다. 좌우 비교는 참조를 왼쪽, 전체 곡 방식의 클릭을 오른쪽에 놓으며 시간 차이를 확대하지 않습니다.',
     'suggested': 'I1_WHOLE_RATE_LOCAL6'},
    {'id': 'src0098', 'start': 0., 'end': 28., 'topic': '더 오래 기다리는 대가',
     'guide': '모두 124 BPM을 골랐지만 클릭이 시작되는 시각이 다릅니다. 원음 처음부터 기존 6초, 시작 12초, 시작 24초를 들어보세요. 전체 곡 방식은 기존 6초와 같은 출력을 냅니다.',
     'suggested': 'I0_LOCAL6'},
]


def pulse(rate, gain):
    t = np.arange(round(.015 * rate)) / rate
    value = gain * np.cos(2 * np.pi * 1800 * t) * np.exp(-t / .0035)
    value[-min(16, len(value)):] *= np.linspace(1., 0., min(16, len(value)))
    return value.astype(np.float32)


def render_click(events, frames, rate, source_start, click_gain):
    result = np.zeros(frames, dtype=np.float32); tone = pulse(rate, click_gain)
    placements = []
    end = source_start + frames / rate
    for event in events:
        if not source_start <= event < end:
            continue
        index = round((float(event) - source_start) * rate)
        if index >= frames:
            # A timestamp less than half a frame from the half-open end may
            # round to the first out-of-excerpt sample; never move it backward.
            continue
        length = min(len(tone), frames - index)
        result[index:index + length] += tone[:length]
        placements.append({'source_seconds': float(event), 'excerpt_sample': index,
                           'excerpt_seconds': index / rate,
                           'rounding_error_ms': (source_start + index / rate - float(event)) * 1000})
    return result, placements


def wav(path, signal, rate):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not np.isfinite(signal).all() or float(np.max(np.abs(signal), initial=0)) > .999:
        raise ValueError(f'Nonfinite/clipping listening audio: {path.name}')
    sf.write(path, signal, rate, subtype='PCM_16')


def clipped_spans(prediction, start, end):
    result = []
    for span in prediction.get('spans', []):
        a, b = max(start, span['start']), min(end, span['end'])
        if b > a:
            result.append({'start': a - start, 'end': b - start,
                           'status': span['status'], 'reason': span['reason'],
                           'bpm': span.get('bpm')})
    return result


def prepare(run, output):
    guard(run)
    if not read(run / 'completion-review.json')['all_96_predictions_scored_without_dropped_recordings']:
        raise ValueError('Listening requires a completed frozen experiment')
    output.mkdir(parents=True, exist_ok=False)
    source_rows = {r['id']: r for r in read(run / 'source-manifest.json')['samples']}
    metadata = {r['id']: r for r in read(run / 'evaluation-manifest.json')['samples']}
    exclusion_path = ROOT / 'data/samples/excluded-candidates.json'
    excluded = read(exclusion_path)['candidates']
    decoded = {}; max_music_peak = 0.
    for case in CASES:
        ident = case['id']; row = metadata[ident]; source = source_rows[ident]
        if any(e.get('permanent_exclusion') and
               (row['original_id'] == e.get('id') or e.get('slug', 'NEVER') in source['inherited_audio_path'] or
                row['title'].casefold() == e.get('title', '').casefold()) for e in excluded):
            raise ValueError('Permanently excluded source')
        path = Path(source['inherited_audio_path'])
        with sf.SoundFile(path) as reader:
            first = round(case['start'] * reader.samplerate)
            last = min(reader.frames, round(case['end'] * reader.samplerate))
            reader.seek(first)
            signal = reader.read(last - first, dtype='float32', always_2d=True)
            if signal.shape[1] == 1:
                signal = np.repeat(signal, 2, axis=1)
            if signal.shape[1] != 2 or not np.isfinite(signal).all():
                raise ValueError('Finite mono/stereo source required')
            decoded[ident] = (signal, reader.samplerate, first, last, reader.frames)
        max_music_peak = max(max_music_peak, float(np.max(np.abs(signal))))
    click_gain = .30
    music_gain = min(.45, (.96 - click_gain) / max(max_music_peak, 1e-12))
    cases = []; render_receipts = []
    for case in CASES:
        ident = case['id']; row = metadata[ident]; source = source_rows[ident]
        signal, rate, first, last, full_frames = decoded[ident]
        start, end = first / rate, last / rate; frames = len(signal)
        music = signal * music_gain; base = Path('audio') / ident
        music_path = output / base / 'music.wav'; wav(music_path, music, rate)
        frozen_reference_path = Path(row['reference_path']); reference = read(frozen_reference_path)
        if reference['additional_offset_applied_seconds'] != 0:
            raise ValueError('Unexpected second reference offset')
        variants = {'MUSIC': {'label': LABELS['MUSIC'], 'mix': str(base / 'music.wav'),
                               'click': None, 'seed': None, 'spans': [], 'event_times': []}}
        rendered_clicks = {}
        for method in (*METHODS, 'REFERENCE'):
            if method == 'REFERENCE':
                events = np.array(reference['quarters']); seed = None
                spans = [{'start': max(a, start) - start, 'end': min(b, end) - start,
                          'status': 'ACCEPTED', 'reason': 'FROZEN_EVALUATION_REFERENCE',
                          'bpm': reference['initial_bpm']}
                         for a, b in reference['support'] if min(b, end) > max(a, start)]
                input_receipt = {'path': str(frozen_reference_path), 'sha256': digest(frozen_reference_path),
                                 'reference_only_diagnostic': True}
            else:
                prediction_path = run / 'predictions' / method / 'proxy_unit_zero' / (ident + '.json')
                prediction = read(prediction_path)
                events = emitted(prediction)
                boot = read(run / 'bootstrap' / method / 'proxy_unit_zero' / (ident + '.json'))
                seed = {'status': boot['status'], 'time': boot['seed']['time'] if boot['seed'] else None,
                        'bpm': boot['seed']['clock']['bpm'] if boot['seed'] else None}
                spans = clipped_spans(prediction, start, end)
                input_receipt = {'path': str(prediction_path), 'sha256': digest(prediction_path),
                                 'emitted_accepted_quarters_only': True, 'unknown_not_filled': True}
            click, placements = render_click(events, frames, rate, start, click_gain)
            rendered_clicks[method] = click
            stem_rel = base / 'stems' / (method + '.wav'); wav(output / stem_rel, click, rate)
            mix_rel = base / (method + '.wav'); wav(output / mix_rel, music + click[:, None], rate)
            variants[method] = {'label': LABELS[method], 'mix': str(mix_rel), 'click': str(stem_rel),
                                'seed': seed, 'spans': spans,
                                'event_times': [p['excerpt_seconds'] for p in placements]}
            render_receipts.append({'id': ident, 'method': method, 'input': input_receipt,
                                    'sample_rate': rate, 'frames': frames, 'events': placements,
                                    'max_absolute_sample_rounding_ms': max((abs(p['rounding_error_ms']) for p in placements), default=0.),
                                    'click_peak': float(np.max(np.abs(click), initial=0)),
                                    'mix_peak': float(np.max(np.abs(music + click[:, None]), initial=0))})
        pair = None
        if ident == 'src0499':
            pair = str(base / 'REFERENCE_left_WHOLE_right.wav')
            wav(output / pair, np.column_stack((rendered_clicks['REFERENCE'], rendered_clicks['I1_WHOLE_RATE_LOCAL6'])), rate)
        cases.append({**case, 'title': row['title'], 'source_start': start, 'source_end': end,
                      'duration': frames / rate, 'sample_rate': rate,
                      'variants': variants, 'stereo_diagnostic': pair,
                      'source_receipt': {'canonical_source_path': source['inherited_audio_path'],
                                         'inherited_audio_sha256': source['inherited_audio_sha256'],
                                         'audio_bytes_rehashed_this_preparation': False,
                                         'full_source_frames': full_frames, 'first_frame': first,
                                         'last_frame_exclusive': last,
                                         'frozen_reference_sha256': digest(frozen_reference_path)}})
        print('RENDERED', ident, round(frames / rate, 2), 's', flush=True)
    manifest = {'format': 'bpm-initialization-offline-listening', 'version': 1,
                'created_at_utc': datetime.now(timezone.utc).isoformat(), 'frozen_run': str(run),
                'experiment_recording_denominator': 8, 'listening_excerpt_count': len(cases),
                'policy': 'proxy_unit_zero; same-unit ±5% outputs identical in frozen run',
                'selection': 'Explanatory excerpts: two recoveries, retained support gaps, phase error and waiting; not a new benchmark',
                'music_gain': music_gain, 'click_gain': click_gain,
                'same_click_timbre_and_gain_for_every_method_and_reference': True,
                'reference_click_is_evaluation_diagnostic_not_a_predictor': True,
                'offset_adjustment_or_delay_exaggeration_seconds': 0,
                'originals_references_predictions_metrics_modified': False,
                'inference_rerun': False, 'browser_server_started': False,
                'excluded_candidates_checked_sha256': digest(exclusion_path), 'cases': cases}
    write(output / 'manifest.json', manifest)
    write(output / 'render-receipts.json', {'rows': render_receipts, 'no_filled_unknown_or_added_ticks': True,
                                           'rendering_only_not_human_listening_validation': True})
    html = (HERE / 'listen-template.html').read_text(encoding='utf-8')
    embedded = json.dumps(manifest, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    (output / 'listen.html').write_text(html.replace('__LISTEN_MANIFEST__', embedded), encoding='utf-8')
    (output / 'Open Listening.cmd').write_text('@echo off\r\nstart "" "%~dp0listen.html"\r\n', encoding='ascii')
    guide = '''Windows에서 `Open Listening.cmd`를 실행하거나 `listen.html`을 브라우저로 엽니다.

1. DIE 4 U에서 재생한 뒤 **기존 6초 / 전체 곡 BPM**을 바꿔보세요. 숫자 1/2도 가능합니다. 같은 음악 위치를 유지합니다.
2. Meet Your Maker와 Prayer Position도 비교하세요. 보류된 클릭은 청취 파일에서도 소리가 나지 않습니다.
3. Nocturne에서는 **좌우 클릭 비교**를 선택하고 헤드폰으로 듣습니다. 왼쪽은 실험 당시 참조, 오른쪽은 전체 곡 방식입니다. 실제 약 33ms 차이를 확대하지 않았습니다.
4. San Quentin은 처음부터 재생하며 6초 / 12초 / 24초를 비교하면 추가 대기를 들을 수 있습니다.

**클릭만**은 원음을 제외합니다. **구간 반복**은 현재 발췌를 반복합니다. 참조는 실험 당시의 저장된 승인 참조이며 비교용입니다.
전체 곡 BPM 방식도 오프라인 결과입니다. 이 청취는 실제 사람의 탭 수집이나 새로운 성능 평가가 아닙니다.

DAW에서는 각 곡 폴더의 `music.wav`와 `stems/*.wav`를 같은 시작점에 서로 다른 트랙으로 가져옵니다.
음악 트랙과 비교할 클릭 트랙 하나만 켜고, 프로젝트 메트로놈은 끕니다. 원음과 클릭 음량을 따로 조절할 수 있습니다.
이 WAV는 일반 오디오이므로 현재 Joljak SDK/Studio와 기존 DAW 모두에 가져올 수 있습니다.

파일은 발췌 청취용입니다. 전체 8곡의 수치와 전체 출력은 원래 실험 보고서를 봅니다.
원본 음원·승인 참조·동결 예측·점수를 변경하지 않았습니다. 모델을 다시 실행하거나 HTTP 서버를 시작하지 않았습니다.
'''
    (output / '사용 안내.md').write_text(guide, encoding='utf-8')
    snapshot = output / 'preparation-code'; snapshot.mkdir()
    for path in HERE.iterdir():
        if path.is_file():
            shutil.copy2(path, snapshot / path.name)
    # Bundle relative assets for double-click listening after extracting on Windows.
    archive = output / 'BPM-listening.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path != archive:
                bundle.write(path, str(path.relative_to(output)))
    write(output / 'completion.json', {'completed': True, 'cases': len(cases),
                                      'mixed_choices_per_case': 6, 'stems_per_case': 5,
                                      'stereo_diagnostic_count': 1,
                                      'archive_bytes': archive.stat().st_size,
                                      'human_listening_or_browser_runtime_tests_performed': False,
                                      'frozen_experiment_preserved': True})
    print('LISTENING_PACK', output, flush=True)
    print('ZIP_MIB', round(archive.stat().st_size / 1024 / 1024, 2), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); run = args.run.resolve()
    output = (args.output or ROOT / 'data/research/listening/bpm_initialization_v1' /
              (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-v1')).resolve()
    prepare(run, output)


if __name__ == '__main__':
    main()
