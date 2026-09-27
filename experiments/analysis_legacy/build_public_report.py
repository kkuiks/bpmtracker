"""Build a local public-corpus report, per-track CSV and known-clock auditions."""

import argparse
import csv
import html
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

from compare_decoders import write_preview


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports',type=Path,nargs='+',required=True)
    parser.add_argument('--catalogs',type=Path,nargs='+',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output directory must be new')
    reports=[json.loads(p.read_text()) for p in args.reports]
    if not all(r['complete'] for r in reports):parser.error('all benchmark runs must be complete')
    catalogs=[json.loads(p.read_text()) for p in args.catalogs]
    catalog={t['id']:t for c in catalogs for t in c['tracks']}
    variants=['official_minimal','legacy_dbn','clock_pipeline']
    names={'official_minimal':'공식 모델','legacy_dbn':'기존 디코더','clock_pipeline':'템포 지도 방식'}
    rows=[]
    for report in reports:
        for track in report['tracks']:
            row={'id':track['id'],'dataset':track['dataset'],'genre':track['genre'],'clock_status':track['clock_status']}
            for variant in variants:
                for key,short in [('beats_seconds','beat'),('downbeats_seconds','downbeat')]:
                    scores=track['scores'][variant]['annotated_span'][key]
                    for tolerance in (.02,.07):
                        row[f'{variant}_{short}_f1_{int(tolerance*1000)}ms']=scores[str(tolerance)]['f1'] if scores else None
            if track['clock_metrics']:
                row.update({k:v for k,v in track['clock_metrics'].items() if k!='changes_0_5s'})
            rows.append(row)
    args.output_dir.mkdir(parents=True)
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with (args.output_dir/'per-track.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    labels=['Official minimal','Historical DBN','Clock pipeline']
    for report in reports:
        for dataset,summary in report['summary'].items():
            for axis,key in zip(axes,['beats_seconds','downbeats_seconds']):
                values=[100*summary['variants'][v]['annotated_span'][key]['macro_f1']['0.07'] for v in variants]
                axis.plot(labels,values,marker='o',label=f"{dataset} (N={summary['variants'][variants[0]]['annotated_span'][key]['track_count']})")
    for axis,title in zip(axes,['Beat F1 at 70 ms','Downbeat F1 at 70 ms']):
        axis.set(title=title,ylabel='Mean per-track F1 (%)',ylim=(0,100));axis.grid(alpha=.2);axis.legend(fontsize=8)
    fig.savefig(args.output_dir/'comparison.png',dpi=160);plt.close(fig)
    cells=[]
    for row in rows:
        scores=[row[f'{v}_beat_f1_70ms'] for v in variants]
        db=[row[f'{v}_downbeat_f1_70ms'] for v in variants]
        values=''.join(f'<td>{100*x:.1f}</td>' if x is not None else '<td>—</td>' for x in scores+db)
        cells.append(f'<tr data-dataset="{html.escape(row["dataset"])}"><td>{html.escape(row["id"])}</td><td>{html.escape(row["genre"])}</td>{values}</tr>')
    # Chosen for authored clock content before seeing BabySlakh predictions:
    # small changes, 2/4 exceptions, a pickup bar and a constant-clock meter edit.
    focus=['babyslakh_Track'+x for x in ['00005','00008','00015','00017','00018']]
    prediction={t['id']:t for r in reports for t in r['tracks']}
    auditions=[]
    for name in focus:
        if name not in catalog or name not in prediction:continue
        source=catalog[name]
        reference=json.loads(Path(source['reference']['path']).read_text())
        audio,sr=sf.read(source['input']['path'],dtype='float32',always_2d=True)
        links=[('원본',Path(source['input']['path']))]
        for key,label,beats,downbeats in [
            ('reference','MIDI 기준 클릭',reference['beats_seconds'],reference['downbeats_seconds'] or []),
            ('prediction','공식 모델 클릭',prediction[name]['variants']['official_minimal']['beats_seconds'],prediction[name]['variants']['official_minimal']['downbeats_seconds'])]:
            target=args.output_dir/'audio'/name/key;target.mkdir(parents=True)
            write_preview(target,beats,downbeats,audio,sr)
            links.append((label,target/'preview.wav'))
        players=''.join(f'<label>{label}<audio controls preload="none" src="{html.escape(os.path.relpath(path,args.output_dir),quote=True)}"></audio></label>' for label,path in links)
        tempos=' → '.join(f"{e['bpm_quarter']:.2f}" for e in reference['tempo_events'])
        meters=' → '.join(f"{e['numerator']}/{e['denominator']}" for e in reference['meter_events'])
        auditions.append(f'<details><summary>{name} · BPM {tempos} · {meters}</summary>{players}</details>')
    summary_rows=[]
    for report in reports:
        for dataset,summary in report['summary'].items():
            for variant in variants:
                beat=summary['variants'][variant]['annotated_span']['beats_seconds']
                downbeat=summary['variants'][variant]['annotated_span']['downbeats_seconds']
                summary_rows.append(f"<tr><td>{dataset}</td><td>{names[variant]}</td><td>{beat['track_count']}</td><td>{100*beat['macro_f1']['0.07']:.1f}</td><td>{downbeat['track_count']}</td><td>{100*downbeat['macro_f1']['0.07']:.1f}</td></tr>")
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>공개 기준 자료 평가</title>
<style>body{max-width:1250px;margin:30px auto;padding:0 20px;font:15px/1.6 system-ui;color:#213041;background:#f5f7fa}table{border-collapse:collapse;background:white;width:100%;margin:20px 0}td,th{padding:7px 10px;border-bottom:1px solid #dce2ea;text-align:left}th{background:#e7eef7}img{width:100%}.note{background:#fff0cd;padding:15px}audio{width:100%;display:block}details{background:white;padding:14px;margin:10px 0}summary{cursor:pointer}select{padding:7px}</style>
<h1>공개 기준 자료로 넓힌 평가</h1><p>모델: Beat This final0. 동일한 모델 출력에 공식 디코더, 기존 DBN, 보수적 연속 템포 지도 복원을 비교했습니다. 정답을 이용한 BPM 배수 선택·시간 이동·파라미터 조정은 하지 않았습니다.</p>
<p class="note">GTZAN은 사람이 표시한 박자와 공개 특징 데이터를 사용하며 원본 음원은 이 묶음에 없습니다. BabySlakh는 실제 렌더링용 MIDI와 합성 멀티트랙 음원을 사용합니다. 두 자료는 정답의 성격이 달라 별도로 집계합니다. F1은 ±70ms 안의 박자 일치를 곡별로 계산한 평균이며, 완벽히 분석된 곡의 비율이 아닙니다.</p>
<table><thead><tr><th>자료</th><th>방법</th><th>박자 N</th><th>박자 F1</th><th>첫 박 N</th><th>첫 박 F1</th></tr></thead><tbody>SUMMARY</tbody></table><img src="comparison.png" alt="자료별 박자·첫 박 F1 비교">
<h2>알려진 시간축으로 비교 청취</h2><p>표본은 예측 성능을 보기 전에 MIDI의 템포·박자 변화 내용으로 골랐습니다. MIDI 클릭은 악기 타격음 그 자체가 아니라 제작 시간축입니다. 플레이어 시간은 원본 기준이며 볼륨은 미리듣기별로 조금 다를 수 있습니다.</p>AUDITIONS
<h2>표본별 결과</h2><p><a href="per-track.csv">20ms·70ms 지표와 템포 오차를 포함한 CSV</a></p><label>자료 선택 <select id="filter"><option value="all">전체</option><option value="gtzan">GTZAN</option><option value="babyslakh">BabySlakh</option></select></label>
<table id="tracks"><thead><tr><th>표본</th><th>장르</th><th>박자: 공식</th><th>박자: DBN</th><th>박자: 지도</th><th>첫 박: 공식</th><th>첫 박: DBN</th><th>첫 박: 지도</th></tr></thead><tbody>ROWS</tbody></table>
<script>document.querySelector('#filter').onchange=e=>{for(const r of document.querySelectorAll('#tracks tbody tr'))r.hidden=e.target.value!=='all'&&r.dataset.dataset!==e.target.value};let active=null;for(const a of document.querySelectorAll('audio'))a.onplay=()=>{if(active&&active!==a)active.pause();active=a};</script></html>'''
    page=page.replace('SUMMARY',''.join(summary_rows)).replace('AUDITIONS',''.join(auditions)).replace('ROWS',''.join(cells))
    (args.output_dir/'index.html').write_text(page,encoding='utf-8')
    print(args.output_dir/'index.html')


if __name__=='__main__':
    main()
