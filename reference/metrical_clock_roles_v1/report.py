"""Readable Korean research evidence and standalone trajectory figures."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .common import FOCUS,read,write,guard

def pct(v):return f'{v*100:.2f}'

def curve(ax,segments,label,color,ref=False):
    for i,e in enumerate(segments):
        a=e['start_seconds'] if ref else e['start'];b=e['end_seconds'] if ref else e['end']
        bpm=e['quarter_bpm'] if ref else e['bpm']
        ax.plot([a,b],[bpm,bpm],color=color,linewidth=1.8,label=label if i==0 else None)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    stage='broad' if (run/'broad-metrics.json').exists() else 'focus'
    metrics=read(run/f'{stage}-metrics.json');rows=metrics['rows'];summary=metrics['summary']
    primary=[r for r in rows if r['method']=='R2_ROLES_BARS' and r['policy']=='proxy100']
    focus=read(run/'focus-decision.json');lines=['# 박 단위·마디 역할 실험 결과','',
      '시작 탭 ±3%는 참조 초기 BPM으로 만든 모의 입력이다. 사람 탭을 측정하지 않았다. 숫자는 이산 단위 관계로 바꾼 뒤 버리며, 시작 8초의 음원 기반 구간에만 단위를 적용한다. 복합 박의 3:2 관계를 포함하는 연구용 인코더이며 앱의 고정 분석기는 변경하지 않았다.','',
      '물리 BPM·위상 후보, 신경망이 관측한 박 간격, 실제 마디 길이 후보, 신경망이 마디를 건너뛰거나 세분해 관측한 역할을 구분한다. 마디 첫 박은 불완전하므로 보조 근거로 사용한다. 시작 마디 길이는 4분음표 4개를 선호하는 사전 비용을 주며 다른 길이와 변경도 허용한다. 이 사전 비용은 관측 수준 대조 자료에서 정했으며 음악적 박자표의 확정을 의미하지 않는다.','',
      '## 첫 세 곡','',f"사전에 동결한 확장 기준: {'충족' if focus['proceed_to_broad'] else '미충족'}. 결과를 본 뒤 최선의 대조 방법으로 기본 방법을 바꾸지 않았다.",'',
      '| 곡 | 올바른 시계 기존 → 새 방법 | 박 F1 기존 → 새 방법 | 개선 판정 |','| --- | ---: | ---: | --- |']
    old={(r['id'],r['policy']):r for r in rows if r['method']=='BASELINE_M3'}
    for f in focus['rows']:
        r=next(r for r in primary if r['id']==f['id']);b=old[(r['id'],'proxy100')]
        lines.append(f"| {r['title']} | {pct(b['correct_clock_fraction'])} → {pct(r['correct_clock_fraction'])}% | {pct(b['quarter_f1_70']['f1'])} → {pct(r['quarter_f1_70']['f1'])}% | {'개선' if f['improved'] else '기준 미달'} |")
    lines+=['','## 방법별 비교','',
            '각 항목은 녹음별 평균이다. 실제 음악, 작성한 음악 대조 자료 및 관측 수준 대조 자료는 서로 다른 집계다.','',
            '| 방법 | 조건 | 변속곡 수 | 올바른 시계 | 반속/배속 오류 | 박 F1 | 올바른 속도 쌍 경계 ±4초 | 불필요한 변경 |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in summary:
        if s['role']!='variable' or s['policy'] not in ['none','proxy100']:continue
        lines.append(f"| {s['method']} | {s['policy']} | {s['inputs']} | {pct(s['correct_clock_macro'])}% | {pct(s['octave_error_macro'])}% | {pct(s['quarter_f1_macro'])}% | {s['boundaries_within']['4.0']}/{s['all_transitions']} | {s['unwanted_changes_4s']} |")
    if stage=='broad':
        decision=read(run/'broad-decision.json')
        lines+=['','## 전체 방향성 기준','',f"동결한 방향성 기준: {'충족' if decision['direction_criteria_met'] else '미충족'}. 올바른 시계 변화 {pct(decision['correct_clock_gain'])}%p, 반속·배속 오류 감소 {pct(decision['octave_error_reduction'])}%p, 실제 대조군 오류 변화 {pct(decision['control_wrong_increase'])}%p. 85% 이상 회복한 변속곡 {len(decision['variable_songs_correct_85'])}/11.",'',
                '| 변속곡 | 올바른 시계 | 반속/배속 오류 | 박 F1 | 경계 ±4초 |','| --- | ---: | ---: | ---: | ---: |']
        for r in primary:
            if r['role']=='variable':lines.append(f"| {r['title']} | {pct(r['correct_clock_fraction'])}% | {pct(r['octave_error_fraction'])}% | {pct(r['quarter_f1_70']['f1'])}% | {r['boundaries_within']['4.0']}/{r['all_transition_count']} |")
    lines+=['','## 근거의 한계','',
       '모든 곡은 이미 사용한 자료다. 반속/배속 회복과 정확한 경계 회복은 별개다. 실제 변속과 신경망 박 역할·마디 역할의 동시 변경이 완전히 같은 관측을 만드는 작성 대조 쌍이 있다. 두 정답을 같은 관측만으로 모두 식별할 수 없으며, 이런 경우 사전 가정이 해석을 결정한다. 작성 대조는 알려진 시계 후보를 넣은 구성요소 실험이며 독립 음악 성능이 아니다.','',
       '빔 검색은 근사이며 일부 박·마디 역할 후보를 제한한다. 시작 4박 선호와 관측 역할 비용의 영향을 사전에 정한 대조 방법으로 평가했다. 마디 길이 일치가 완전한 박자표·마디 위치 성공을 의미하지 않는다. 원음·참조·동결된 과거 구현을 바꾸지 않았으며 앱 통합·재생·내보내기 검증은 수행하지 않았다.','',
       '박 위치 F1은 70ms에서 계산하며 20/30ms도 원자료에 보존한다. 올바른 시계는 명목 BPM과 박 위상을 함께 평가한다. 경계는 속도 쌍의 대응, 시간 오차, 기존 8박 전후의 엄격 기준을 따로 보존한다. 참조는 사용자가 승인한 맵이며 제작자 시계의 독립적인 밀리초 정밀도를 인증하지 않는다.','',
       '## 그림과 원자료','']
    figures=run/'figures';figures.mkdir(exist_ok=True)
    for r in primary:
        if r['role']!='variable':continue
        ident=r['id'];ref=read(run/'references'/f'{ident}.json');pred=read(run/'predictions/R2_ROLES_BARS/proxy100'/f'{ident}.json');baseline=read(run/'baseline/proxy100'/f'{ident}.json')
        fig,axes=plt.subplots(2,1,figsize=(14,6),sharex=True,gridspec_kw={'height_ratios':[3,1]})
        curve(axes[0],ref['segments'],'Reference','#333333',True);curve(axes[0],baseline['accepted'],'Previous M3','#cf7a30');curve(axes[0],pred['accepted'],'Joint roles','#246cc0')
        for tr in ref['transitions']:axes[0].axvline(tr['time'],color='#555555',alpha=.22)
        axes[0].set_ylabel('Quarter BPM');axes[0].legend(loc='upper right');axes[0].grid(alpha=.2)
        axes[0].set_title(f"{ident}: source clock / neural roles, initial unit assistance")
        for c in pred['latent_context']:
            axes[1].plot([c['start'],c['end']],[c['role_period_quarters']]*2,color='#246cc0')
        axes[1].set_ylabel('NN pulse / quarter');axes[1].set_xlabel('Original audio time (s)');axes[1].grid(alpha=.2)
        fig.tight_layout();fig.savefig(figures/f'{ident}.png',dpi=150);fig.savefig(figures/f'{ident}.svg');plt.close(fig)
        lines.append(f"- {r['title']}: [그림](figures/{ident}.png)")
    lines+=['','`focus-metrics.json`, `broad-metrics.json`(확장한 경우), `sensor-observability.json`, `observation-controls.json`, `ambiguous-pair/metrics.json`, `completion-review.json`, `freeze.json`에 수치와 실행 근거를 보존한다.']
    (run/'report.ko.md').write_text('\n'.join(lines)+'\n')
    print('REPORTED',stage,flush=True)

if __name__=='__main__':main()
