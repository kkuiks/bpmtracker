"""Compare fixed clocks with verified, defined generated transport clocks."""

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import shutil

import numpy as np

from experiments.metronome_reconstruction_v1.grid import rational_pool
from .inference import write_json
from .metrics import clock_error, event_f1, is_clock


def score(prediction,reference,duration,model):
    returned=is_clock(prediction)
    values={'returned_clock':returned,'status':prediction.get('status','missing'),
            'reference_kind':'defined_generated_transport','real_producer_precision_claim':False,
            'origin_coordinate_bound_ms':reference['origin_coordinate_bound_ms']}
    values['quarter_f1']={str(ms):event_f1(prediction.get('quarter_clicks_seconds',[]) if returned else [],
        reference['quarter_times_seconds'],ms/1000)['f1'] for ms in [10,20,30,70]}
    values['downbeat_f1']={str(ms):event_f1(prediction.get('downbeats_seconds',[]) if returned else [],
        reference['downbeat_times_seconds'],ms/1000)['f1'] for ms in [10,20,30,70]}
    nearest=min(rational_pool(model['bpm_min'],model['bpm_max'],model['denominator_max']),
                key=lambda value:abs(float(value)-reference['quarter_bpm']))
    values['reference_bpm_exactly_in_output_vocabulary']=abs(float(nearest)-reference['quarter_bpm'])<1e-9
    values['vocabulary_minimum_rate_drift_ms']=duration*(reference['quarter_bpm']/float(nearest)-1)*1000
    if returned:
        signature=prediction['time_signature']
        values.update({'bpm_relative_error_percent':abs(prediction['quarter_bpm']/reference['quarter_bpm']-1)*100,
            'meter_match':signature==reference['time_signature'],
            'quarter_clock':clock_error(reference['quarter_times_seconds'],prediction['period_seconds'],prediction['offset_seconds']),
            'bar_clock':clock_error(reference['downbeat_times_seconds'],prediction['period_seconds']*signature['numerator']*4/signature['denominator'],prediction['offset_seconds']),
            'confidence_flags':prediction.get('confidence_flags',[])})
    return values


def summarize(rows,names):
    summary={}
    for name in names:
        metrics=[row['conditions'][name]['metrics'] for row in rows]
        clocks=[value for value in metrics if value['returned_clock']]
        represented=[value for value in metrics if value['reference_bpm_exactly_in_output_vocabulary']]
        summary[name]={'denominator':len(metrics),'returned_clocks':len(clocks),'failed_or_abstained':len(metrics)-len(clocks),
            'bpm_within_0_1_percent':sum(value['bpm_relative_error_percent']<=.1 for value in clocks),
            'meter_matches':sum(value['meter_match'] for value in clocks),
            'quarter_macro_f1':{str(ms):float(np.mean([value['quarter_f1'][str(ms)] for value in metrics])) for ms in [10,20,30,70]},
            'downbeat_macro_f1':{str(ms):float(np.mean([value['downbeat_f1'][str(ms)] for value in metrics])) for ms in [10,20,30,70]},
            'representable_denominator':len(represented),
            'representable_quarter_and_bar_max_within_ms':{str(ms):sum(value['returned_clock']
                and value['quarter_clock']['maximum_absolute_ms']<=ms and value['bar_clock']['maximum_absolute_ms']<=ms
                for value in represented) for ms in [10,20,30,70]},
            'maximum_quarter_drift_ms_returned':max((abs(value['quarter_clock']['accumulated_drift_ms']) for value in clocks),default=None)}
    return summary


