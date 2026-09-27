"""Build the current audit from explicit model/path/reference coverage.

Automatic full-source, partial-region and feature-only evidence stay separate.
No method or reference is selected by the resulting scores.
"""
import argparse
from collections import Counter,defaultdict
import csv
import html
import json
from pathlib import Path
import statistics

from inspect_inputs import sha256
from reanalyze_status_paths import read,save
from status_reanalysis_metrics import tempo_rate_diagnostics

TOLERANCES=('10ms','20ms','30ms','70ms')
NAMES={'official':'공식 출력','legacy_dbn':'기존 DBN','legacy_dbn_clock':'기존 DBN + 지도',
 'meter_free_clock':'마디 독립 박 추적 + 지도','clock_candidates_selected':'후보 자동 선택',
 'continuous_refit':'무선호 재피팅','soft_prior_0.5':'BPM 선호 0.5','soft_prior_1.0':'BPM 선호 1',
 'soft_prior_2.0':'BPM 선호 2','phase_after_prior_2':'선호 2 + 위치 보정',
 'bar_fixed':'고정 마디','bar_variable':'가변 마디'}
COHORTS={'babyslakh':'합성 음악','forestry_creator':'Forestry 제작자 3곡','forestry_observed_click':'Forestry 관측 클릭',
 'groove':'GMD 전자드럼','walker':'Walker','ntm_user_reference':'NTM Master',
 'daybreak':'Daybreak','legacy_regression':'과거 회귀 음원'}


def metric_row(item,name,value,metrics,record,scope):
    clock=value.get('clock');prediction=value.get('prediction',[])
    if isinstance(prediction,dict):prediction=prediction['beats_seconds']
    capable=value.get('capabilities',{}).get('tempo_map',scope=='refinement')
    row={'id':item['id'],'cohort':item['cohort'],'group_id':record.get('group_id',item['id']),
      'reference_tier':record.get('reference_tier','none'), 'model':item['model'],'scope':scope,'method':name,
      'evaluation_admission':item['evaluation_admission'],'status':value.get('status'),
      'prediction_count':len(prediction),'tempo_map_supported':capable,'tempo_map_produced':clock is not None,
      'support_start':clock['support_seconds'][0] if clock else None,'support_end':clock['support_seconds'][1] if clock else None,
      'full_tempo_meter_map_validated':False,
      'downbeat_supported':value.get('capabilities',{}).get('downbeat',scope=='core' and name!='clock_candidates_selected')}
    for label in TOLERANCES:
        score=(metrics or {}).get('event_'+label) or {};db=(metrics or {}).get('downbeat_'+label) or {}
        for key in ('precision','recall','f1','true_positives','false_positives','false_negatives'):
            row['beat_'+label+'_'+key]=score.get(key)
        row['downbeat_'+label+'_f1']=db.get('f1')
        errors=score.get('matched_event_errors') or {}
        row['matched_error_'+label+'_p95_ms']=1000*errors['absolute_p95_seconds'] if errors else None
    for label in ('100ms','500ms'):
        change=(metrics or {}).get('tempo_changes_'+label) or {};counts=change.get('full_change_scores') or {}
        row['tempo_'+label+'_status']=change.get('status')
        for key in ('true_positives','false_positives','false_negatives'):
            row['tempo_'+label+'_'+key]=counts.get(key)
    return row


