"""Explain annotation disagreements from a completed source-only clock trace."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import html
import json
from pathlib import Path
import shutil

from experiments.metronome_reconstruction_v1.grid import rational_pool, timestamps
from .inference import write_json
from .metrics import event_f1
from .gtzan import aggregate_annotations
from .trace import candidate_key


def alignment(candidate, reference, duration, tolerance):
    start, end = reference['support_seconds']
    def events(period):
        values = timestamps(period, candidate['offset_seconds'], duration)
        return values[(values >= start) & (values < end)].tolist()
    beat = event_f1(events(candidate['period_seconds']), reference['beat_times_seconds'], tolerance)['f1']
    bar = event_f1(events(candidate['period_seconds'] * candidate['time_signature']['numerator']),
                   reference['downbeat_times_seconds'], tolerance)['f1'] if reference['downbeat_times_seconds'] is not None else None
    return {'beat_f1':beat, 'downbeat_f1':bar, 'balanced_f1':(beat + bar) / 2 if bar is not None else beat}


def compact(record, reference, duration, tolerance):
    row = record['candidate']
    return {'score_id':record['score_id'],'block':record['block'],'stage':record['stage'],
        'bpm':row['quarter_bpm'],'period_seconds':row['period_seconds'],
        'meter':row['time_signature'],'offset_seconds':row['offset_seconds'],'score':row['score'],
        'bpm_error_percent':abs(row['quarter_bpm'] / reference['pulse_bpm'] - 1) * 100,
        'beat_evidence_f1':row['beat_evidence']['weighted_smooth_f1'],
        'downbeat_evidence_f1':row['downbeat_evidence']['weighted_smooth_f1'],
        'annotation_alignment':alignment(row,reference,duration,tolerance)}


def inspect_trace(row, reference, records, events, metadata, config, primary_ms):
    prediction = row['conditions']['audio_only']['prediction']
    metrics = row['conditions']['audio_only']['metrics']
    expected = reference['pulse_bpm']
    pool = rational_pool(config['bpm_min'],config['bpm_max'],config['denominator_max'])
    nearest = min(pool,key=lambda value:abs(float(value)-expected))
    unique = {}
    for record in records:
        key = (record['block'],candidate_key(record['candidate']))
        previous = unique.get(key)
        if previous is None or record['candidate']['score'] > previous['candidate']['score']:
            unique[key] = record
    family = sorted((record for record in unique.values() if record['block'].startswith('layer_')),
                    key=lambda record:record['candidate']['score'],reverse=True)
    base = [record for record in unique.values() if record['block']=='base_search']
    tolerance = primary_ms / 1000
    def compatible(records):
        return [record for record in records if abs(record['candidate']['quarter_bpm']/expected-1)*100 <= 2]
    family_rate, base_rate = compatible(family), compatible(base)
    targets = [record for record in family_rate if reference['bar_pulse_count'] is None
               or record['candidate']['time_signature']['numerator']==reference['bar_pulse_count']]
    evaluated = [(record,alignment(record['candidate'],reference,row['duration_seconds'],tolerance)) for record in targets]
    best = max(evaluated,key=lambda pair:(pair[1]['balanced_f1'], -abs(pair[0]['candidate']['quarter_bpm']/expected-1),
                                         pair[0]['candidate']['score']),default=None)
    ranks = {record['score_id']:index for index,record in enumerate(family,1)}
    retained = {ident for event in events if event['event']=='block_finished'
                for ident in event['retained_score_ids'] if ident is not None}
    refined = {event['score_id'] for event in events if event['event']=='refinement_seed'}
    source_rate = metrics.get('rate_relation')
    categories = []
    if not metrics['returned_prediction']:
        categories.append('no_automatic_clock')
    elif source_rate != 'within_2_percent':
        categories.append('annotation_rate_disagreement')
        categories.append('compatible_rate_scored_but_not_selected' if family_rate else 'no_compatible_rate_in_final_family')
        if base_rate and not family_rate:
            categories.append('compatible_base_rate_lost_in_family_narrowing')
    if metrics.get('bar_pulse_count_match') is False:
        categories.append('annotation_bar_pulse_count_disagreement')
    beat = metrics['beat_f1'][str(primary_ms)]['f1']
    bar = metrics['downbeat_f1'][str(primary_ms)]['f1'] if metrics['downbeat_f1'] is not None else None
    if beat == 1 and bar == 0:
        categories.append('perfect_beats_zero_downbeats')
    if source_rate=='within_2_percent' and (beat < .9 or (bar is not None and bar < .9)):
        categories.append('timing_disagreement_at_diagnostic_0_9_cutoff')
    output = {'id':row['id'],'genre':row['genre'],'categories':categories,
        'primary_rate_relation':source_rate,'primary_beat_f1':beat,'primary_downbeat_f1':bar,
        'vocabulary':{'nearest_bpm':float(nearest),'fraction':{'numerator':nearest.numerator,'denominator':nearest.denominator},
            'minimum_relative_error_percent':abs(float(nearest)/expected-1)*100,
            'rate_implied_drift_ms_over_input':row['duration_seconds']*(expected/float(nearest)-1)*1000,
            'exact_expression':abs(float(nearest)-expected)<1e-9,
            'original_reference_bpm':expected},
        'trace':{'complete':metadata['complete'],'score_calls':len(records),'unique_family_clocks':len(family),
                 'unique_base_clocks':len(base),'rate_compatible_family_clocks':len(family_rate),
                 'rate_compatible_base_clocks':len(base_rate),
                 'nearest_allowed_bpm_in_family':any(abs(record['candidate']['quarter_bpm']-float(nearest))<1e-9 for record in family)},
        'oracle_diagnostic_is_not_a_primary_prediction':True,
        'reference_precision_verified':reference['precise_producer_clock_verified'],
        'reference_notation_verified':reference['notation_denominator_verified'],
        'causal_status':'unresolved: source evidence, annotation interpretation and model choice are not independently adjudicated'}
    if best:
        target = compact(best[0],reference,row['duration_seconds'],tolerance)
        target.update({'audio_score_rank_among_unique_family_clocks':ranks[best[0]['score_id']],
            'selected_score_minus_candidate':prediction.get('score',0)-target['score'],
            'retained_in_public_top_candidates':best[0]['score_id'] in retained,
            'was_refinement_seed':best[0]['score_id'] in refined})
        output['best_annotation_agreement_clock_in_family'] = target
        if metrics['returned_prediction']:
            same = [(record,agreement) for record,agreement in evaluated
                    if record['candidate']['bpm_fraction']==prediction['bpm_fraction']
                    and record['candidate']['time_signature']==prediction['time_signature']]
            alternative = max(same,key=lambda pair:pair[1]['balanced_f1'],default=None)
            if alternative:
                target_phase = compact(alternative[0],reference,row['duration_seconds'],tolerance)
                output['best_annotation_phase_with_selected_rate_meter'] = target_phase
                output['selected_downbeat_evidence_minus_annotation_phase'] = (
                    prediction['downbeat_evidence']['weighted_smooth_f1']-target_phase['downbeat_evidence_f1'])
    return output


def partition_summary(results, previous_ids):
    selected = [row for row in results['rows'] if row['selected_for_inference']]
    groups = {'original100':[row for row in selected if row['id'] in previous_ids],
              'additional180':[row for row in selected if row['id'] not in previous_ids],
              'complete_development':selected}
    refs = {row['id']:{'bar_pulse_count':row['reference_fixed_fit']['bar_pulse_count']} for row in selected}
    return {name:aggregate_annotations(rows,refs,results['protocol'],'development') for name,rows in groups.items()}


def render(report):
    esc=lambda value:html.escape(str(value))
    data=report['diagnostics']
    counts=report['category_counts']
    summaries=[]
    for name,value in report['partitions'].items():
        auto=value['conditions']['audio_only']
        summaries.append(f"<tr><td>{esc(name)}</td><td>{value['selected_count']}</td><td>{auto['bpm_within_relative_percent']['2']}</td>"
                         f"<td>{auto['beat_macro_f1']['70']*100:.2f}%</td><td>{auto['downbeat_macro_f1']['70']*100:.2f}%</td></tr>")
    rows=[]
    for item in data:
        best=item.get('best_annotation_agreement_clock_in_family',{})
        rows.append(f"<tr><td>{esc(item['id'])}</td><td>{esc(', '.join(item['categories']) or 'no_named_disagreement')}</td>"
            f"<td>{item['trace']['score_calls']}</td><td>{item['trace']['rate_compatible_family_clocks']}</td>"
            f"<td>{esc(best.get('audio_score_rank_among_unique_family_clocks','—'))}</td>"
            f"<td>{esc(best.get('selected_score_minus_candidate','—'))}</td></tr>")
    return f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>개발 전체 동결 평가와 선택 진단</title><style>body{{font:15px/1.7 system-ui;background:#f5f7fa;color:#172338}}main{{max-width:1450px;margin:auto;padding:24px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #d6e0e9;padding:8px;text-align:left}}th{{background:#eef4f8}}.note{{background:#fff4da;padding:18px}}.scroll{{overflow-x:auto}}</style><main>
<h1>개발 전체 동결 평가와 후보 선택 진단</h1><p class="note">후보의 참조 일치도를 사후에 비교한 값은 원인 분석용 진단입니다. 가장 잘 맞는 후보를 실제 모델 예측으로 바꾸지 않습니다. GTZAN 주석은 제작자의 정밀 시계나 악보의 4분음표로 인증되지 않았습니다.</p>
<h2>같은 모델, 다른 평가 범위</h2><table><tr><th>범위</th><th>분모</th><th>BPM 오차 ≤2%</th><th>박 macro F1@70ms</th><th>마디 macro F1@70ms</th></tr>{''.join(summaries)}</table>
<h2>진단 유형</h2><p>{esc(json.dumps(counts,ensure_ascii=False))}</p><p>유형은 겹칠 수 있습니다. 0.9 F1 기준은 후속 탐색용 진단이며 제품 합격 기준이 아닙니다. 생성·선택의 관찰은 알고리즘 또는 주석의 정오를 독립적으로 확정하지 않습니다.</p>
<h2>표본별 기록</h2><div class="scroll"><table><tr><th>ID</th><th>유형</th><th>전체 점수 계산 수</th><th>참조 속도 근처 후보 수</th><th>참조 일치가 좋은 후보의 원래 점수 순위</th><th>선택 점수와의 차이</th></tr>{''.join(rows)}</table></div>
<p><a href="decomposition.json">전체 진단</a> · <a href="partitions.json">100·추가·전체 비교</a> · <a href="repeat-comparison.json">기존 예측 재현</a></p></main></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new analysis directory')
    results=json.loads((args.run/'results.json').read_text())
    old=json.loads((args.previous/'results.json').read_text())
    config=json.loads((args.run/'model-config.json').read_text())
    ids={row['id'] for row in old['rows'] if row['selected_for_inference']}
    selected=[row for row in results['rows'] if row['selected_for_inference']]
    if not ids.issubset({row['id'] for row in selected}):
        raise ValueError('Original pilot is not included in expanded selection')
    comparison={}
    old_rows={row['id']:row for row in old['rows'] if row['selected_for_inference']}
    for row in selected:
        if row['id'] in ids:
            comparison[row['id']]=all(row['conditions'][name]['prediction']==old_rows[row['id']]['conditions'][name]['prediction']
                                      for name in results['protocol']['conditions'])
    diagnostics=[]
    for index,row in enumerate(selected,1):
        ident=row['id']
        reference=json.loads((args.run/'references'/f'{ident}.json').read_text())
        metadata=json.loads((args.run/'traces'/f'{ident}.json').read_text())
        with gzip.open(args.run/'traces'/f'{ident}.scores.jsonl.gz','rt') as stream:
            records=[json.loads(line) for line in stream]
        with gzip.open(args.run/'traces'/f'{ident}.events.jsonl.gz','rt') as stream:
            events=[json.loads(line) for line in stream]
        diagnostics.append(inspect_trace(row,reference,records,events,metadata,config,results['protocol']['primary_event_tolerance_ms']))
        if index%20==0:
            print(f'DECOMPOSE {index}/{len(selected)}',flush=True)
    partitions=partition_summary(results,ids)
    report={'source_run':str(args.run.resolve()),'previous_run':str(args.previous.resolve()),
        'primary_predictions_replaced':False,'timing_diagnostic_cutoff':.9,
        'category_counts':dict(Counter(category for item in diagnostics for category in item['categories'])),
        'diagnostics':diagnostics,'partitions':partitions}
    args.output.mkdir(parents=True)
    shutil.copyfile(Path(__file__),args.output/'analysis-source.py')
    write_json(args.output/'decomposition.json',report)
    write_json(args.output/'partitions.json',partitions)
    write_json(args.output/'repeat-comparison.json',{'same_predicted_values':comparison,'all_identical':all(comparison.values()),
        'count':len(comparison),'neural_and_clock_conditions':results['protocol']['conditions']})
    (args.output/'report.html').write_text(render(report),encoding='utf-8')
    print(json.dumps({'category_counts':report['category_counts'],'repeat_identical':all(comparison.values()),'count':len(diagnostics)},indent=2),flush=True)


if __name__=='__main__':
    main()
