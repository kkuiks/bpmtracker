"""Build the iterative clock-decoding evidence page and source-aligned auditions."""

import argparse
import html
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import soundfile as sf

from compare_decoders import write_preview


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison',type=Path,required=True)
    parser.add_argument('--probe',type=Path,required=True)
    parser.add_argument('--bar-report',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    comparison=json.loads(args.comparison.read_text())
    probe=json.loads(args.probe.read_text())
    if not comparison['complete'] or not probe['complete']:parser.error('comparisons must be complete')
    rows={t['id']:t for t in comparison['tracks']}
    bars={t['id']:t for t in json.loads(args.bar_report.read_text())['tracks']}
    catalog={t['id']:t for t in json.loads(args.catalog.read_text())['tracks']}
    args.output_dir.mkdir(parents=True)
    focus=['babyslakh_Track'+n for n in ('00005','00017','00008','00018')]
    fig,axes=plt.subplots(4,1,figsize=(13,13),layout='constrained')
    cards=[]
    for ax,name in zip(axes,focus):
        entry=catalog[name];row=rows[name]
        ref=json.loads(Path(entry['reference']['path']).read_text())
        duration=entry['duration_seconds']
        for key,label,color in [('old_clock','Previous meter-coupled clock','#b95c61'),('meter_free_clock','Meter-free pulse clock candidate','#217959')]:
            clock=row['methods'][key]['clock']
            if clock:
                segments=clock['segments'];x=[s['start_seconds'] for s in segments]+[segments[-1]['end_seconds']]
                y=[s['pulse_rate_per_minute'] for s in segments]+[segments[-1]['pulse_rate_per_minute']]
                ax.step(x,y,where='post',label=label,color=color,linewidth=1.4)
        events=ref['tempo_events']
        ax.step([e['time_seconds'] for e in events]+[duration],[e['bpm_quarter'] for e in events]+[events[-1]['bpm_quarter']],
                where='post',label='Rendered MIDI quarter clock',color='#302d70',linestyle='--',linewidth=1.1)
        meter=ref['meter_events']
        first=True
        for i,event in enumerate(meter):
            if event['numerator']==2 and event['denominator']==4:
                end=meter[i+1]['time_seconds'] if i+1<len(meter) else duration
                ax.axvspan(event['time_seconds'],end,color='#f0bb44',alpha=.3,label='Reference 2/4 bar' if first else None)
                first=False
        ax.set(title=name+(' — unresolved half/double interpretation' if name.endswith('00018') else ''),
               xlabel='Original source time (seconds)',ylabel='Pulses / minute',xlim=(194,214) if name.endswith('00017') else (0,duration))
        ax.grid(alpha=.2);ax.legend(fontsize=8,loc='best')
        audio,sr=sf.read(entry['input']['path'],dtype='float32',always_2d=True)
        new=row['methods']['meter_free_clock']['prediction'];old=row['methods']['old_clock']['prediction']
        choices=[('reference','MIDI 기준 클릭',ref['beats_seconds'],ref['downbeats_seconds'] or []),
                 ('old','기존 지도 클릭',old['beats_seconds'],old['downbeats_seconds']),
                 ('pulse','새 템포 후보 · 첫 박 강조 없음',new['beats_seconds'],[]),
                 ('bar','새 첫 박 후보 · 변박 위치 미확정',new['beats_seconds'],bars[name]['methods']['variable']['prediction']['downbeats_seconds'])]
        players=[]
        for key,label,beats,downbeats in choices:
            target=args.output_dir/'audio'/name/key;target.mkdir(parents=True)
            write_preview(target,beats,downbeats,audio,sr)
            relative=html.escape(os.path.relpath(target/'preview.wav',args.output_dir),quote=True)
            players.append(f'<label>{html.escape(label)}<audio controls preload="none" src="{relative}"></audio></label>')
        metrics=row['methods']['meter_free_clock']['clock_metrics']
        cards.append(f'<details><summary>{name}</summary><p>미리듣기는 모두 원본 시간과 길이를 유지합니다. 다른 플레이어를 켜면 같은 곡의 직전 재생 위치에서 비교합니다.</p>{"".join(players)}<pre>{html.escape(json.dumps(metrics,indent=2))}</pre></details>')
    fig.savefig(args.output_dir/'comparison.png',dpi=150);plt.close(fig)
    table=[]
    for cohort,report in [('기존 개발 표본',comparison),('추가 고정 표본',probe)]:
        for dataset,summary in report['summary'].items():
            for name,label in [('official_raw','공식 원본'),('old_clock','기존 지도'),('meter_free_clock','새 템포 후보')]:
                m=summary['methods'][name]['metrics'];beat=m['beats_seconds'];down=m['downbeats_seconds']
                table.append(f"<tr><td>{cohort} · {dataset}</td><td>{label}</td><td>{beat['count']}</td><td>{100*beat['macro_f1']['0.07']:.2f}</td><td>{100*beat['macro_f1']['0.02']:.2f}</td><td>{down['count']}</td><td>{100*down['macro_f1']['0.07']:.2f}</td></tr>")
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>템포·변박 분리 실험</title>
<style>body{max-width:1200px;margin:30px auto;padding:0 20px;background:#f4f6f9;color:#233044;font:15px/1.65 system-ui}img{width:100%}table{width:100%;background:white;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #d8dfe8;text-align:left}th{background:#e7eef6}.note{background:#fff1d3;padding:15px}details{background:white;padding:15px;margin:12px 0}summary{cursor:pointer;font-weight:600}audio{display:block;width:100%;margin:8px 0 16px}pre{white-space:pre-wrap;font-size:12px}</style>
<h1>변박이 템포를 왜곡하는 경로 분리</h1><p>Track00017의 가짜 템포 변화가 없어졌고, Track00005의 변화 위치 검출은 1/5에서 4/5로 개선됐습니다. Track00008의 성공도 유지했습니다.</p>
<p class="note">새 후보는 자동 확정된 결과가 아닙니다. 반속·배속 선택과 정확한 변박 위치는 미해결이며, 20ms 지표나 일부 곡에서는 손해가 있습니다. 템포 후보와 첫 박 후보를 따로 검토하세요. 드럼 스템을 추가한 실험도 변박 위치 문제를 해결하지 못했습니다.</p>
<table><thead><tr><th>표본</th><th>방법</th><th>박자 N</th><th>박자 F1 70ms</th><th>박자 F1 20ms</th><th>첫 박 N</th><th>첫 박 F1 70ms</th></tr></thead><tbody>TABLE</tbody></table>
<p>수치는 곡별 F1의 평균(%)입니다. 추가 표본은 기존 곡 ID·동일 특징 파일을 제외한 50개이며, 아티스트·근접 중복까지 독립적인 최종 시험 세트는 아닙니다. 추가 결과를 보기 전에 후보 코드와 설정을 고정했습니다.</p>
<img src="comparison.png" alt="기준 템포와 기존·신규 후보 비교"><h2>원본 시간축에서 비교 청취</h2>CARDS
<script>let active=null;for(const a of document.querySelectorAll('audio'))a.onplay=()=>{if(active&&active!==a){if(active.closest('details')===a.closest('details'))a.currentTime=active.currentTime;active.pause()}active=a};</script></html>'''
    (args.output_dir/'index.html').write_text(page.replace('TABLE',''.join(table)).replace('CARDS',''.join(cards)),encoding='utf-8')
    print(args.output_dir/'index.html')


if __name__=='__main__':main()
