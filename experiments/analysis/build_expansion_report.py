"""Render cohort-separated expansion metrics and explicitly labeled oracles."""
import argparse
import csv
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from inspect_inputs import sha256


LABELS = {'official_minimal': 'Official model', 'meter_free_raw': 'Meter-free pulses',
          'current_clock': 'Continuous clock', 'soft_prior_2': 'Soft BPM prior',
          'phase_consensus': 'Shared phase correction'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmarks', type=Path, nargs='+', required=True)
    parser.add_argument('--diagnoses', type=Path, nargs='*', default=[])
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    benchmarks = [json.loads(p.read_text()) for p in args.benchmarks]
    rows = [r for report in benchmarks for r in report['rows']]
    summaries = {k: v for report in benchmarks for k, v in report['summary'].items()}
    if len(rows) != len({r['id'] for r in rows}):
        raise ValueError('duplicate recordings')
    diagnoses = {r['id']: r for p in args.diagnoses for r in json.loads(p.read_text())['rows']}
    fig, axes = plt.subplots(len(summaries), 1, figsize=(11, 4*len(summaries)), squeeze=False)
    for ax, (cohort, summary) in zip(axes[:, 0], summaries.items()):
        x = np.arange(len(LABELS))
        for index, tolerance in enumerate(('10ms', '20ms', '70ms')):
            values = [100*summary['methods'][m]['declared_support']['macro_f1_'+tolerance] for m in LABELS]
            bars = ax.bar(x+(index-1)*.24, values, width=.24, label=tolerance)
            ax.bar_label(bars, fmt='%.1f', fontsize=8)
        ax.set_xticks(x, list(LABELS.values()), fontsize=9)
        ax.set_ylim(0, 124)
        ax.set_yticks(np.arange(0, 101, 20))
        ax.set_ylabel('Recording macro event F1 (%)')
        ax.set_title(f"{cohort}: {summary['recordings']} recording(s), {summary['group_count']} group(s)")
        ax.legend(loc='upper left', ncols=3)
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('Frozen settings on newly acquired recordings — no automatic default promoted', fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(args.output_dir/'comparison.png', dpi=180)
    fig.savefig(args.output_dir/'comparison.svg')
    plt.close(fig)
    headers = ['Recording', 'Cohort', 'Group', 'Style', *LABELS.values(), 'Candidate selection',
               'Oracle existing pool', 'Oracle phase only']
    table = []
    for row in rows:
        diagnosis = diagnoses.get(row['id'])
        values = [100*row['scores']['declared_support'][m]['event_20ms']['f1'] for m in LABELS]
        extra = [diagnosis[k]*100 if diagnosis and diagnosis.get(k) is not None else None for k in
                 ('selected_f1_20ms', 'oracle_available_pool_f1_20ms', 'oracle_common_phase_f1_20ms')]
        table.append([row['id'], row['dataset'], row['group_id'], row['genre'], *values, *extra])
    with (args.output_dir/'cases.csv').open('w') as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(table)
    def cell(value):
        return '—' if value is None else f'{value:.2f}' if isinstance(value, float) else html.escape(str(value))
    body = ''.join('<tr>'+''.join('<td>'+cell(v)+'</td>' for v in row)+'</tr>' for row in table)
    document = '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>표본 확대 비교</title>
<style>body{font:16px system-ui;max-width:1400px;margin:40px auto;padding:0 24px;color:#182735;background:#f5f7fa}h1{font-size:28px}p{line-height:1.7}img{width:100%;background:white}table{border-collapse:collapse;background:white;font-size:13px}th,td{padding:10px;border:1px solid #d9dfe8;text-align:right}th{background:#eaf0f6}td:first-child,td:nth-child(2){text-align:left}a{color:#175fc0}</style>
<h1>표본 확대 · 고정 설정 비교</h1>
<p>새 표본을 메타데이터로 선정한 뒤 기존 설정을 그대로 적용했습니다. 아래 표는 20ms 기준 F1이며, 그림은 10/20/70ms를 함께 보여 줍니다. 드럼 연주와 제작자 완성곡은 별도 집계합니다. 같은 곡의 믹스·스템은 독립된 곡으로 세지 않습니다.</p>
<p>GMD는 메트로놈에 맞춘 사람의 전자드럼 연주입니다. 제작자가 오디오/MIDI를 2ms 이내로 정렬했다고 설명하지만, 여기서 원본 클릭 WAV로 독립 검증한 것은 아닙니다. 일정 BPM의 박자 종류를 포함하며 곡 중간 템포·박자 변경에 대한 성능 증거는 아닙니다. 기존 모델의 학습 자료와 겹치는지는 확인되지 않았습니다.</p>
<p>Walker 완성곡은 드럼·클릭 스템과 시작 위치가 달랐습니다. 파형 대조로 스템 기준 +2.875초 대응을 확인했고, 유효 8개 구간의 위치 차이 범위는 0.521ms였습니다. 최초 2샘플 정렬 기준은 통과하지 못했고, 후속 1ms 기준으로 참조를 구성했습니다. 클릭 추출도 1ms 해상도입니다. 클릭이 확인되는 0.125–402.875초, 538개 박만 평가하며 변박·다운비트·원래 녹음에 사용한 클릭 여부는 인증하지 않습니다. 음원은 이동·변형하지 않았고 모델 입력에 클릭을 섞지 않았습니다.</p>
<p><b>Oracle 열은 정답으로 가장 좋은 결과를 고른 진단값입니다.</b> 자동 정확도나 향후 달성 보장이 아닙니다. 후보 선택과 위상 이동 진단은 서로 다른 실험이며 결합 성능으로 읽으면 안 됩니다. 기존 모델·지도·BPM·위치 보정 출력과 추가 후보를 합친 풀의 진단도 포함합니다. 예측 파일은 평가 전에 저장하고 해시를 검증했습니다.</p>
<p><a href="cases.csv">전체 수치 CSV</a> · <a href="comparison.svg">벡터 그림</a> · <a href="summary.json">출처·설정 색인</a></p><img src="comparison.png" alt="세 오차 허용 범위의 방법별 평균 F1 비교"><div style="overflow:auto"><table><thead><tr>'''
    document += ''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div></html>'
    (args.output_dir/'index.html').write_text(document)
    (args.output_dir/'summary.json').write_text(json.dumps({'summaries': summaries,
        'benchmarks': [{'path': str(p), 'sha256': sha256(p)} for p in args.benchmarks],
        'diagnoses': [{'path': str(p), 'sha256': sha256(p)} for p in args.diagnoses],
        'generator_sha256': sha256(__file__), 'default_promoted': False}, indent=2)+'\n')


if __name__ == '__main__':
    main()
