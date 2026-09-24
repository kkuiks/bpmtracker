"""Render admitted click results separately from pending producer references."""
import argparse
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from acquire_reference_corpus import click_onsets
from inspect_inputs import sha256
from qualify_observed_click import match_quarters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--producer-audit', required=True, type=Path)
    parser.add_argument('--producer-predictions', required=True, type=Path)
    parser.add_argument('--click-catalog', required=True, type=Path)
    parser.add_argument('--benchmark', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    audit = json.loads(args.producer_audit.read_text())
    predictions = json.loads(args.producer_predictions.read_text())
    if predictions['scoring_performed'] or audit['strict_timing_scores_permitted']:
        raise ValueError('pending cohort must have no accuracy scores')
    pending = {r['id']: r for r in predictions['rows']}
    benchmark = json.loads(args.benchmark.read_text())
    row = benchmark['rows'][0]
    record = json.loads(args.click_catalog.read_text())['tracks'][0]
    observed = json.loads(Path(record['reference']['path']).read_text())
    declared_path = Path(observed['quarter_identity_source']['path'])
    declared = json.loads(declared_path.read_text())
    raw = np.asarray(declared['beats_seconds'])
    lo, hi = observed['evaluation_support_seconds']
    raw = raw[(raw >= lo) & (raw <= hi)]
    _, difference = match_quarters(raw, click_onsets(record['reference_click_path'])['times_seconds'])
    fig, axes = plt.subplots(2, 1, figsize=(11, 8))
    axes[0].plot(raw, difference*1000, lw=1.5)
    axes[0].axhline(-20, ls='--', color='#aa4444', label='20ms evaluation tolerance')
    axes[0].set(xlabel='Source time (s)', ylabel='Observed click minus MIDI (ms)',
                title='Reference disagreement — no model predictions involved')
    axes[0].legend()
    methods = ['official_minimal', 'meter_free_raw', 'current_clock', 'soft_prior_2', 'phase_consensus']
    x = np.arange(len(methods))
    for i, tolerance in enumerate(('10ms', '20ms', '70ms')):
        values = [100*row['scores']['declared_support'][m]['event_'+tolerance]['f1'] for m in methods]
        bars = axes[1].bar(x+(i-1)*.24, values, .24, label=tolerance)
        axes[1].bar_label(bars, fmt='%.1f', fontsize=8)
    axes[1].set_xticks(x, ['Official', 'Meter-free', 'Clock', 'BPM prior', 'Phase'])
    axes[1].set(ylabel='Event F1 (%)', ylim=(0, 112), title='Come Thou Long — 549 observed creator click quarters')
    axes[1].set_yticks(np.arange(0, 101, 20))
    axes[1].legend(ncols=3)
    fig.tight_layout()
    fig.savefig(args.output_dir/'reference-and-results.png', dpi=180)
    fig.savefig(args.output_dir/'reference-and-results.svg')
    plt.close(fig)
    table = []
    for a in audit['tracks']:
        p = pending[a['id']]
        clock = p['methods']['soft_prior_2']['clock']
        rates = ', '.join(f"{s['pulse_rate_per_minute']:.2f}" for s in clock['segments']) if clock else '지도 없음: 구간 수 제한'
        table.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
            [a['id'], ', '.join(f'{r:.2f}' for r in a['declared_quarter_rates_bpm']),
             a['declared_meter_changes'], rates, '미계산: 원점 미확정'])+'</tr>')
    document = '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>제작자 참조 검증</title>
<style>body{font:16px system-ui;max-width:1150px;margin:40px auto;padding:0 24px;background:#f7f8fa;color:#172d40}p{line-height:1.8}table{border-collapse:collapse;background:white;width:100%;font-size:14px}th,td{padding:12px;border:1px solid #d7dfe6;text-align:left}th{background:#e8eff5}img{width:100%}a{color:#175fc0}</style>
<h1>제작자 자료 확보와 정답 시간축 검증</h1>
<p>Daybreak Studio의 Equilibrium·Nocturne·Naysayer 세 녹음과 제작 MIDI를 확보했습니다. 세 곡은 한 제작자 집단입니다. Nocturne와 Naysayer는 제작자의 커버 녹음이며 원곡의 공식 스템이 아닙니다. 각 곡의 여러 MIDI는 템포·박자 지도가 일치하지만, 최종 믹스와 MIDI의 절대 원점은 아직 검증하지 못했습니다. 아래 자동 후보는 고정 설정의 예측이며, 20ms 정확도 점수는 계산하지 않았습니다.</p>
<table><thead><tr><th>녹음</th><th>MIDI BPM</th><th>MIDI 변박 횟수</th><th>자동 지도 구간 BPM</th><th>절대 시각 평가</th></tr></thead><tbody>'''
    document += ''.join(table)+'''</tbody></table>
<p>처리된 믹스와 원본 스템이 파형 대조 조건을 통과하지 못했다는 것은 현재 검증법으로 대응을 확정하지 못했다는 뜻입니다. 자료 자체가 틀렸다고 결론 내리지 않았고, 모델 출력으로 정답 원점을 맞추지도 않았습니다. Naysayer의 드럼 MIDI에는 믹스 길이 밖의 노트 1,107개가 있어 MIDI 길이를 음원 길이로 간주할 수도 없습니다.</p>
<p>별도 제작자 Wilding Studios의 Animal MIDI에서는 145→140→135→105 BPM과 박자 변경 정보를 확인했지만, 공개 묶음에서 완성 믹스를 확보하지 못해 이번 평가에 포함하지 않았습니다.</p>
<h2>실제 클릭으로 검증한 추가 곡</h2>
<p>Future of Forestry의 Come Thou Long Expected Jesus를 추가했습니다. 기존 아티스트의 다른 곡으로, 새로운 독립 아티스트 검증은 아닙니다. 이 곡은 제작 MIDI와 실제 클릭 사이에 최대 21.80ms 차이가 있어, MIDI는 4분음표의 신원을 정하는 데만 사용하고 실제 시각은 클릭 WAV에서 가져왔습니다. 평가 구간의 549개 박이 클릭의 매 두 번째 타격과 일대일 대응합니다. 음원·MIDI를 변경하거나 시간 이동을 피팅하지 않았습니다.</p>
<p>검증 범위는 약 2.580–357.109초이며 클릭 추출 해상도는 1ms입니다. 정확한 템포 변경점·다운비트 점수는 보류했습니다. 아래 점수는 관측된 클릭에 대한 박 위치 비교로, 템포·박자 지도 전체의 복원 성공률이 아닙니다. 기존 알고리즘·설정은 유지했으며 위치 보정은 보류되어 추가 개선이 없었습니다.</p>
<img src="reference-and-results.png" alt="MIDI와 실제 클릭의 차이 및 관측 클릭 기준 고정 설정 비교">
<p><a href="reference-and-results.svg">벡터 그림</a> · <a href="evidence.json">재현 근거 파일과 해시</a></p></html>'''
    (args.output_dir/'index.html').write_text(document)
    evidence = {'producer_audit': args.producer_audit, 'producer_predictions': args.producer_predictions,
                'click_catalog': args.click_catalog, 'click_benchmark': args.benchmark}
    (args.output_dir/'evidence.json').write_text(json.dumps({k: {'path': str(p), 'sha256': sha256(p)}
        for k, p in evidence.items()}, indent=2)+'\n')


if __name__ == '__main__':
    main()
