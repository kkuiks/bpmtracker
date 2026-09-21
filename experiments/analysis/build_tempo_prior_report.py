"""Summarize every frozen prior setting, including regressions and phase errors."""
import argparse
import csv
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from run_one_song_completion import render_quarter_click


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports',type=Path,nargs='+',required=True)
    parser.add_argument('--light-completion',type=Path,required=True)
    parser.add_argument('--what-beauty-reference',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    reports=sorted([(json.loads(p.read_text()),p) for p in args.reports],key=lambda item:item[0]['configuration']['prior']['strength'])
    identities=[[(r['id'],r['reference_sha256']) for r in report['rows']] for report,_ in reports]
    if any(v!=identities[0] for v in identities):raise ValueError('comparison case sets or references differ')
    args.output_dir.mkdir(parents=True);output=args.output_dir
    rows=[];phase={}
    beauty=json.loads(args.what_beauty_reference.read_text());truth=np.asarray(beauty['beats_seconds'])
    truth=truth[(truth>=110)&(truth<=min(227.746,beauty['evaluation_support_seconds'][1]))]
    for report,path in reports:
        strength=report['configuration']['prior']['strength']
        for row in report['rows']:
            for method,value in row['methods'].items():
                m=value['metrics'];rows.append({'strength':strength,'id':row['id'],'scope':row['scope'],
                    'cohort':row['cohort'],'model':row['model'],'method':method,
                    'f1_20ms':m['event_20ms']['f1'],'f1_70ms':m['event_70ms']['f1'],
                    'f1_30ms':None,'status':value['status']})
            if row['id']=='forestry_what-beauty__beat_this__full':
                phase[str(strength)]={}
                for method,value in row['methods'].items():
                    predicted=np.asarray(value['prediction']);predicted=predicted[(predicted>=110)&(predicted<=227.746)]
                    phase[str(strength)][method]={'event_20ms':nearest_event_diagnostics(truth,predicted,.02),
                        'event_30ms':nearest_event_diagnostics(truth,predicted,.03),
                        'event_70ms':nearest_event_diagnostics(truth,predicted,.07)}
    with (output/'cases.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # Strongest predeclared setting, explicitly not a label-picked default.
    strong,strong_path=reports[-1]
    completed=next(row for row in strong['rows'] if row['scope']=='conditional_completion')
    candidate=completed['methods']['soft_prior']['clock']
    info=json.loads((args.light_completion/'report.json').read_text())
    if sha256(args.light_completion/'music.wav')!=info['source_sha256']:raise ValueError('listening source hash mismatch')
    artifact={**candidate,'source_audio_sha256':info['source_sha256'],'reference_used_for_prediction':False,
        'tempo_prior_strength':strong['configuration']['prior']['strength'],'accepted':False,
        'status':'stronger_sensitivity_candidate_not_promoted','meter':None,
        'bridge_certified':False,'report_path':str(strong_path),'report_sha256':sha256(strong_path)}
    (output/'light-strong-candidate.json').write_text(json.dumps(artifact,indent=2)+'\n')
    render=render_quarter_click(output/'light-strong-click.wav',candidate['beats_seconds'],info['source_sample_rate'],info['source_frames'])
    # Diagnostic plots compare unchanged predictions, never re-align them.
    reference=json.loads((args.light_completion/'reference-map.json').read_text())
    light_truth=np.asarray([v for v in reference['beats_seconds'] if v<=314.527])
    fig,(ax1,ax2)=plt.subplots(2,1,figsize=(10.8,6.7),layout='constrained')
    for report,_ in reports:
        row=next(r for r in report['rows'] if r['scope']=='conditional_completion')
        t=np.asarray([v for v in row['methods']['soft_prior']['prediction'] if v<=314.527])
        if len(t)!=len(light_truth) or max(abs(t-light_truth))>.07:raise ValueError('plot requires verified one-to-one 70 ms pairs')
        ax1.plot(light_truth,(t-light_truth)*1000,label='Prior strength '+str(report['configuration']['prior']['strength']))
    old=np.asarray(completed['methods']['existing']['prediction']);old=old[old<=314.527]
    ax1.plot(light_truth,(old-light_truth)*1000,color='#555',linestyle='--',label='Existing completion')
    ax1.set_title('Light Has Come: stronger prior removes long-section rate drift')
    beauty_row=next(r for r in strong['rows'] if r['id']=='forestry_what-beauty__beat_this__full')
    for method,label in [('existing','Existing clock'),('soft_prior','Strong prior: correct 59 BPM, delayed phase')]:
        p=np.asarray(beauty_row['methods'][method]['prediction']);p=p[(p>=110)&(p<=227.746)]
        if len(p)!=len(truth) or max(abs(p-truth))>.07:raise ValueError('phase plot requires verified one-to-one pairs')
        ax2.plot(truth,(p-truth)*1000,label=label)
    ax2.set_title('What Beauty, 110-227.746 s: smaller drift still misses the 20 ms threshold')
    for ax in (ax1,ax2):
        ax.axhspan(-20,20,color='#dceddf',alpha=.6)
        ax.axhline(20,color='#8a4038',linestyle='--',linewidth=.8);ax.axhline(-20,color='#8a4038',linestyle='--',linewidth=.8)
        ax.axhline(0,color='#666',linewidth=.5);ax.set_xlabel('Source time (seconds)');ax.set_ylabel('Click error (ms)')
        ax.grid(alpha=.15);ax.legend(fontsize=8)
    ax2.set_ylim(10,30)
    fig.savefig(output/'timing-diagnostics.png',dpi=160);plt.close(fig)
    summary={'schema_version':1,'reports':[{'path':str(p),'sha256':sha256(p),'strength':r['configuration']['prior']['strength']} for r,p in reports],
        'case_count_per_setting':len(strong['rows']),'distinct_songs':len({r['track_id'] for r in strong['rows']}),
        'comparisons':{str(r['configuration']['prior']['strength']):r['summary'] for r,_ in reports},
        'what_beauty_phase_diagnostic':{'source_seconds':[110,227.746],'results':phase},
        'light_click_export':render,'default_promoted':False,'human_listening_performed':False,
        'warning':'Sensitivity runs after observing the first result; development evidence, not a held-out evaluation. Strongest setting is not selected per song.'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    title='BPM 선호도 비교 · 개발 표본'
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>'+title+'</title>',
        '<style>body{font:16px/1.6 system-ui;max-width:1250px;margin:30px auto;padding:0 20px;color:#203247}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d2dae2;padding:7px;text-align:left}th{background:#edf3f7}img{max-width:100%}details{margin:20px 0}.warn{background:#fff2dc;padding:15px}</style>',
        '<h1>'+title+'</h1><p>23곡 · 전곡 모델 경로 32개, 부분 구간 24개, Light Has Come 연결 지도 1개를 각 설정에서 비교했습니다. 모델·부분 구간을 별도 곡으로 세지 않습니다.</p>',
        '<p class="warn">정수·0.5 BPM을 우선하되 연속값도 허용합니다. 새 변경점을 추가하지 않고 위치와 기존 경계를 함께 맞춥니다. 모든 예측을 저장한 뒤 정답을 읽었습니다. 설정 강도 비교는 첫 결과를 본 후 수행한 개발 실험입니다. 전역 기본값으로 승격하지 않았습니다.</p>',
        '<p><a href="cases.csv">전체 사례 CSV</a> · <a href="summary.json">요약 JSON</a> · <a href="light-strong-candidate.json">Light 강한 선호도 후보</a> · <a href="light-strong-click.wav">후보 클릭 WAV</a></p>',
        '<img src="timing-diagnostics.png" alt="Light의 드리프트 개선과 What Beauty의 21ms 위상 오차">']
    for report,_ in reports:
        strength=report['configuration']['prior']['strength'];parts.append('<h2>선호도 강도 '+str(strength)+'</h2>')
        parts.append('<table><tr><th>평가 범위 / 자료 / 모델</th><th>사례 수</th><th>기존 20ms</th><th>선호도 없이 재계산</th><th>선호도 적용 20ms</th><th>적용 70ms</th></tr>')
        for key,value in report['summary'].items():
            m=value['methods'];parts.append('<tr><td>'+html.escape(key)+'</td><td>'+str(value['case_count'])+'</td>'+''.join('<td>'+f'{v*100:.2f}%'+'</td>' for v in
                [m['existing']['event_20ms'],m['continuous_refit']['event_20ms'],m['soft_prior']['event_20ms'],m['soft_prior']['event_70ms']])+'</tr>')
        parts.append('</table><details><summary>곡별 수치와 회귀</summary><table><tr><th>사례</th><th>기존 20ms</th><th>재계산 대조군</th><th>선호도 적용</th></tr>')
        for row in report['rows']:
            parts.append('<tr><td>'+html.escape(row['id'])+'</td>'+''.join('<td>'+f'{row["methods"][m]["metrics"]["event_20ms"]["f1"]*100:.2f}%'+'</td>' for m in ('existing','continuous_refit','soft_prior'))+'</tr>')
        parts.append('</table></details>')
    parts.append('<p>부분 구간 점수는 고정된 원본 관측 범위만 평가합니다. BabySlakh는 합성 음원이며 09/12/20의 음악적 기준 해석이 미확정입니다. 제작자 표본 세 곡은 같은 아티스트 그룹입니다. 클릭 시각의 개선이 정확한 변박·변경 위치·마디 원점의 복원을 뜻하지 않습니다.</p></html>')
    (output/'index.html').write_text('\n'.join(parts))
    print(json.dumps({'output':str(output),'case_count_per_setting':len(strong['rows']),'distinct_songs':summary['distinct_songs'],'click':render},indent=2))


if __name__=='__main__':main()