def aggregate(rows):
    groups=defaultdict(list)
    for r in rows:
        if r['evaluation_admission']=='admitted_reference':groups[(r['cohort'],r['model'],r['scope'],r['method'])].append(r)
    out=[]
    for (cohort,model,scope,method),rs in sorted(groups.items()):
        item={'cohort':cohort,'model':model,'scope':scope,'method':method,'track_count':len(rs),
              'distinct_group_count':len({r['group_id'] for r in rs}),
              'empty_predictions':sum(r['prediction_count']==0 for r in rs),
              'tempo_maps_produced':sum(r['tempo_map_produced'] for r in rs),
              'failed_tempo_maps':sum(r['tempo_map_supported'] and not r['tempo_map_produced'] for r in rs),
              'status_counts':dict(Counter(r['status'] for r in rs)),
              'tempo_map_unsupported_tracks':sum(not r['tempo_map_supported'] for r in rs),
              'downbeat_unsupported_tracks':sum(not r.get('downbeat_supported',False) for r in rs)}
        for label in TOLERANCES:
            values=[r['beat_'+label+'_f1'] for r in rs if r['beat_'+label+'_f1'] is not None]
            item['beat_'+label+'_scored_track_count']=len(values)
            item['beat_'+label+'_macro_f1']=statistics.mean(values) if values else None
            by_group=defaultdict(list)
            for r in rs:
                if r['beat_'+label+'_f1'] is not None:by_group[r['group_id']].append(r['beat_'+label+'_f1'])
            item['beat_'+label+'_group_macro_f1']=statistics.mean(statistics.mean(v) for v in by_group.values()) if by_group else None
            values=[r['downbeat_'+label+'_f1'] for r in rs if r['downbeat_'+label+'_f1'] is not None]
            item['downbeat_'+label+'_macro_f1']=statistics.mean(values) if values else None
            item['downbeat_scored_track_count']=len(values)
        for label in ('100ms','500ms'):
            eligible=[r for r in rs if r['tempo_'+label+'_true_positives'] is not None]
            item['tempo_'+label]={'scored_track_count':len(eligible),
               **{key:sum(r['tempo_'+label+'_'+key] for r in eligible) for key in ('true_positives','false_positives','false_negatives')}} if eligible else None
        out.append(item)
    return out


def collect(root,old):
    catalog={r['id']:r for r in read(old/'catalog-scored-audio.json')['tracks']}
    core=read(root/'core-paths/manifest.json');refinement=read(root/'refinements/manifest.json')
    if not core['complete'] or not refinement['complete']:raise ValueError('core/refinement incomplete')
    rows=[];rate_rows=[];bar_rows=[];runtime=[]
    for item in core['rows']:
        if item['status']!='predictions_saved':continue
        value=read(item['prediction_path']);scores=read(item['score_path'])['scores'];record=catalog.get(item['id'],{})
        ref=read(record['reference']['path']) if item['evaluation_admission']=='admitted_reference' else None
        runtime.append({'id':item['id'],'model':item['model'],**value['execution'], 'source_cache':value['cache']})
        for name,method in value['methods'].items():
            rows.append(metric_row(item,name,method,(scores or {}).get(name),record,'core'))
            if method['capabilities']['tempo_map']:
                rate_rows.append({'id':item['id'],'cohort':item['cohort'],'model':item['model'],'method':name,
                  'evaluation_admission':item['evaluation_admission'],
                  'diagnostics':tempo_rate_diagnostics(ref,method.get('clock')) if ref else None})
    for item in refinement['rows']:
        value=read(item['prediction_path']);scores=read(item['score_path']) if item.get('score_path') else None
        record=catalog.get(item['id'],{})
        runtime.append({'id':item['id'],'model':item['model'],'refinement_elapsed_seconds':value['elapsed_seconds'],
                        'prediction_reused':item['prediction_reused'],'attack_provenance':value['attack_provenance'],
                        'memory_process_high_water_rss_bytes':value['memory_process_high_water_rss_bytes']})
        for name,method in value['methods'].items():
            metrics=(scores or {}).get('methods',{}).get(name)
            rows.append(metric_row(item,name,method,metrics,record,'refinement'))
            rate_rows.append({'id':item['id'],'cohort':item['cohort'],'model':item['model'],'method':name,
                 'evaluation_admission':item['evaluation_admission'],'diagnostics':(metrics or {}).get('rate_diagnostics')})
        for name,bars in value['bars'].items():
            bar_rows.append({'id':item['id'],'cohort':item['cohort'],'model':item['model'],'method':name,
                 'evaluation_admission':item['evaluation_admission'],'status':bars['status'],
                 'scores':(scores or {}).get('bars',{}).get(name),'full_meter_map_supported':False})
    return rows,rate_rows,bar_rows,runtime


