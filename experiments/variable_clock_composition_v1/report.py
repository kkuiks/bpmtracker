"""Standalone research figures and a compact Korean report."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .common import read,write,guard
from .evaluate import arrays


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    metrics=read(run/'metrics.json');rows=read(run/'evaluation-index.json')['rows'];figdir=run/'figures';figdir.mkdir(exist_ok=True)
    primary=[r for r in metrics['rows'] if r['tree']=='predictions' and r['method']=='M3_REGION_HOLD' and r['policy']=='none']
    m3={r['id']:r for r in primary}
    for row in rows:
        if row['role'] not in ['variable','meter_control']:continue
        ident=row['id'];ref=read(run/'references'/f'{ident}.json')
        fig,axes=plt.subplots(3,1,figsize=(14,7),sharex=True,gridspec_kw={'height_ratios':[2,2,1]},layout='constrained')
        methods=[('M3_REGION_HOLD','none','Region hold'),('M3_REGION_HOLD','proxy100','Initial unit diagnostic')]
        for ax,(method,policy,label) in zip(axes[:2],methods):
            pred=read(run/'predictions'/method/policy/f'{ident}.json')
            for s in ref['segments']:ax.plot([s['start_seconds'],s['end_seconds']],[s['quarter_bpm']]*2,color='black',lw=2)
            for e in pred['accepted']:ax.plot([e['start'],e['end']],[e['bpm']]*2,color='#2769b0',lw=1.4)
            for tr in ref['transitions']:ax.axvline(tr['time'],color='gray',ls=':',alpha=.6)
            ax.set_ylabel(label+'\nquarter BPM');ax.grid(alpha=.15)
        pred=read(run/'predictions/M3_REGION_HOLD/none'/f'{ident}.json')
        time,support,truth,rate,error,correct,selected=arrays(pred,ref,row['duration_seconds'])
        labels=np.full(len(time),np.nan);labels[support&~selected]=0;labels[support&selected&~(correct&(error<=.07))]=1;labels[support&correct&(error<=.07)]=2
        axes[2].scatter(time,labels,c=np.where(np.nan_to_num(labels)==2,'#21965b',np.where(np.nan_to_num(labels)==1,'#c84c45','#909090')),s=1,rasterized=True)
        axes[2].set_yticks([0,1,2],['No clock','Wrong','Correct']);axes[2].set_xlabel('Original audio seconds')
        fig.suptitle(row['title']+' — quarter clocks, reference in black',fontsize=11)
        fig.savefig(figdir/f'{ident}.png',dpi=150);fig.savefig(figdir/f'{ident}.svg');plt.close(fig)
    summary=[r for r in metrics['summary'] if r['tree']=='predictions' and r['role']=='variable' and r['policy'] in ['none','proxy100']]
    lines=['# 구간 시계 조합의 유효성 검증', '',
           '현재 승인된 실제 변속곡 11곡, 박자 변화 대조 4곡, 고정 대조 6곡, 기존 구성 음악 24개를 평가했다. 구성 음악은 4개 부모의 변형이며 실제 24곡으로 세지 않는다.', '',
           '주 조건은 음원 관측만 사용한다. 초기 단위 조건은 참조 BPM의 ±5%를 이산 octave 정보로 바꾼 진단이며 실제 사람 탭 평가가 아니다. 정답 BPM·위상 사전은 변경 시점을 제공하지 않는 별도 진단이다.', '',
           '| 방법 | 초기 정보 | 올바른 시계 | 잘못된 시계 | 미복원 | quarter F1@70ms | 성공 변속 | 거짓 변속 |',
           '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"| {r['method']} | {r['policy']} | {r['correct_clock_macro']:.2%} | {r['wrong_clock_macro']:.2%} | {r['unknown_macro']:.2%} | {r['quarter_f1_macro']:.2%} | {r['successful_transitions']}/{r['eligible_transitions']} | {r['false_tempo_changes']} |")
    lines+=['','| 주 조건의 곡 | 올바른 시계 | 잘못된 시계 | quarter F1 | 성공 변속 | 긴 구간 복원 |',
            '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        if row['role']!='variable':continue
        r=m3[row['id']]
        lines.append(f"| {row['title']} | {r['correct_clock_fraction']:.2%} | {r['wrong_clock_fraction']:.2%} | {r['quarter_f1_70']['f1']:.2%} | {r['successful_transitions']}/{r['eligible_transitions']} | {r['long_regions_recovered']}/{r['long_reference_regions']} |")
    lines += ['', '사전 게이트는 decision-gate.json, 모든 곡·조건·변속은 metrics.json/metrics.csv, 후보 생존과 위상·유효 구간은 candidate-availability.json에 남겼다.', '',
        '판단과 실패 원인에 대한 충분한 해석은 interpretation.ko.md를 함께 읽는다. 임계값을 결과에 맞춰 재조정하지 않았다. 70ms는 연구 진단용이며 제작자 클릭의 독립적인 밀리초 인증이나 제품 합격 기준이 아니다.', '',
        '곡 전체를 미래 정보까지 사용하는 오프라인 실험이다. 자동 박자표 추론·점진적 템포 변화·앱 통합·새 가중치 학습·새 표본 수집은 수행하지 않았다.']
    (run/'report.ko.md').write_text('\n'.join(lines)+'\n')
    print('REPORT',len(list(figdir.glob('*.png'))),'figures',flush=True)


if __name__=='__main__':main()
