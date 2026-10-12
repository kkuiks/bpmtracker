"""Standalone figures and a concise Korean results artifact."""
from __future__ import annotations

import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .common import METHODS, read, guard


def percent(value):
    return f'{100 * value:.2f}%'


def plot(run, row):
    ref = read(row['reference_path'])
    fig, axes = plt.subplots(3, 1, figsize=(13, 7), sharex=True)
    for axis, (method, label) in zip(axes, [('B0_RAW', 'Original'), ('B1_VETO05', 'Veto and hold'), ('F1_FOLD05', 'Existing folded clock')]):
        pred = read(run / 'predictions' / method / 'proxy100' / f"{row['id']}.json")
        for i, segment in enumerate(ref['segments']):
            axis.plot([segment['start_seconds'], segment['end_seconds']], [segment['quarter_bpm']] * 2,
                      color='black', linewidth=2.5, label='Accepted reference' if i == 0 else None)
        for i, segment in enumerate(pred['accepted']):
            axis.plot([segment['start'], segment['end']], [segment['bpm']] * 2,
                      color='#237bb5', linewidth=1.3, label='Output' if i == 0 else None)
        for event in pred['correction_events']:
            axis.axvspan(event['start'], event['end'], color='#e6a51d', alpha=.15)
        axis.set_ylabel('Quarter BPM')
        axis.set_title(label, loc='left', fontsize=10)
        axis.grid(alpha=.2)
    axes[0].legend(loc='upper right')
    axes[-1].set_xlabel('Original audio time (seconds)')
    fig.suptitle(row['title'])
    fig.tight_layout()
    directory = run / 'figures'
    directory.mkdir(exist_ok=True)
    for extension in ('png', 'svg'):
        fig.savefig(directory / f"{row['id']}.{extension}", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    guard(args.run)
    metrics = read(args.run / 'metrics.json')
    decision = read(args.run / 'decision.json')
    lines = ['# 두 배·절반 오류 보호 결과', '',
             '이전에 분석한 실제 21곡(변속 11·변박 4·고정 대조 6)에 동일한 기존 후보와 원래 변경 시점을 사용했다. 새로운 음원·신경망·정답 후보를 추가하지 않았다. 시작 탭 ±3%는 참조로 만든 모의 입력이며 실제 사람 탭이 아니다.', '',
             '맞는 클릭 시간은 정확한 명목 BPM과 박 위치 70ms 이내를 동시에 요구한다. 배수 오류는 참조의 두 배·절반에서 1% 이내인 시간이다. 아래 값은 곡마다 같은 비중의 평균이다.', '',
             '| 방법 · 시작 단위 제공 | 맞는 클릭 시간 | 맞는 BPM 시간 | 두 배·절반 오류 | 클릭 F1 |',
             '|---|---:|---:|---:|---:|']
    for method in METHODS:
        row = next(r for r in metrics['summary'] if r['method'] == method and r['policy'] == 'proxy100' and r['role'] == 'variable')
        lines.append(f"| {method} | {percent(row['correct_clock_fraction'])} | {percent(row['correct_rate_fraction'])} | {percent(row['alias_error_fraction'])} | {percent(row['click_f1'])} |")
    lines += ['', '| 변속곡 | 원래 | 변경 차단·유지 | 환산 후보 선택 |', '|---|---:|---:|---:|']
    primary = [r for r in metrics['rows'] if r['method'] == 'F1_FOLD05' and r['policy'] == 'proxy100' and r['role'] == 'variable']
    for row in primary:
        def value(method):
            return next(r for r in metrics['rows'] if r['id'] == row['id'] and r['method'] == method and r['policy'] == 'proxy100')
        lines.append(f"| {row['title']} | {percent(value('B0_RAW')['correct_clock_fraction'])} | {percent(value('B1_VETO05')['correct_clock_fraction'])} | {percent(row['correct_clock_fraction'])} |")
    lines += ['', f"성분 효과 기준 통과: **{decision['component_direction_criteria_met']}**. 모든 변속곡 손실 기준 통과: **{decision['all_song_loss_checks_met']}**.",
              '', f"작은 실제 변속 {decision['small_true_change_count']}개의 변경 뒤 16초 명목 BPM 시간 평균 변화: {100 * decision['small_change_post_rate_gain']:+.2f}%p.",
              '', '진짜 두 배·절반 변경은 전체 변속곡 평균에 그대로 포함했다. 원래 출력 경계를 재사용하므로 정확한 변경 시점을 새로 찾은 성과가 아니다. 미지곡 일반화·제품 적용·재생 검증도 아니다.',
              '', '세부 결과: `metrics.json`, `decision.json`, `candidate-rate-availability.json`, `audit.json`. 해석과 권고는 `interpretation.ko.md`에 기록한다.']
    (args.run / 'report.ko.md').write_text('\n'.join(lines) + '\n')
    evaluation = read(args.run / 'evaluation-index.json')['rows']
    for row in evaluation:
        if row['id'] in ('r002', 'r003', 'r005', 'r008', 'r009', 'r010'):
            plot(args.run, row)
    print('REPORT and six PNG/SVG figures', flush=True)


if __name__ == '__main__':
    main()