def region_results(root):
    manifest=read(root/'region-paths/manifest.json')
    if not manifest['complete']:raise ValueError('regions incomplete')
    rows=[]
    for item in manifest['rows']:
        if item['status']!='predictions_saved':continue
        score=read(item['score_path']);metrics=score['scores']
        selected=metrics['selected'] if metrics else None
        rows.append({'id':item['id'],'cohort':item['cohort'],'model':item['model'],
          'evaluation_admission':item['evaluation_admission'],'full_song_map':False,
          'metrics':selected,'oracle_diagnostics':metrics.get('oracle_diagnostics') if metrics else None})
    groups=defaultdict(list)
    for row in rows:
        if row['evaluation_admission']=='admitted_reference':groups[(row['cohort'],row['model'])].append(row)
    summary=[]
    for (cohort,model),rs in sorted(groups.items()):
        entry={'cohort':cohort,'model':model,'track_count':len(rs),'full_song_map':False}
        for scope in ('whole_annotation_diagnostic','within_proposed_region_diagnostic'):
            scored=[r['metrics'][scope] for r in rs if r['metrics'] and r['metrics'].get(scope)]
            entry[scope]={'scored_track_count':len(scored), **{'f1_'+tol:statistics.mean(m['event_'+tol]['f1'] for m in scored) if scored else None for tol in TOLERANCES}}
        summary.append(entry)
    return {'coverage':manifest['state_counts'],'cohort_results':summary,'rows':rows}


def bar_results(rows):
    groups=defaultdict(list)
    for r in rows:
        if r['evaluation_admission']=='admitted_reference':groups[(r['cohort'],r['model'],r['method'])].append(r)
    summary=[]
    for (cohort,model,method),rs in sorted(groups.items()):
        item={'cohort':cohort,'model':model,'method':method,'track_count':len(rs),
              'full_meter_map_supported':False,'scope':'change time and NEW numerator under quarter-pulse hypothesis'}
        for tol in TOLERANCES:
            values=[r['scores']['downbeat_scores'][tol]['f1'] for r in rs if r['scores']['downbeat_scores'][tol] is not None]
            item['downbeat_'+tol+'_macro_f1']=statistics.mean(values) if values else None
            item['downbeat_scored_tracks']=len(values)
        for tol in ('100ms','500ms'):
            values=[r['scores']['meter_change_'+tol+'_quarter_hypothesis'] for r in rs if r['scores']['meter_change_'+tol+'_quarter_hypothesis'] is not None]
            item['meter_change_'+tol]={'scored_track_count':len(values),**{k:sum(v[k] for v in values) for k in ['reference_change_count','predicted_change_count','matched_count']}}
        item['unsupported_reference_signatures']=sorted({tuple(s) for r in rs for s in r['scores']['unsupported_reference_signatures']})
        summary.append(item)
    return summary


