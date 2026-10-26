"""Standalone plots and Korean result tables from frozen metrics."""
import argparse
import os
from pathlib import Path
import tempfile

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='bpmtracker-init-mpl-'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from experiments.bpm_continuity_v1.evaluate import arrays
from .common import METHODS, read, guard

LABELS = {'I0_LOCAL6': 'Current local 6 s', 'I1_WHOLE_RATE_LOCAL6': 'Whole-input rate + local phase',
          'I2_LOCAL12': 'Initial local 12 s', 'I3_LOCAL24': 'Initial local 24 s'}
COLORS = {'correct_clock_70ms': '#2c8f65', 'wrong_rate': '#d65b4b', 'wrong_phase_only': '#a46eae',
          'unknown': '#b5bec5', 'ambiguous': '#e4b954'}


def percent(value):
    return f'{value * 100:.2f}%'


def make_figures(run, metrics):
    directory = run / 'figures'; directory.mkdir(exist_ok=False)
    fig, ax = plt.subplots(figsize=(10, 3.8)); left = np.zeros(len(METHODS))
    for key, color in COLORS.items():
        values = np.array([metrics['aggregates'][m + '/proxy_unit_zero']['macro'][key] * 100 for m in METHODS])
        ax.barh(np.arange(len(METHODS)), values, left=left, color=color, label=key.replace('_', ' '))
        left += values
    ax.set_yticks(np.arange(len(METHODS)), [LABELS[m] for m in METHODS]); ax.invert_yaxis()
    ax.set_xlim(0, 100); ax.set_xlabel('Macro percentage of approved support (8 fixed recordings)')
    ax.legend(loc='upper center', bbox_to_anchor=(.5, -.2), ncol=3, fontsize=8)
    ax.set_title('Initialization only; identical downstream C_HOLD; offline diagnostic')
    fig.tight_layout(); fig.savefig(directory / 'summary.png', dpi=160, bbox_inches='tight')
    fig.savefig(directory / 'summary.svg', bbox_inches='tight'); plt.close(fig)
    for row in read(run / 'evaluation-manifest.json')['samples']:
        ident = row['id']; ref = read(row['reference_path'])
        fig, axes = plt.subplots(3, 1, figsize=(12, 7.2), sharex=True,
                                 gridspec_kw={'height_ratios': [1.5, 1.5, 1.]})
        for k, method in enumerate(METHODS):
            pred = read(run / 'predictions' / method / 'proxy_unit_zero' / (ident + '.json'))
            boot = read(run / 'bootstrap' / method / 'proxy_unit_zero' / (ident + '.json'))
            t, support, truth, rate, error, labels = arrays(pred, ref, row['duration_seconds'])
            for category, color in COLORS.items():
                active = support & labels[category]
                edges = np.diff(np.r_[False, active, False].astype(int))
                for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                    axes[0].broken_barh([(max(0., t[a] - .01), (b - a) * .02)], (k - .32, .64), color=color)
            for span in pred['accepted']:
                axes[1].plot([span['start'], span['end']], [span['bpm'], span['bpm']], linewidth=1.1,
                             color=plt.cm.tab10(k), label=LABELS[method] if span is pred['accepted'][0] else None)
            if boot['seed']:
                axes[0].plot(boot['seed']['time'], k, '|', color='black', markersize=14)
            selected = np.isfinite(rate) & support
            plotted = np.where(selected, np.minimum(error * 1000, 200), np.nan)
            axes[2].plot(t[::10], plotted[::10], linewidth=.75, alpha=.85, color=plt.cm.tab10(k), label=LABELS[method])
        axes[0].set_yticks(range(4), [LABELS[m] for m in METHODS]); axes[0].invert_yaxis()
        axes[0].set_title(row['title'] + ' | unchanged approved support; proxy unit input')
        axes[1].axhline(ref['initial_bpm'], color='black', linestyle='--', linewidth=1., label='Accepted nominal BPM')
        axes[1].set_ylabel('Emitted BPM'); axes[1].legend(fontsize=7, ncol=3)
        axes[2].axhline(70, color='black', linestyle=':', linewidth=.8)
        axes[2].set_ylim(0, 205); axes[2].set_ylabel('Grid error (ms)\nclipped at 200'); axes[2].set_xlabel('Audio-relative seconds')
        axes[2].set_xlim(0, row['duration_seconds'])
        axes[0].legend(handles=[Patch(color=c, label=k.replace('_', ' ')) for k, c in COLORS.items()],
                       loc='lower center', bbox_to_anchor=(.5, 1.03), ncol=5, fontsize=7)
        fig.tight_layout(); fig.savefig(directory / (ident + '.png'), dpi=160)
        fig.savefig(directory / (ident + '.svg')); plt.close(fig)


