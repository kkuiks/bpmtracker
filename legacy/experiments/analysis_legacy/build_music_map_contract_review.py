"""Build deterministic original audio examples for a pending music-map policy.

These are constructed musical interpretations, not analyzer predictions or a
claim that either interpretation is correct. No external media is read.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import html
import json
import struct
from pathlib import Path

import numpy as np

from musical_units import MeterSpec, TempoSpec

LEAD = Fraction(1, 2)
TAIL = Fraction(1, 4)


def rational(value):
    value = Fraction(value)
    return {'numerator': value.numerator, 'denominator': value.denominator}


def sample_index(seconds, sample_rate):
    """Nearest native sample; exact rational half-up rounding, never accumulation."""
    value = Fraction(seconds) * sample_rate
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def specs():
    return [
        {'id': 'A', 'bars': 4, 'bar_seconds': Fraction(240, 85), 'subdivisions': 8,
         'title': 'A · 같은 마디 길이, 다른 박 밀도',
         'description': '마디는 둘 다 약 2.8235초입니다. 먼저 4분음표 클릭 4개와 8개의 차이를 들어 봅니다.',
         'variants': [
             {'id': 'a_85_4_4', 'title': '85 BPM · 4/4', 'bpm': 85, 'meter': (4, 4),
              'click_q': Fraction(1), 'grouping': None, 'optional': False,
              'click_label': '4분음표 클릭', 'note': '마디당 클릭 4개. 중간 묶음 강세는 추가하지 않았습니다.'},
             {'id': 'a_170_8_4', 'title': '170 BPM · 8/4', 'bpm': 170, 'meter': (8, 4),
              'click_q': Fraction(1), 'grouping': None, 'optional': False,
              'click_label': '4분음표 클릭', 'note': '마디당 클릭 8개. 8/4의 내부 묶음은 정하지 않았습니다.'},
             {'id': 'a_170_8_4_grouped', 'title': '추가 가정 · 170 BPM, 8/4를 2+2+2+2로 묶기',
              'bpm': 170, 'meter': (8, 4), 'click_q': Fraction(2), 'grouping': [2, 2, 2, 2],
              'optional': True, 'click_label': '2분음표 길이의 묶음 시작만 클릭',
              'note': '묶음 시작만 들리게 하면 85 BPM·4/4 클릭과 시각·소리가 동일합니다. 내부 묶음과 클릭 생략이라는 추가 가정을 넣은 예시이며, 기본 동등성 판정이 아닙니다.'},
         ]},
        {'id': 'B', 'bars': 6, 'bar_seconds': Fraction(3, 2), 'subdivisions': 6,
         'title': 'B · 같은 4분음표 BPM과 마디 길이, 다른 묶음',
         'description': '둘 다 표기상 4분음표 BPM은 120이고 한 마디는 1.5초입니다. 주박 클릭은 3/4에서 분당 120번, 6/8의 3+3 묶음에서 분당 80번입니다.',
         'variants': [
             {'id': 'b_120_3_4', 'title': '120 BPM · 3/4 · 2+2+2개의 8분음표',
              'bpm': 120, 'meter': (3, 4), 'click_q': Fraction(1), 'grouping': [1, 1, 1],
              'optional': False, 'click_label': '4분음표 주박 클릭',
              'note': '4분음표 3개로 묶습니다. 8분음표로 세면 2+2+2입니다.'},
             {'id': 'b_120_6_8', 'title': '120 BPM · 6/8 · 3+3개의 8분음표',
              'bpm': 120, 'meter': (6, 8), 'click_q': Fraction(3, 2), 'grouping': [3, 3],
              'optional': False, 'click_label': '점4분음표 주박 클릭',
              'note': '점4분음표 2개로 묶습니다. 실제 클릭률 80은 표기상 4분음표 BPM 120과 다른 단위의 수치입니다.'},
             {'id': 'b_shared_eighths', 'title': '공통 세분 기준 · 8분음표 6개 클릭',
              'bpm': 120, 'meter': None, 'click_q': Fraction(1, 2), 'grouping': None,
              'optional': True, 'click_label': '8분음표 세분 클릭',
              'note': '분당 240번, 마디당 6개입니다. 내부 묶음 강세를 넣지 않은 공통 세분 기준이며, 특정 박자 해석을 제출한 것이 아닙니다.'},
         ]},
    ]


def point(seconds, sample_rate, **fields):
    frame = sample_index(seconds, sample_rate)
    return {'source_seconds_exact': rational(seconds), 'source_seconds': float(seconds),
            'onset_sample_index': frame, 'rendered_source_seconds': frame / sample_rate, **fields}


def variant_metadata(pair, variant, sample_rate):
    bpm = Fraction(variant['bpm'])
    tempo_spec = TempoSpec(float(bpm), Fraction(1))
    click_tempo_spec = TempoSpec(float(bpm / variant['click_q']), variant['click_q'])
    if tempo_spec.quarter_bpm != click_tempo_spec.quarter_bpm:
        raise ValueError('notated and click units must describe the same physical tempo')
    meter_spec = None
    bar_q = pair['bar_seconds'] * bpm / 60
    if variant['meter']:
        numerator, denominator = variant['meter']
        meter_spec = MeterSpec(numerator, denominator, tuple(variant['grouping']) if variant['grouping'] is not None else None)
        if meter_spec.quarters_per_bar != bar_q:
            raise ValueError('declared meter/tempo does not preserve pair bar length')
        meter = {'numerator': numerator, 'denominator': denominator,
                 'grouping_in_denominator_units': variant['grouping']}
    else:
        meter = None
    if bar_q % variant['click_q']:
        raise ValueError('click pattern must fit complete bars')
    clicks_per_bar = int(bar_q / variant['click_q'])
    events = []
    for bar in range(pair['bars']):
        for ordinal in range(clicks_per_bar):
            local_q = ordinal * variant['click_q']
            t = LEAD + bar * pair['bar_seconds'] + local_q * 60 / bpm
            events.append(point(t, sample_rate, bar_index=bar, click_index_in_bar=ordinal,
                                quarter_position=rational(bar * bar_q + local_q),
                                kind='bar_start' if ordinal == 0 else 'pulse',
                                audible_accent='bar' if ordinal == 0 else 'regular'))
    groups = None
    if variant['grouping'] is not None:
        groups = []
        starts = meter_spec.group_offsets_quarters
        for bar in range(pair['bars']):
            for ordinal, local_q in enumerate(starts):
                groups.append(point(LEAD + bar * pair['bar_seconds'] + local_q * 60 / bpm,
                                    sample_rate, bar_index=bar, group_index_in_bar=ordinal,
                                    quarter_position=rational(bar * bar_q + local_q)))
    return {'id': variant['id'], 'title_ko': variant['title'], 'note_ko': variant['note'],
            'optional': variant['optional'], 'role': 'shared_subdivision_reference' if meter is None else 'constructed_interpretation',
            'meter': meter, 'quarter_bpm': rational(bpm),
            'declared_tempo': tempo_spec.to_dict(), 'rendered_click_tempo': click_tempo_spec.to_dict(),
            'declared_meter': meter_spec.to_dict() if meter_spec else None,
            'tempo_bpm_unit': 'quarter_note', 'bar_duration_seconds_exact': rational(pair['bar_seconds']),
            'bar_duration_quarters': rational(bar_q), 'click_unit_quarters': rational(variant['click_q']),
            'actual_click_rate_per_minute': rational(bpm / variant['click_q']),
            'click_label_ko': variant['click_label'], 'clicks_per_bar': clicks_per_bar,
            'click_events': events, 'group_boundaries': groups,
            'grouping_policy': 'explicit constructed grouping' if groups is not None else 'not asserted',
            'equivalence_claim': 'pending user policy; none asserted by generator'}


def synth_backing(pair, sample_rate, frames):
    """Neutral equally loud subdivisions plus one softly changing chord per bar."""
    audio = np.zeros(frames, dtype=np.float64)
    length = max(1, round(.13 * sample_rate))
    tau = np.arange(length) / sample_rate
    pluck = .085 * np.exp(-tau / .042) * (np.sin(2 * np.pi * 440 * tau) + .24 * np.sin(2 * np.pi * 880 * tau))
    notes = []
    roots = [130.8128, 146.8324, 164.8138, 146.8324, 130.8128, 164.8138]
    for bar in range(pair['bars']):
        t0 = LEAD + bar * pair['bar_seconds']
        start, end = sample_index(t0, sample_rate), sample_index(t0 + pair['bar_seconds'], sample_rate)
        local = np.arange(end - start) / sample_rate
        envelope = np.minimum(1., local / .035) * np.minimum(1., (end - start - 1 - np.arange(end - start)) / (.05 * sample_rate))
        envelope = np.maximum(envelope, 0)
        root = roots[bar % len(roots)]
        chord = sum(np.sin(2 * np.pi * root * ratio * local) for ratio in (1., 1.25, 1.5))
        audio[start:end] += .017 * envelope * chord
        for subdivision in range(pair['subdivisions']):
            exact = t0 + pair['bar_seconds'] * subdivision / pair['subdivisions']
            index = sample_index(exact, sample_rate)
            stop = min(frames, index + length)
            audio[index:stop] += pluck[:stop-index]
            notes.append(point(exact, sample_rate, bar_index=bar, subdivision_index=subdivision,
                               amplitude=.085, internal_accent=False))
    return audio.astype(np.float32), notes


def synth_click(events, sample_rate, frames):
    audio = np.zeros(frames, dtype=np.float64)
    length = max(1, round(.028 * sample_rate))
    tau = np.arange(length) / sample_rate
    for event in events:
        strong = event['audible_accent'] == 'bar'
        frequency, amplitude = (1600., .23) if strong else (1100., .16)
        tone = amplitude * np.exp(-tau / .0045) * (np.cos(2*np.pi*frequency*tau) + .2*np.cos(4*np.pi*frequency*tau)) / 1.2
        start = event['onset_sample_index'];end = min(frames, start+length)
        audio[start:end] += tone[:end-start]
    return audio.astype(np.float32)


def write_float_wav(path, samples, sample_rate):
    """Write mono IEEE-float RIFF without timestamp-bearing optional chunks."""
    samples = np.asarray(samples, dtype='<f4')
    if samples.ndim != 1 or not np.isfinite(samples).all():
        raise ValueError('audio must be finite mono samples')
    payload = samples.tobytes()
    fmt = struct.pack('<HHIIHH', 3, 1, sample_rate, sample_rate * 4, 4, 32)
    chunks = (b'fmt ' + struct.pack('<I', len(fmt)) + fmt +
              b'fact' + struct.pack('<II', 4, len(samples)) +
              b'data' + struct.pack('<I', len(payload)) + payload)
    Path(path).write_bytes(b'RIFF' + struct.pack('<I', 4 + len(chunks)) + b'WAVE' + chunks)


def short_rate(value):
    q = Fraction(value['numerator'], value['denominator'])
    return str(q.numerator) if q.denominator == 1 else f'{float(q):.4f}'


def diagram_svg(pair, variant):
    """Diagram one complete bar; physical time width stays identical per pair."""
    left, right, top = 64, 730, 86
    clicks = variant['clicks_per_bar'];subs = pair['subdivisions']
    fragments = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 790 190" role="img" aria-label="한 마디의 세분 위치와 실제 클릭 위치">',
        '<rect width="790" height="190" rx="12" fill="#f7f8fa"/>',
        '<text x="24" y="28" font-family="sans-serif" font-size="15" fill="#27344b">한 마디 · 가로 길이는 실제 시간</text>',
        f'<line x1="{left}" y1="{top}" x2="{right}" y2="{top}" stroke="#768396" stroke-width="2"/>']
    for i in range(subs+1):
        x = left + (right-left)*i/subs
        fragments.append(f'<line x1="{x:.3f}" y1="68" x2="{x:.3f}" y2="103" stroke="#ced4df"/>')
    for i in range(clicks):
        x = left + (right-left)*i/clicks
        color = '#b24c25' if i == 0 else '#246593'
        fragments.append(f'<circle cx="{x:.3f}" cy="{top}" r="{9 if i == 0 else 7}" fill="{color}"/>')
        fragments.append(f'<text x="{x:.3f}" y="132" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#253248">{i+1}</text>')
    fragments.extend([f'<line x1="{left}" y1="48" x2="{left}" y2="111" stroke="#b24c25" stroke-width="3"/>',
        f'<line x1="{right}" y1="48" x2="{right}" y2="111" stroke="#b24c25" stroke-width="3"/>',
        '<text x="64" y="169" font-family="sans-serif" font-size="13" fill="#526075">갈색: 마디 시작 · 파랑: 들리는 클릭 · 회색: 같은 반주의 세분</text>', '</svg>'])
    return '\n'.join(fragments)


def html_page(metadata):
    esc = html.escape
    panels=[]
    for pair in metadata['pairs']:
        def panel(v):
            meter = f"{v['meter']['numerator']}/{v['meter']['denominator']}" if v['meter'] else '미지정 · 공통 세분 기준'
            return f'''<article class="card"><h3>{esc(v['title_ko'])}</h3>
<table><tr><th>박자 표기</th><td>{meter}</td></tr><tr><th>표기상 4분음표 BPM</th><td>{short_rate(v['quarter_bpm'])}</td></tr>
<tr><th>실제 클릭 단위</th><td>{esc(v['click_label_ko'])}</td></tr><tr><th>실제 클릭률 · 분당</th><td>{short_rate(v['actual_click_rate_per_minute'])}</td></tr>
<tr><th>마디 길이 · 초</th><td>{short_rate(v['bar_duration_seconds_exact'])}</td></tr><tr><th>한 마디의 클릭 수</th><td>{v['clicks_per_bar']}</td></tr></table>
<img src="{v['diagram_path']}" alt="한 마디의 실제 클릭 간격"/><p>{esc(v['note_ko'])}</p>
<label>같은 반주 + 이 클릭<audio controls preload="metadata" data-pair="{pair['id']}" src="{v['mixed_audio_path']}"></audio></label>
<details><summary>클릭만 듣기</summary><audio controls preload="metadata" data-pair="{pair['id']}" src="{v['click_audio_path']}"></audio></details></article>'''
        primary=''.join(panel(v) for v in pair['variants'] if not v['optional'])
        optional=''.join(panel(v) for v in pair['variants'] if v['optional'])
        panels.append(f'''<section><h2>{esc(pair['title_ko'])}</h2><p>{esc(pair['description_ko'])}</p>
<p>공통 시작 여백 0.5초 · {pair['bar_count']}마디 · 두 기본 해석의 마디 시작·끝은 같습니다.</p>
<details><summary>공통 반주만 듣기</summary><audio controls preload="metadata" data-pair="{pair['id']}" src="{pair['backing_audio_path']}"></audio></details>
<div class="pair">{primary}</div><details class="optional"><summary>추가 구성 예시 보기 · 기본 동등성 판정 아님</summary>{optional}</details></section>''')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>음악 지도 표기와 클릭 비교</title><style>
body{font-family:system-ui,"Malgun Gothic",sans-serif;background:#eef1f5;color:#1c293a;margin:0;padding:24px;line-height:1.65}main{max-width:1200px;margin:auto}h1{font-size:1.8rem}h2{margin-top:0}section{background:white;border-radius:16px;padding:24px;margin:28px 0}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:20px}.card{border:1px solid #d5dce6;border-radius:12px;padding:18px}.card h3{margin-top:0}.card img{width:100%;height:auto}table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{text-align:left;padding:6px;border-bottom:1px solid #e6eaf0}th{font-weight:500;width:57%;color:#45546b}audio{display:block;width:100%;margin:8px 0 14px}.notice{background:#e0e9f4;padding:16px;border-radius:10px}.optional{margin-top:20px}.optional .card{margin-top:14px}summary{cursor:pointer;color:#194d75}small{color:#4d5f77}@media(max-width:760px){.pair{grid-template-columns:1fr}body{padding:12px}section{padding:16px}}
</style><main><h1>음악 지도 표기와 클릭 비교</h1>
<p class="notice">직접 만든 합성 예시입니다. 각 비교 안에서는 반주 파일과 마디 시간표를 동일하게 유지했습니다. 어느 표기를 정답으로 인정할지는 아직 결정하지 않았습니다. 음악적 묶음과 실제 클릭 단위가 달라지는 부분을 듣고 볼 수 있도록 구성했습니다.</p>
<p>플레이어를 바꾸면 같은 비교 안의 재생 중인 소리는 멈추고, 가능한 경우 같은 위치에서 이어집니다. 처음부터 비교하려면 재생 위치를 0으로 돌려 주세요.</p>
''' + ''.join(panels) + '''<p><a href="events.json">정확한 단위·마디·샘플 위치 기록</a> · <a href="manifest.json">생성 파일 정보</a></p>
<small>이 예시는 실제 분석기의 출력이나 성능 평가가 아닙니다. 어떤 동등성 규칙도 자동으로 승인하지 않습니다.</small></main>
<script>for(const a of document.querySelectorAll('audio')){a.addEventListener('play',()=>{for(const b of document.querySelectorAll('audio')){if(a!==b&&!b.paused){const same=a.dataset.pair===b.dataset.pair;const t=b.currentTime;b.pause();if(same&&Number.isFinite(t)){try{a.currentTime=t;}catch(e){}}}}});}</script></html>'''


def build_review(output_dir, sample_rate=48000):
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 192000:
        raise ValueError('sample_rate must be an integer from 8000 to 192000')
    output_dir=Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('review output directory must be new or empty; existing examples are preserved')
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata={'schema_version':1,'scope':'original deterministic synthetic listening examples; interpretation policy pending',
              'equivalence_policy_decided':False,'model_predictions':False,'external_media_used':False,
              'sample_rate':sample_rate,'audio_channels':1,'audio_subtype':'FLOAT',
              'source_origin_seconds':0,'lead_in_seconds_exact':rational(LEAD),
              'sample_rounding':'nearest native sample, exact rational half-up; each onset independently rounded',
              'click_sound':'bar start:1600Hz, amplitude0.23; other clicks:1100Hz, amplitude0.16; same synthesis in all variants',
              'pairs':[]}
    for pair in specs():
        duration=LEAD+pair['bars']*pair['bar_seconds']+TAIL
        frames=sample_index(duration,sample_rate)
        backing,notes=synth_backing(pair,sample_rate,frames)
        backing_name=pair['id'].lower()+'_shared_backing.wav'
        write_float_wav(output_dir/backing_name,backing,sample_rate)
        entry={'id':pair['id'],'title_ko':pair['title'],'description_ko':pair['description'],
               'bar_count':pair['bars'],'bar_duration_seconds_exact':rational(pair['bar_seconds']),
               'sample_frames':frames,'rendered_duration_seconds':frames/sample_rate,
               'duration_seconds_exact':rational(duration),'backing_audio_path':backing_name,
               'backing_sha256':hashlib.sha256((output_dir/backing_name).read_bytes()).hexdigest(),
               'backing_description':'equal internal subdivision plucks; same-amplitude chord once per bar; no internal grouping accents',
               'backing_subdivision_count_per_bar':pair['subdivisions'],'backing_events':notes,
               'bar_boundaries':[point(LEAD+i*pair['bar_seconds'],sample_rate,bar_boundary_index=i) for i in range(pair['bars']+1)],
               'variants':[]}
        for spec in pair['variants']:
            v=variant_metadata(pair,spec,sample_rate)
            click=synth_click(v['click_events'],sample_rate,frames)
            mix=(backing+click).astype(np.float32)
            if np.max(np.abs(mix))>=.99:raise ValueError('synthesis exceeds fixed headroom; no content-dependent normalization allowed')
            v.update(backing_audio_path=backing_name,backing_sha256=entry['backing_sha256'],
                     click_audio_path=v['id']+'_click.wav',mixed_audio_path=v['id']+'_mix.wav',diagram_path=v['id']+'.svg',
                     sample_frames=frames,sample_rate=sample_rate,mix_peak=float(np.max(np.abs(mix))))
            write_float_wav(output_dir/v['click_audio_path'],click,sample_rate)
            write_float_wav(output_dir/v['mixed_audio_path'],mix,sample_rate)
            (output_dir/v['diagram_path']).write_text(diagram_svg(pair,v),encoding='utf-8')
            entry['variants'].append(v)
        metadata['pairs'].append(entry)
    (output_dir/'events.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (output_dir/'index.html').write_text(html_page(metadata),encoding='utf-8')
    manifest={'schema_version':1,'generator_path':str(Path(__file__)),'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'sample_rate':sample_rate,'equivalence_policy_decided':False,'deterministic':True,
              'dependency_sha256':{'musical_units.py':hashlib.sha256(Path(__file__).with_name('musical_units.py').read_bytes()).hexdigest()},
              'files':{p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(output_dir.iterdir()) if p.is_file()}}
    (output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--sample-rate',type=int,default=48000)
    args=parser.parse_args()
    result=build_review(args.output_dir,args.sample_rate)
    print(json.dumps({'output_dir':str(args.output_dir),'pair_count':len(result['pairs']),'sample_rate':args.sample_rate,'equivalence_policy_decided':False}))


if __name__=='__main__':main()