def csv_save(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def percent(v):return '평가 불가' if v is None else f'{100*v:.2f}%'


def markdown(summary):
    lines=['# 현재 기술·표본·성능 재분석','',
      '이 문서는 현재 상태와 근거를 정리한다. 다음 개발 방향이나 알고리즘 개선 우선순위는 정하지 않는다.','',
      '## 결과를 읽는 핵심','',
      '- 박 위치가 맞는 것, 올바른 BPM 단위로 세는 것, 정확한 변경점과 마디를 복원하는 것은 서로 다른 능력이다.',
      '- 현재 비교한 경로는 모두 실험이다. 사람의 선택·교정 없이 완전한 전곡 템포·박자 지도를 만들었다는 검증은 없다.',
      '- 기존 모델·디코더·피팅·후처리 설정을 유지했다. 바뀐 것은 평가 오류와 비교 연결·보고 방식이다.',
      '- 참조 38개는 이번 정책에서 평가에 채택한 자료이다. 모두 음악적으로 독립 검증된 정답이라는 뜻이 아니다.',
      '- 아래 점수는 곡별 F1의 평균이다. 곡 전체 성공률이나 제품 완성도가 아니다.','',
      '## 실제 평가 범위','',
      f"- 원본 음원52개: Beat This 전부, Beat Transformer는 기존9개. 모델-음원61쌍에 기존 경로를 적용했다.",
      '- BabySlakh09·12·20은 사용자 판단에 따라 정확도 집계에서 제외했다. Daybreak3·과거8은 정답 정렬 미확인으로 예측만 남겼다.',
      '- 주 정확도 표는38개 참조, 두 모델 직접 비교는 같은9개에 한정한다. 마디 독립·후보·선호도·위치·별도 마디·부분 구간 경로는61개 모델-음원 조합을 처리했다.',
      '- 기존 DBN 및 DBN 지도 대조군은 종전 Beat This41개 결과를 재사용했다. 정답 없는11개와 Beat Transformer에는 그 대조군을 새 조합으로 추가하지 않았다.',
      '- GTZAN은 음원 없는 특징·수작업 박 라벨 보조 평가다. 부분 구간과 정답을 이용한 최선 후보 선택은 별도 진단이다.',
      '- 원본·승인지도·과거 결과는 보존하고 새 결과는 이 재분석 디렉터리에 저장했다.','',
      '## Beat This: 같은 자료에서 처리 경로 비교','',
      '| 집단 | 방법 | 곡 수 | 박20ms | 박70ms | 지도 생성 실패 |',
      '|---|---|---:|---:|---:|---:|']
    shown=('official','legacy_dbn_clock','meter_free_clock','clock_candidates_selected','soft_prior_0.5','soft_prior_1.0','soft_prior_2.0','phase_after_prior_2')
    for r in summary['cohort_results']:
        if r['model']=='beat_this' and r['method'] in shown:
            lines.append(f"| {COHORTS.get(r['cohort'],r['cohort'])} | {NAMES.get(r['method'],r['method'])} | {r['track_count']} | {percent(r['beat_20ms_macro_f1'])} | {percent(r['beat_70ms_macro_f1'])} | {r['failed_tempo_maps'] if r['method']!='official' else '미지원'} |")
    lines += ['', '같은 아티스트의 Forestry 자료와 같은 연주자의 GMD 반복을 독립 아티스트로 세지 않는다. JSON에는 곡 평균과 그룹 평균을 함께 보존했다. 위상 보정은 강도2 결과에서만 적용한 기존 경로다.','',
      '## NTM 곡별 결과','', '| 곡 | 방법 | 박20ms | 지도 생성 |', '|---|---|---:|---|']
    for r in summary['ntm_rows']:
        if r['method'] in shown:
            lines.append(f"| {r['id'].removeprefix('ntm_')} | {NAMES.get(r['method'],r['method'])} | {percent(r['beat_20ms_f1'])} | {'생성' if r['tempo_map_produced'] else '실패' if r['tempo_map_supported'] else '기능 없음'} |")
    lines += ['', '## 템포 변경 집계','',
      '변경 위치100ms 또는500ms와 전후BPM 각각0.1 이내를 동시에 요구한다. 기능이 있는 경로의 지도 생성 실패는 참조 변경을 모두 누락으로 센다. 원래 지도를 만들지 않는 공식 박 출력은 미지원이다.','',
      '| 집단 | 모델 | 방법 | 100ms 맞음/거짓/누락 | 500ms 맞음/거짓/누락 |', '|---|---|---|---:|---:|']
    for r in summary['cohort_results']:
        if r['method'] not in shown or r['tempo_100ms'] is None:continue
        def counts(label):
            s=r['tempo_'+label];return '/'.join(str(s[k]) for k in ('true_positives','false_positives','false_negatives'))
        lines.append(f"| {COHORTS.get(r['cohort'],r['cohort'])} | {r['model']} | {NAMES.get(r['method'],r['method'])} | {counts('100ms')} | {counts('500ms')} |")
    lines += ['', '## 박자와 전곡 출력의 한계','',
       '후보 선택 경로는 다운비트를 출력하지 않으므로 미지원으로 표시했다. 별도의 고정·가변 마디 실험은 입력 박을2·3·4개씩 묶는다. 4분음표 단위와 분모를 자동 확정한 박자 지도가 아니다. 별도 마디 점수도 이 가정을 명시한 진단이며, 변경 시점과 변경 후 분자만 대응시킨다. 변경 전후 박자 쌍 전체를 인증하는 지표는 아니다.',
       '지도 지원 구간과 전곡 길이를 구분했고, 정답과 예측의 음악적 박 번호 원점이 확인되지 않아 누적 드리프트를 임의 대응시켜 계산하지 않았다. rate-diagnostics.json의 반속도·배속과 BPM오차는 참조4분음표 대비 해석 진단이다.', '',
       '## 정정한 내용','',
       '1. 기존 DBN 지도와 마디 독립 박 추적 지도를 다른 방법으로 명명했다.',
       '2. 지도 생성 실패를 템포 변경 분모에서 빼던 집계를 수정했다.',
       '3. 미지원 다운비트와 실제 오예측을 구분했다.',
       '4. 38개를 채택 참조로 표기했다. 실제 평가 구간 안의 변경 포함 표본은 템포10개·박자8개다.',
       '5. 같은 박자 재선언은 변박으로 세지 않는다. 참조의 마디 재시작 정보 자체는 보존한다.',
       '6. 두 번째 모델의 누락은 공통 전처리 장애에 따른 미확보로 표시하고, 개별 실행 충돌과 구분했다.', '',
       '## 참조 불확실성과 보존','',
       'NTM은 정확한 사용자 승인지도와의 일치도다. 원본 기록 클릭으로 검증된 밀리초 절대 정확도로 확대하지 않는다. GTZAN의 중복 특징·다른 박 라벨은 임의 수정하지 않고, 충돌 집단 제외 민감도 결과를 별도 보존했다.',
       '참조별 평가 항목·지원 시간·미확인 사항은 reference-review/qualified-v2/references.json, 실제 파일 조사·디코딩 결과는 reference-review/qualified-v2/corpus-assets.json에 있다.','',
       '## 실행 및 산출물','',
       '- per-track-method.csv: 모든 원본 음원의 실행된 방법별 출력 상태와 평가. 참조가 없는 결과는 점수 공란.',
       '- summary.json: 집단별·동일9개 모델 비교와 실행 범위.',
       '- rate-diagnostics.json / bar-diagnostics.json: BPM단위·지원구간·별도 마디 실험 상세.',
       '- runtime.json: 이번 후처리 실행과 과거 모델 실행 기록을 구분. RSS는 프로세스 누적 최고치여서 곡별 독립 메모리 측정이 아니다.',
       '- core-paths, refinements, region-paths, gtzan-paths: 예측과 점수 원본.',
       '- preservation-before.json 및 validation.json: 기존 데이터·알고리즘 보존과 검증 기록.', '',
       '## 목표 대비 판단','',
       '박 추적·지도 피팅·후보 선택·선택적 보정의 구현과 실제 개선/악화 사례는 확인된다. 그러나 박 단위 오류·거짓 변경·빈 지도·변박 및 음악적 원점 문제가 남아 있다. 무교정 전곡 성공률을 제시할 근거는 아직 없다.']
    extra=['## 이번 재분석으로 구분된 실패 원인','',
       '- State Champs: 승인170BPM에 가까운 후보가 존재하며 박20ms F1은98.50%다. 자동 선택은85BPM 후보를 골라50.43%가 됐다. 이98.50%는 정답을 보고 고른 원인 진단값이며 자동 성능이 아니다.',
       '- Archspire: 현재 지도 피팅은 계산 복잡도 제한으로 대체 출력에 머물고, 전곡·부분 구간 후보 모두 비어 있다. 참조 템포 변경2개는 누락으로 포함했다.',
       '- SWS와 Kami: 후보 선택의 박20ms F1은91.03%,95.89%로 개선됐지만 거짓 템포 구간과 앞뒤 미지원 범위가 남는다.',
       '- NTM 가변 마디 진단은 참조 변경6개 중500ms 내 일치0개, 제안72개다. 다운비트 점수와 완전한 박자 지도 복원을 구분해야 한다.','',
       '## GTZAN 보조 평가와 참조 민감도','',
       '| 방법 | 박20ms | 박70ms | 평가 수 | 빈 출력 |','|---|---:|---:|---:|---:|']
    for name,r in summary['gtzan']['summary']['methods'].items():
        extra.append(f"| {NAMES.get(name,name)} | {percent(r['beat_macro_f1']['20ms'])} | {percent(r['beat_macro_f1']['70ms'])} | {r['scored_tracks']} | {r['empty_prediction_tracks']} |")
    extra += ['', '14개 특징 중복쌍 중11개는 박 개수·위치·마디 라벨의 의미 있는 충돌이 있었다. 어느 정답도 모델 점수에 맞춰 바꾸지 않았다. 충돌 집단을 제외한974개에서 공식 박20ms F1은63.95%, 원래985개에서는64.06%다. 개별 사례의 큰 불확실성과 전체 평균의 작은 변화를 함께 보존한다.','',
       '## 부분 구간·과거 실험','',
       '부분 구간 후보는 Beat This51/52, Beat Transformer9/9에서 생성됐다. 구간 안의 점수와 전체 참조에 대한 누락 포함 점수를 분리했다. 부분 지도를 이어 붙인 전곡 결과로 집계하지 않았다.',
       '과거 실험 재채점은 채택894방법-사례와 제외 참조45진단 사례를 보존한다. 선호도·위치·부분 구간·Light 자동/보조/참조 지도·정답박 입력의 짧은 변경 실험을 섞지 않았다. 비교 가능한 과거F1 1,826개가 일치했다.', '',
       '연구 과정은 기존 신경망 기준선 재현, 박/마디 분리, 연속 지도·다중 후보, 짧은 변경 통제, Light 전곡 연결, BPM선호도·위치 보정, 다양한 표본 확보와 참조 검증 순서로 이어졌다. 각 단계의 개선·회귀·보류 이유와 별개로, 이번 작업은 그 결과의 평가와 적용 범위를 다시 확인한 것이다.','']
    # Keep detailed tables for review while placing the final judgement last.
    index=lines.index('## 목표 대비 판단')
    lines[index:index]=extra
    return '\n'.join(lines)+'\n' 


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--old-root',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();rows,rates,bars,runtime=collect(args.root,args.old_root)
    if args.output_dir.exists():p.error('output must be new')
    args.output_dir.mkdir(parents=True)
    regions=region_results(args.root)
    gtzan=read(args.root/'gtzan-paths/report.json')
    if not gtzan['complete']:raise ValueError('GTZAN replay incomplete')
    core=read(args.root/'core-paths/manifest.json')
    conflicts=read(args.root/'reference-review/qualified-v2/gtzan-annotation-conflicts.json')
    sensitivities={}
    for label,ids in [('exclude_conflicting_clusters',conflicts['conflicting_retained_ids']),('exclude_all_nonidentical_clusters',conflicts['all_nonidentical_retained_ids'])]:
        retained=[r for r in gtzan['tracks'] if r['id'] not in ids]
        sensitivities[label]={'track_count':len(retained),'excluded_ids':ids,'methods':{
            method:{'f1_'+tol:statistics.mean(r['methods'][method]['metrics']['event_'+tol]['f1'] for r in retained) for tol in TOLERANCES}
            for method in gtzan['summary']['methods']}}
    new_inference=[]
    for path in sorted((args.root/'legacy-new-inference').glob('*/beat-this/result.json')):
        result=read(path);new_inference.append({'id':path.parent.parent.name,'path':str(path),'sha256':sha256(path),
          'timing_seconds':result['timing_seconds'],'gpu_memory':result['gpu_memory'],'model':result['model']})
    paired={r['id'] for r in rows if r['model']=='beat_transformer' and r['evaluation_admission']=='admitted_reference'}
    summary={'schema_version':1,'scope':'current_evidence_no_improvement_priority','cohort_results':aggregate(rows),
       'paired_model_comparison':{'track_count':len(paired),'ids':sorted(paired),'cohort_results':aggregate([r for r in rows if r['id'] in paired])},
       'ntm_rows':[r for r in rows if r['cohort']=='ntm_user_reference'],
       'model_coverage':core['state_counts'],'reference_review':{'path':str(args.root/'reference-review/qualified-v2/manifest.json'),'sha256':sha256(args.root/'reference-review/qualified-v2/manifest.json')},
       'bar_summary':bar_results(bars),'partial_regions':{k:v for k,v in regions.items() if k!='rows'},
       'gtzan':{'summary':gtzan['summary'],'path':str(args.root/'gtzan-paths/report.json'),'sha256':sha256(args.root/'gtzan-paths/report.json')},
       'gtzan_new_path_reference_sensitivity':sensitivities,
       'execution_accounting':{'new_acoustic_inference':new_inference,'new_inference_count':len(new_inference),'reused_acoustic_cache_count':61-len(new_inference),
            'core_postprocessing_seconds':sum(r.get('postprocessing_elapsed_seconds',0) for r in runtime),
            'refinement_prediction_seconds_recorded':sum(r.get('refinement_elapsed_seconds',0) for r in runtime),
            'wall_clock_warning':'stage sums are not end-to-end latency; caches reused, stages can overlap, RSS is process cumulative high-water'},
       'gtzan_reference_sensitivity':read(args.root/'reference-review/qualified-v2/gtzan-annotation-conflicts.json'),
       'historical_rescore':{'path':str(args.root/'historical-rescore/report.json'),'sha256':sha256(args.root/'historical-rescore/report.json'),'summary':read(args.root/'historical-rescore/report.json')['summary']},
       'candidate_selection_diagnostic':{'path':str(args.root/'core-paths/candidate-selection-diagnostic.json'),'sha256':sha256(args.root/'core-paths/candidate-selection-diagnostic.json'),'diagnostic_only':True,'groups':read(args.root/'core-paths/candidate-selection-diagnostic.json')['groups']},
       'row_count':len(rows),'distinct_audio_count':len({r['id'] for r in rows}),
       'scored_audio_count':len({r['id'] for r in rows if r['evaluation_admission']=='admitted_reference'}),
       'sources':{n:{'path':str(args.root/n),'sha256':sha256(args.root/n)} for n in
          ['core-paths/manifest.json','refinements/manifest.json','region-paths/manifest.json','gtzan-paths/report.json','historical-rescore/report.json','corrected-existing-v1/summary.json']},
       'full_tempo_meter_contract':'not_established','default_promoted':False}
    csv_save(args.output_dir/'per-track-method.csv',rows)
    csv_save(args.output_dir/'model-coverage.csv',[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in core['rows']])
    save(args.output_dir/'summary.json',summary);save(args.output_dir/'rate-diagnostics.json',rates)
    save(args.output_dir/'bar-diagnostics.json',bars);save(args.output_dir/'runtime.json',runtime)
    save(args.output_dir/'region-diagnostics.json',regions)
    text=markdown(summary);(args.output_dir/'STATUS.md').write_text(text)
    (args.output_dir/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Joljak 현황 재분석</title><style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:16px/1.6 system-ui}pre{white-space:pre-wrap}</style><pre>'+html.escape(text)+'</pre>')
    print(json.dumps({'rows':len(rows),'scored_audio':summary['scored_audio_count'],'output':str(args.output_dir)}))

if __name__=='__main__':main()