def report(run):
    guard(run); metrics = read(run / 'metrics.json'); analysis = read(run / 'analysis.json')
    make_figures(run, metrics)
    lines = ['시작 시계 선택만 바꾼 네 방법을 고정 BPM 8곡에서 비교했습니다. 이후 출력은 모두 기존 6초 C_HOLD입니다.',
             '', '±5% 입력은 세 방법별로 같은 단위 power를 선택한 정답 기반 진단입니다. 실제 사람의 탭을 수집하지 않았고, 8곡을 24곡으로 세지 않았습니다.',
             '', '## 전체 결과', '',
             '| 시작 방법 | 맞는 시계 @70ms | 잘못된 BPM | phase만 틀림 | UNKNOWN | 실제 quarter F1@70ms | 정확한 seed | NO_SEED | 사전 기준 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for method in METHODS:
        a = metrics['aggregates'][method + '/proxy_unit_zero']['macro']; d = metrics['decisions'][method]
        lines.append(f"| {LABELS[method]} | {percent(a['correct_clock_70ms'])} | {percent(a['wrong_rate'])} | {percent(a['wrong_phase_only'])} | {percent(a['unknown'])} | {percent(a['quarter_f1_70ms'])} | {d['exact_rate_seeds']}/8 | {d['no_seed_inputs']}/8 | {d['status']} |")
    lines += ['', '평균은 곡별 동일 비중의 macro입니다. 승인 참조 구간 전체가 분모이며 대기·NO_SEED·출력 보류를 제외하지 않았습니다. 시간 가중 micro는 metrics.json에 별도로 있습니다.',
              '', '사전 연구 기준은 맞는 시계 ≥80%, 실제 quarter F1이 기존 stateless 모의 입력보다 낮지 않음, 기존 6초 hold 대비 모든 곡의 맞는 시계 손실 ≤5%p입니다. 제품 합격 기준은 아닙니다.',
              '', f"기존 stateless의 실제 quarter F1 기준은 {percent(metrics['quarter_F1_threshold'])}입니다.",
              '', '## 곡별 결과', '', '| 곡 | 기존 6초 | 전체 곡 BPM | 시작 12초 | 시작 24초 |', '|---|---:|---:|---:|---:|']
    for row in analysis['per_song']:
        lines.append('| ' + row['title'] + ' | ' + ' | '.join(percent(row['methods'][m]['fractions']['correct_clock_70ms']) for m in METHODS) + ' |')
    lines += ['', '## 처음 고른 BPM과 대기', '', '| 곡 / 참조 BPM | 기존 6초 | 전체 곡 BPM | 시작 12초 | 시작 24초 |', '|---|---|---|---|---|']
    for row in analysis['per_song']:
        values = []
        for method in METHODS:
            seed = row['methods'][method]['seed']
            values.append(f"{seed['bpm']:.6g} BPM / {seed['time']:.2f}s" if seed['time'] is not None else 'NO_SEED')
        lines.append(f"| {row['title']} / {row['nominal_bpm']:g} | " + ' | '.join(values) + ' |')
    lines += ['', '위 대기는 오프라인 출력 타임라인에서 seed를 확정한 시점입니다. 전체 곡 BPM 조건은 이미 곡 끝까지 보았으므로 온라인 대기 시간으로 읽을 수 없습니다.',
              '', '| 방법 | seed 시각 중앙값 | 승인 구간 중 초기 대기 평균 | @20ms 맞는 시계 | @30ms 맞는 시계 |', '|---|---:|---:|---:|---:|']
    for method in METHODS:
        a = metrics['aggregates'][method + '/proxy_unit_zero']['macro']; d = metrics['decisions'][method]
        lines.append(f"| {LABELS[method]} | {d['median_seed_time_seconds']:.2f}s ({d['passing_seed_time_denominator']}/8 seeded) | {percent(d['mean_waiting_support_fraction'])} | {percent(a['correct_clock_20ms'])} | {percent(a['correct_clock_30ms'])} |")
    lines += ['', 'NO_SEED는 위 seed 시각 중앙값에 들어가지 않지만 전체 점수에서는 승인 구간 전체가 출력 실패로 남습니다. 상세 대기·seed 이후 UNKNOWN·BPM 오류 시간은 analysis.json에 있습니다.',
              '', '## 선택의 확신과 가까운 BPM', '',
              '기존 margin은 다른 동등성 그룹의 대표와 비교합니다. 같은 그룹의 가까운 BPM은 경쟁자로 빠질 수 있으므로 margin=1은 정확한 소수 BPM의 확률 100%를 뜻하지 않습니다. seed-diagnostics는 같은 그룹 안의 다른 BPM과 원래 점수 차이도 저장했습니다.',
              '', '전체 곡 방법도 준비된 family의 최상위 BPM을 한 번 선택할 뿐입니다. 그 family의 소수 BPM 경쟁 점수 차이를 저장했으며, 이번 결과를 보고 반올림이나 곡별 예외를 추가하지 않았습니다.',
              '', '## 실험 범위와 해석의 한계', '',
              '전체 곡 조건은 기존 고정 추정기가 준비한 BPM만 가져오고 phase와 박자표는 가져오지 않았습니다. 선택 단위는 기존 국소 audio base에 맞춰 변환했습니다. 선택된 BPM이 공통 후보군에 없으면 NO_SEED로 남기는 규칙입니다.',
              '', '12/24초 조건은 trailing 시작 근거 창만 바꿨고 확정 시점의 출력 가능성은 원래 6초 규칙으로 확인했습니다. 최소 12/24초를 기다리며 시작 deadline 30초를 연장하지 않았습니다. 한 조건에서 확정하지 못한 곡에 다른 방법을 대신 쓰지 않았습니다.',
              '', '모든 조건은 보관된 오프라인 신경망 관측과 전체 곡 기반 후보/phase를 사용합니다. 짧은 창 조건의 결과도 실시간 분석기의 검증이 아닙니다. 정확한 시작 BPM을 제공한 기존 진단 비교는 새 소스 방법의 엄밀한 상한이 아니며 별도 참고로 남겼습니다.',
              '', '8곡은 이미 알고 있던 개발·실패 자료입니다. 독립 미지곡 일반화, 제작자 시계의 millisecond 인증, 실제 사람의 탭, 변속 검출을 검증하지 않았습니다. 원본과 참조, 기존 동결 결과와 앱 추정기를 변경하지 않았습니다.',
              '', '## 실행 확인', '']
    audit = read(run / 'source-isolation-audit.json'); controls = read(run / 'controls.json')
    lines += [f"논리 대조 {len(controls['checks'])}개 PASS. 참조·원래 입력값을 바꾼 worker1과 기본 worker2의 예측/trace {len(audit['prediction_trace_comparisons'])}조건이 byte 일치했습니다. 기존 6초 baseline {len(audit['baseline_reproduction'])}조건도 byte 재현했으며 금지 참조 읽기는 0회입니다.",
              '', '후속 방향에 대한 상세 해석은 [결과 검토](interpretation.ko.md)에 있습니다.',
              '', '## 그림', '', '- [전체 분해](figures/summary.png)']
    for row in analysis['per_song']:
        lines.append(f"- [{row['title']}](figures/{row['id']}.png)")
    lines += ['', '## 재현', '', '새 run을 prepare로 만든 뒤 출력된 경로를 사용합니다. 완료된 run에 덮어쓰지 않습니다.', '', '```sh',
              '.venv-metronome-v1/bin/python -m experiments.bpm_initialization_v1.prepare',
              'RUN="<new prepare output>"']
    for module, options in [('controls', ''), ('run', '--stage build --workers 2'),
                            ('run', '--stage freeze'), ('run', '--stage predict --workers 2'),
                            ('audit', ''), ('evaluate', ''), ('report', '')]:
        lines.append(f'.venv-metronome-v1/bin/python -m experiments.bpm_initialization_v1.{module} --run "$RUN" {options}'.rstrip())
    lines += ['```', '', '예측·metrics·protocol·실행 코드는 같은 run에 보관했습니다. 원본 음원과 모델 가중치는 ZIP에 포함하지 않습니다.']
    (run / 'report.ko.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('REPORT', run / 'report.ko.md', flush=True)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(); report(args.run.resolve())


if __name__ == '__main__':
    main()