def paired_contrasts(rows, names):
    baselines = {row['parent_group']: row for row in rows if row['variant'] == 'straight'}
    pairs = []
    for row in rows:
        if row['variant'] == 'straight':
            continue
        base = baselines[row['parent_group']]
        expected_shift = row['defined_reference_clock']['offset_seconds'] - base['defined_reference_clock']['offset_seconds']
        conditions = {}
        for name in names:
            first = base['conditions'][name]['prediction']
            changed = row['conditions'][name]['prediction']
            same = (is_clock(first) and is_clock(changed)
                    and first['quarter_bpm'] == changed['quarter_bpm']
                    and first['time_signature'] == changed['time_signature'])
            residual = None
            if same:
                signature = first['time_signature']
                bar = first['period_seconds'] * signature['numerator'] * 4 / signature['denominator']
                delta = changed['offset_seconds'] - first['offset_seconds'] - expected_shift
                residual = ((delta + bar / 2) % bar - bar / 2) * 1000
            conditions[name] = {'same_predicted_rate_and_meter': same,
                                'bar_phase_shift_residual_ms': residual,
                                'phase_comparison_requires_unchanged_predicted_clock': True}
        pairs.append({'baseline_id': base['id'], 'changed_id': row['id'], 'variant': row['variant'],
                      'parent_group': row['parent_group'], 'defined_transport_shift_seconds': expected_shift,
                      'conditions': conditions})
    return {'parent_groups': len({row['parent_group'] for row in pairs}), 'pair_count': len(pairs),
            'pure_source_shift_pair_variant': 'leading_shift',
            'arrangement_changes_can_also_change_noise_voice_realizations': True,
            'unchanged_clock_agreement_is_not_a_real_music_accuracy_claim': True, 'pairs': pairs}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--model-config',type=Path,required=True)
    parser.add_argument('--method',action='append',required=True,help='NAME=prediction output directory')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new result directory')
    model=json.loads(args.model_config.read_text())
    rows=json.loads((args.corpus/'source-inputs.json').read_text())['samples']
    methods=dict(item.split('=',1) for item in args.method)
    names=[]
    for row in rows:
        reference=json.loads((args.corpus/'references'/f'{row["id"]}.json').read_text())
        clock=json.loads((args.corpus/'inputs'/row['id']/'clock.json').read_text())
        row.update({'variant':clock['variant'],'parent_group':clock['parent_group'],'conditions':{},
                    'defined_reference_clock':{key:reference[key] for key in ['quarter_bpm','time_signature','offset_seconds']}})
        for method,path in methods.items():
            for condition in ['audio_only','correct_unit_diagnostic']:
                name=method+'_'+condition
                if name not in names:names.append(name)
                file=Path(path)/'predictions'/condition/f'{row["id"]}.json'
                prediction=json.loads(file.read_text()) if file.is_file() else {'status':'inference_failed','error':'missing_prediction'}
                row['conditions'][name]={'prediction':prediction,'metrics':score(prediction,reference,row['duration_seconds'],model)}
    summary=summarize(rows,names)
    by_variant={variant:summarize([row for row in rows if row['variant']==variant],names) for variant in sorted({row['variant'] for row in rows})}
    result={'corpus':str(args.corpus.resolve()),'summary':summary,'by_variant':by_variant,'rows':rows,
            'paired_contrasts':paired_contrasts(rows,names),
            'real_recording_generalization_evidence':False,'known_clock_is_not_uniquely_identifiable_from_all_arrangements':True}
    args.output.mkdir(parents=True)
    shutil.copyfile(Path(__file__),args.output/'scoring-source.py')
    write_json(args.output/'results.json',result);write_json(args.output/'summary.json',summary)
    lines=[]
    for name,value in summary.items():
        lines.append(f"<tr><td>{html.escape(name)}</td><td>{value['returned_clocks']}/{value['denominator']}</td>"
            f"<td>{value['bpm_within_0_1_percent']}</td><td>{value['meter_matches']}</td>"
            f"<td>{value['representable_quarter_and_bar_max_within_ms']['20']}/{value['representable_denominator']}</td>"
            f"<td>{value['quarter_macro_f1']['20']*100:.2f}%</td><td>{value['downbeat_macro_f1']['20']*100:.2f}%</td></tr>")
    (args.output/'report.html').write_text(f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>생성 시계 대조 실험</title>
<style>body{{font:15px/1.7 system-ui;background:#f5f7fa;color:#172338}}main{{max-width:1300px;margin:auto;padding:28px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #d6e0e9;padding:9px;text-align:left}}</style>
<main><h1>알려진 생성 시계와 음악 대조 실험</h1><p>입력 {len(rows)}개, 정의한 생성 시계와 오디오 좌표를 별도 검증 신호 및 실제 배치 기록으로 확인했습니다. 검증 신호는 모델에 제공하지 않았습니다. 실제 음악 일반화나 실제 제작자의 정답을 인증하는 실험과 구분됩니다.</p>
<table><tr><th>방법</th><th>시계 반환</th><th>BPM 오차 ≤0.1%</th><th>박자표 일치</th><th>표현 가능한 시계: 박·마디 최대오차 ≤20ms</th><th>박 macro F1@20ms</th><th>마디 macro F1@20ms</th></tr>{''.join(lines)}</table>
<p>120.1 BPM 긴 입력은 현재 분모 4 이하 후보의 표현 한계를 보는 사전 정의 진단입니다. 표현 가능한 입력의 정밀 집계와 따로 기록합니다. 반속도·배속도 배치 및 약한 강세에서는 음악만으로 의도한 시계를 유일하게 고르기 어려울 수 있어, 자동 조건과 단위 제공 진단을 분리합니다.</p>
<p><a href="results.json">표본별·대조 유형별 기록</a> · <a href="summary.json">집계</a></p></main></html>''',encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
