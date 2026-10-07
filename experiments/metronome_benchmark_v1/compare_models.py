"""Compare frozen and additional fixed-clock predictions on unchanged labels."""

import argparse
from collections import Counter
from copy import deepcopy
import html
import json
from pathlib import Path
import shutil

from .gtzan import aggregate_annotations, score_annotation
from .inference import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--model',action='append',default=[],help='NAME=additional prediction directory')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new comparison output')
    original=json.loads((args.run/'results.json').read_text())
    rows=deepcopy(original['rows']);protocol=deepcopy(original['protocol'])
    selected=[row for row in rows if row['selected_for_inference']]
    references={row['id']:json.loads((args.run/'references'/f'{row["id"]}.json').read_text())
                for row in rows if row['eligible']}
    methods={}
    for item in args.model:
        name,value=item.split('=',1)
        methods[name]=Path(value)
        for condition in ['audio_only','correct_unit_diagnostic']:
            label=name+'_'+condition
            protocol['conditions'].append(label)
            for row in selected:
                path=Path(value)/'predictions'/condition/f'{row["id"]}.json'
                prediction=json.loads(path.read_text()) if path.is_file() else {'status':'inference_failed','error':'missing_prediction'}
                row['conditions'][label]={'prediction':prediction,'metrics':score_annotation(prediction,references[row['id']],protocol)}
    summary=aggregate_annotations(rows,references,protocol,original['summary']['selected_role'])
    genres={genre:aggregate_annotations([row for row in selected if row['genre']==genre],references,protocol,
                                      original['summary']['selected_role'])
            for genre in sorted({row['genre'] for row in selected})}
    results={'source_run':str(args.run.resolve()),'protocol':protocol,'rows':rows,'summary':summary,'by_genre':genres,
             'original_predictions_replaced':False,'added_methods':{name:str(path.resolve()) for name,path in methods.items()}}
    args.output.mkdir(parents=True)
    shutil.copyfile(Path(__file__),args.output/'comparison-source.py')
    write_json(args.output/'results.json',results);write_json(args.output/'summary.json',summary)
    lines=[]
    for name,value in summary['conditions'].items():
        bpm=f"{value['bpm_within_relative_percent']['2']}/{value['pulse_bpm_denominator']}" if 'pulse_bpm_denominator' in value else '—'
        meter=f"{value['bar_pulse_count_matches']}/{value['bar_pulse_count_denominator']}" if 'bar_pulse_count_denominator' in value else '—'
        lines.append(f"<tr><td>{html.escape(name)}</td><td>{bpm}</td><td>{meter}</td><td>{value['failed_or_abstained']}</td>"
                     f"<td>{value['beat_macro_f1']['70']*100:.2f}%</td><td>{value['downbeat_macro_f1']['70']*100:.2f}%</td></tr>")
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>고정 시계 방법 비교</title>
<style>body{{font:15px/1.7 system-ui;background:#f5f7fa;color:#172338}}main{{max-width:1200px;margin:auto;padding:28px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{border:1px solid #d6e0e9;padding:9px;text-align:left}}th{{background:#eef4f8}}</style><main>
<h1>동일 평가 자료의 고정 시계 방법 비교</h1><p>선정 역할 {html.escape(original['summary']['selected_role'])}, 분모 {len(selected)}개. 원래 관측과 주석을 유지하고 추가 방법의 예측을 별도로 채점했습니다. 단위 제공 조건은 참조 기반 진단이며 실제 사용자 탭이 아닙니다.</p>
<table><tr><th>방법·조건</th><th>주석 BPM 오차 ≤2%</th><th>마디당 박 수</th><th>실패·미반환</th><th>박 macro F1@70ms</th><th>마디 macro F1@70ms</th></tr>{''.join(lines)}</table>
<p>기본 이벤트는 고정 시계와 출력 목표가 다릅니다. GTZAN 점수는 기존 주석과의 일치도이며 제작자 시계의 정밀 정확도를 뜻하지 않습니다. 원래 예측과 참조는 바꾸지 않았습니다.</p><p><a href="results.json">표본별 결과와 장르별 비교</a> · <a href="summary.json">집계</a></p></main></html>'''
    (args.output/'report.html').write_text(page,encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
