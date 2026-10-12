from __future__ import annotations

import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .common import METHODS,read,guard


def percentage(value):return f'{value*100:.2f}%'


def figure(run,item,metrics):
    reference=read(item['reference_path']);fig,axes=plt.subplots(3,1,figsize=(13,7),sharex=True,sharey=True)
    methods=['B0_RAW','B1_VETO05','F1_FOLD05']
    rates=[]
    for axis,method in zip(axes,methods):
        prediction=read(run/'predictions'/method/'proxy100'/f"{item['id']}.json")
        result=next(r for r in metrics['rows'] if r['id']==item['id'] and r['method']==method and r['policy']=='proxy100')
        for i,state in enumerate(reference['states']):
            axis.plot([state['start'],state['end']],[state['bpm']]*2,color='black',linewidth=2,label='Saved quarter map' if i==0 else None)
        for i,segment in enumerate(prediction['accepted']):
            axis.plot([segment['start'],segment['end']],[segment['bpm']]*2,color='#267fae',linewidth=1.3,label='Output' if i==0 else None)
            rates.append(segment['bpm'])
        for event in result['change_events']:
            if event['classification']=='UNNECESSARY_CHANGE':axis.axvline(event['time'],color='#d13d3d',alpha=.7,linewidth=1)
        axis.set_ylabel('Pulse BPM');axis.grid(alpha=.2)
        axis.set_title(f"{method}: stable {result['stable_valid_fraction']*100:.1f}%, unnecessary {result['unnecessary_changes']}",loc='left',fontsize=10)
    axes[0].legend(loc='upper right');axes[-1].set_xlabel('Original audio seconds; red lines: unnecessary changes')
    fig.suptitle(item['title']);fig.tight_layout();out=run/'figures';out.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(out/f"{item['id']}.{extension}",dpi=150)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();guard(args.run);metrics=read(args.run/'metrics.json');decision=read(args.run/'decision.json')
    lines=['# 복수 리듬 해석 · 불필요 변경 재평가','',
           '승인된 완성곡33곡 중 모델에서 출발한 정답1곡은 별도 진단이다. 주 요약은 나머지32곡이다. 이전21곡에12곡을 추가했지만 실제 변속10곡의 수는 늘지 않았다. Juno는 새108 BPM 정답을 쓴다. 시작 탭은 ±3% 모의 입력이며 실제 사람 탭을 측정하지 않았다.','',
           '허용 해석은 정답의 박·마디 구조에서 미리 만든 규칙이다. 모든 대체 맵을 새로 청취 승인했다는 뜻은 아니다. 박자표 출력이 없는 실험이므로 클릭 흐름만 평가한다.','',
           '| 방법 · 시작 단위 제공 ·32곡 | 순간별 허용 | 구간별 일관된 해석 | 불필요 변경 감점 후 | 불필요 변경 |',
           '|---|---:|---:|---:|---:|']
    for method in METHODS:
        row=next(r for r in metrics['summary'] if r['method']==method and r['policy']=='proxy100' and r['group']=='all33' and r['exclude_model_seeded'])
        lines.append(f"| {method} | {percentage(row['frame_permissive_fraction'])} | {percentage(row['region_coherent_fraction'])} | {percentage(row['stable_valid_fraction'])} | {row['unnecessary_changes']} |")
    lines+=['','| 원래21곡 | 단일 정답 시간 | 구간별 허용 | 감점 후 | 불필요 변경 |','|---|---:|---:|---:|---:|']
    for method in ['B0_RAW','B1_VETO05','F1_FOLD05']:
        row=next(r for r in metrics['summary'] if r['method']==method and r['policy']=='proxy100' and r['group']=='original21' and r['exclude_model_seeded'])
        lines.append(f"| {method} | {percentage(row['canonical_correct_clock_fraction'])} | {percentage(row['region_coherent_fraction'])} | {percentage(row['stable_valid_fraction'])} | {row['unnecessary_changes']} |")
    lines+=['','| 곡 | 기존 감점 후 | 보정 감점 후 | 기존 불필요 변경 | 보정 불필요 변경 |','|---|---:|---:|---:|---:|']
    for item in read(args.run/'evaluation-index.json')['rows']:
        rows={r['method']:r for r in metrics['rows'] if r['id']==item['id'] and r['policy']=='proxy100'}
        before,after=rows['B0_RAW'],rows['F1_FOLD05']
        title=item['title']+(' · 모델 정답 진단' if item['model_seeded_reference_diagnostic_only'] else '')
        lines.append(f"| {title} | {percentage(before['stable_valid_fraction'])} | {percentage(after['stable_valid_fraction'])} | {before['unnecessary_changes']} | {after['unnecessary_changes']} |")
        if item['id'] in ['r005','r008','r010','e003','e010','e011']:figure(args.run,item,metrics)
    lines+=['',f"사전 부품 효과 기준 통과: **{decision['component_direction_criteria_met']}**.",'',
            '순간마다 다른 정답을 고르는 점수는 진단이다. 주 점수는 실제 정답의 구조가 유지되는 구간 전체에서 하나의 해석을 택하고, 원래 출력의 불필요 변경 뒤8초를 감점한다. 변경 횟수 자체도 별도로 공개한다. 감점은 실제 클릭을 끄는 동작이 아니다.','',
            '전체 음악에 한 해석을 유지하는 점수,4초·16초 감점, 더 넓은 해석, 단일 정답 점수도 보존했다. 이 숫자는 새 정책 하의 클릭 지표이며 일반 음악적 타당성·새 곡 일반화·박자표·앱 재생의 인증이 아니다.','',
            '상세 판단은 `interpretation.ko.md`, 수치는 `metrics.json`·`decision.json`·`paired-bootstrap.json`, 입력 보존은 `audit.json`에 있다.']
    (args.run/'report.ko.md').write_text('\n'.join(lines)+'\n')
    print('REPORT AND SIX FIGURES',flush=True)


if __name__=='__main__':main()
