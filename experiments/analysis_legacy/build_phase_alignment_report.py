"""Build a complete review of calibration, shifts, abstentions and regressions."""
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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    if args.output_dir.exists():p.error('output must be new')
    report=json.loads(args.report.read_text());cal=json.loads(args.calibration.read_text())
    if sha256(args.calibration)!=report['configuration']['calibration']['sha256']:raise ValueError('wrong calibration')
    output=args.output_dir;output.mkdir(parents=True)
    methods=['unchanged','pooled_calibrated','uncalibrated_consensus','calibrated_consensus']
    rows=[]
    for row in report['rows']:
        for method in methods:
            value=row['methods'][method];proposal=value['proposal'];metrics=value['metrics']
            rows.append({'case':row['id'],'scope':row['scope'],'cohort':row['cohort'],'model':row['model'],
                'method':method,'shift_ms':proposal['applied_shift_seconds']*1000,'status':proposal['status'],
                **{key:metrics['event_'+key]['f1'] for key in ('10ms','20ms','70ms')}})
    with (output/'cases.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    counts={}
    for row in report['rows']:
        status=row['methods']['calibrated_consensus']['proposal']['status'];counts[status]=counts.get(status,0)+1
    figure,(ax,cal_ax)=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    keys=['full_clock/babyslakh/beat_this','full_clock/babyslakh/beat_transformer',
          'full_clock/forestry_producer_pilot/beat_this','conditional_completion/forestry_producer_pilot/combined']
    labels=['Synth 20\nBeat This','Synth 6\nBeat Transformer','Creator 3\nBeat This','Light\ncompletion']
    positions=np.arange(len(keys))
    for offset,method,label in [(-.26,'unchanged','Unchanged'),(0,'pooled_calibrated','Ungated pooled'),(.26,'calibrated_consensus','Consensus / abstention')]:
        values=[report['summary'][k]['methods'][method]['mean_f1_20ms']*100 for k in keys]
        ax.bar(positions+offset,values,width=.25,label=label)
    ax.set_xticks(positions,labels);ax.set_ylim(0,110);ax.set_ylabel('20 ms event F1 (%)');ax.legend(fontsize=8)
    ax.set_title('Whole-song paths; partial regions evaluated separately')
    bands=list(cal['bands'])
    fast=[cal['bands'][b]['fast_validation_p95_absolute_seconds']*1000 for b in bands]
    slow=[cal['bands'][b]['slow_validation_p95_absolute_seconds']*1000 for b in bands]
    x=np.arange(3);cal_ax.bar(x-.17,fast,.34,label='Fast synthetic attacks');cal_ax.bar(x+.17,slow,.34,label='Slow synthetic attacks')
    cal_ax.set_xticks(x,['8 ms smooth','1-8 ms detail','<1 ms detail']);cal_ax.set_ylabel('P95 absolute timing error (ms)')
    cal_ax.set_title('Calibration validation: attack timing, not musical beat accuracy');cal_ax.legend(fontsize=8)
    figure.savefig(output/'comparison.png',dpi=160);plt.close(figure)
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>클릭 위치 보정 실험</title>',
        '<style>body{font:16px/1.6 system-ui;max-width:1250px;margin:30px auto;padding:0 20px;color:#213449}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border:1px solid #ccd8e1;text-align:left}th{background:#edf3f7}img{max-width:100%}.warn{background:#fff2dd;padding:16px}details{margin:20px 0}</style>',
        '<h1>클릭 위치 보정 · 개발 표본 실험</h1>',
        '<p>기존 강한 BPM 선호도 지도를 기준으로 23곡, 57사례를 평가했습니다. 전곡 모델 경로 32개·부분 구간 24개·Light 연결 지도 1개이며, 독립적인 곡 57개를 뜻하지 않습니다.</p>',
        '<p class="warn">합성 타격음의 시각 검증은 통과했지만, 실제 음악의 원래 클릭 위치를 확정하지는 못했습니다. 합성 음원에서는 개선 사례가 있었고, 제작자 음원의 전곡 보정은 보류됐습니다. Light의 Beat Transformer 앞부분 지도에서는 오보정도 발생했습니다. 자동 기본값으로 채택하지 않았습니다.</p>',
        '<p><a href="cases.csv">모든 사례 CSV</a> · <a href="summary.json">출처와 요약 JSON</a></p>',
        '<img src="comparison.png" alt="코호트별 20ms 점수와 합성 타격음 시각 검증 결과">',
        '<p>비교군: 기존 유지, 보류 없이 전체 근거를 합치는 방식, 시각 보정 없이 합의만 적용, 시각 보정 후 여러 구간·특징의 합의가 있을 때만 적용. 모두 원본 오디오·BPM·박 간격을 유지합니다.</p>',
        '<table><tr><th>평가 범위 / 자료 / 모델</th><th>사례 수</th><th>기존 20ms</th><th>보류 없는 보정</th><th>합의 보정 20ms</th><th>기존 → 보정 10ms</th><th>이동 사례</th></tr>']
    for key,value in report['summary'].items():
        m=value['methods'];parts.append('<tr><td>'+html.escape(key)+'</td><td>'+str(value['case_count'])+'</td>'+''.join('<td>'+f'{m[n]["mean_f1_20ms"]*100:.2f}%'+'</td>' for n in ('unchanged','pooled_calibrated','calibrated_consensus'))+
            '<td>'+f'{m["unchanged"]["mean_f1_10ms"]*100:.2f}% → {m["calibrated_consensus"]["mean_f1_10ms"]*100:.2f}%'+'</td><td>'+str(m['calibrated_consensus']['changed_cases'])+'</td></tr>')
    parts.append('</table><details><summary>모든 사례의 보정·보류·회귀</summary><table><tr><th>사례</th><th>판정</th><th>이동 ms</th><th>기존 → 보정 20ms</th><th>기존 → 보정 10ms</th></tr>')
    for row in report['rows']:
        a=row['methods']['unchanged'];b=row['methods']['calibrated_consensus']
        parts.append('<tr><td>'+html.escape(row['id'])+'</td><td>'+html.escape(b['proposal']['status'])+'</td><td>'+f'{b["proposal"]["applied_shift_seconds"]*1000:.2f}'+'</td>'+''.join('<td>'+f'{a["metrics"]["event_"+k]["f1"]*100:.2f}% → {b["metrics"]["event_"+k]["f1"]*100:.2f}%'+'</td>' for k in ('20ms','10ms'))+'</tr>')
    parts.append('</table></details><p>정답은 모든 예측 파일을 저장한 뒤 평가에만 사용했습니다. 시각 보정량은 합성 타격음에서 구했습니다. 주파수 특징들은 같은 음원에서 만들어져 독립적인 악기나 독립적인 표가 아닙니다. 기존 지도에 없던 템포 변경은 추가하지 않았으며, 승인된 지도와 사용자 기준점이 있는 지도는 변경 대상에서 제외했습니다.</p></html>')
    (output/'index.html').write_text('\n'.join(parts))
    summary={'report_path':str(args.report),'report_sha256':sha256(args.report),'calibration_path':str(args.calibration),
        'calibration_sha256':sha256(args.calibration),'summary':report['summary'],'decision_counts':counts,
        'default_promoted':False,'human_listening_performed':False}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'output':str(output),'decision_counts':counts},indent=2))


if __name__=='__main__':main()
