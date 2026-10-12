"""Standalone source-unit trajectory plots and a Korean evidence report."""
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .common import CONFIG,CRITERIA,read,guard

def pct(v):return f'{v*100:.2f}'

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    metrics=read(run/'metrics.json');decision=read(run/'decision.json');rows=metrics['rows'];summary=metrics['summary']
    lines=['# 원음 리듬 패턴의 박 단위 판별 결과','',
      '음원 강세의 상대 패턴과 반복 주기가 박 단위 선택에 추가 정보를 주는지를 평가했다. 저·중·고역의 공격음 특징이며 킥·스네어 악기 종류를 인증하거나 악기를 분리한 모델은 아니다. 실제 음악 11곡으로 학습·설정을 선택하고, 다른 10곡으로 검증했다. 24개 작성 음악 대조는 학습하지 않았다. 모두 과거 사용 자료이며 미지곡 성능의 인증은 아니다.','',
      '시작 탭은 참조 초기 BPM의 97/100/103% 모의 입력이다. 음원 특징 이후 이산 단위 관계로 바꾸며 숫자는 버린다. 실제 사람 탭을 측정하지 않았다. 출력은 국소 박 단위 판별이며 정확한 BPM·박 위상·변속 경계·완전한 맵의 성공과 구분한다.','',
      '## 검증곡 결과','',
      '| 방법 | 종류 | 곡 수 | 박 단위 정확도 | 음원 기반 단위 후보 가용성 |','| --- | --- | ---: | ---: | ---: |']
    for s in summary:
        if s['partition']!='validation' or s['policy']!='proxy100':continue
        lines.append(f"| {s['method']} | {s['role']} | {s['songs']} | {pct(s['unit_accuracy_macro'])}% | {pct(s['family_coverage_macro'])}% |")
    lines+=['','## 사전 판정','']
    for d in decision['hypotheses']:
        lines.append(f"- {d['method']}: {'통과' if d['pass'] else '미충족'}. 검증 변속곡 평균 {pct(d['variable_accuracy'])}%, 신경망 비교 {pct(d['baseline_variable_accuracy'])}%, 차이 {pct(d['bootstrap_gain']['macro_gain'])}%p. 곡 단위 부트스트랩 범위 {pct(d['bootstrap_gain']['lower_95'])}~{pct(d['bootstrap_gain']['upper_95'])}%p. 실제 2배 변속 뒤 Juno {pct(d['Juno_true_double_post_accuracy']) if d['Juno_true_double_post_accuracy'] is not None else '채점 불가'}%. 대조군 차이 {pct(d['control_accuracy_delta'])}%p.")
        lines.append(f"  판정 항목: {d['checks']}")
    lines+=['','## 곡별 판별','',
      '| 검증곡 | 신경망 비교 | 원음+초기 패턴 | 원음+신경망+초기 패턴 |','| --- | ---: | ---: | ---: |']
    table={(r['method'],r['policy'],r['id']):r for r in rows}
    validation=sorted(set(r['id'] for r in rows if r['partition']=='validation'))
    figures=run/'figures';figures.mkdir(exist_ok=True)
    for ident in validation:
        base=table[('N1_NEURAL_ANCHOR','proxy100',ident)];audio=table[('A2_AUDIO_ANCHOR','proxy100',ident)];full=table[('A4_AUDIO_NEURAL_ANCHOR','proxy100',ident)]
        lines.append(f"| {base['title']} | {pct(base['unit_accuracy'])}% | {pct(audio['unit_accuracy'])}% | {pct(full['unit_accuracy'])}% |")
        if base['role']!='variable':continue
        ref=read(run/'references'/f'{ident}.json');fig,ax=plt.subplots(figsize=(13,4))
        for j,s in enumerate(ref['segments']):ax.plot([s['start_seconds'],s['end_seconds']],[s['quarter_bpm']]*2,color='black',linewidth=2,label='Reference rate' if j==0 else None)
        for method,color,label in [('N1_NEURAL_ANCHOR','#cc7d28','Neural unit estimate'),('A4_AUDIO_NEURAL_ANCHOR','#2470b5','Audio + neural unit estimate')]:
            pred=read(run/'predictions'/method/'proxy100'/f'{ident}.json')['rows']
            t=np.array([r['time'] for r in pred]);v=np.array([r['unit_rate_estimate'] if r['unit_rate_estimate'] is not None else np.nan for r in pred])
            use=np.zeros(len(t),bool)
            for a,b in ref['support']:use|=(t>=a)&(t<b)
            ax.plot(t[use],v[use],color=color,linewidth=1,label=label)
        ax.set_title(f'{ident}: unit-family probe, not a fitted tempo map');ax.set_xlabel('Original audio time (s)');ax.set_ylabel('Source rate x chosen unit factor');ax.grid(alpha=.2);ax.legend()
        fig.tight_layout();fig.savefig(figures/f'{ident}.png',dpi=150);fig.savefig(figures/f'{ident}.svg');plt.close(fig)
    lines+=['','## 한계','',
      '박 단위 정확도는 국소 음원 후보와 선택한 단위의 속도가 해당 시각 참조 BPM의 5% 이내에 들어가는 관계인지를 기준으로 한다. 미세 BPM·위상·변경 시점의 정확도를 대신하지 않는다. 전체 검증 지지 범위의 중심점을 분모로 유지하며 약한 관측·표현 불가능한 단위도 실패에 포함한다. 조건부 정확도와 후보 가용성은 metrics.json에 따로 보존한다.','',
      '같은 곡의 창들은 독립 표본이 아니다. 곡별 평균과 곡 단위 재표집을 사용했지만 검증 변속곡은 다섯 개뿐이다. 장르 다양성·미지곡 일반화·자동 맵 전체의 성능은 추가로 입증하지 않았다. 정규화 비용·스케일은 개발곡에서만 선택하며 검증 곡을 학습하지 않았다.','',
      '후보와 원음 패턴은 음원에서 먼저 준비했다. 원본 음원·참조·과거 동결 구현·앱 분석기는 유지했다. 새 신경망 추론·악기 분리·표본 수집·재생 시험·소스 Git 발행은 하지 않았다. 신경망 비교 모델도 이번에 개발곡으로 학습한 모델이며 과거 M3/R2와 같은 모델이 아니다.','',
      '원자료: metrics.json, decision.json, learning-split.json, development-label-receipt.json, model-freeze.json, completion-review.json. 모든 후보 특징·학습 계수·검증 예측·참조와 그림을 보존한다.']
    (run/'report.ko.md').write_text('\n'.join(lines)+'\n');print('REPORTED',flush=True)

if __name__=='__main__':main()
