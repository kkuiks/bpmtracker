"""Evaluation-only interpretation and standalone scientific timeline artifacts."""
import argparse
from collections import defaultdict
from pathlib import Path
import json
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiments.variable_clock_exploration_v1.evaluate import reference
from .core import quantize
from .evaluate import aggregate,nearest_error
from .io import read,write,digest


def references_unchanged(run):
    guard=read(run/'evaluation-freeze.json')
    if digest(run/'evaluation-index.json')!=guard['manifest_sha256']:raise ValueError('Evaluation manifest changed')
    for path,value in guard['reference_files'].items():
        if digest(path)!=value:raise ValueError('Accepted reference changed: '+path)


def failure_analysis(run,index,sources,evaluation):
    result=[]
    for row in index:
        if row['role']!='real_variable':continue
        ref=reference(row,sources[row['id']]['duration_seconds']);bank=read(run/'candidate-banks'/f"{row['id']}.json")
        qtrue=np.array(ref['quarters'])
        for k,seg in enumerate(ref['segments']):
            nominal=quantize(seg['quarter_bpm']);record=dict(id=row['original_id'],segment=k,start=seg['start_seconds'],end=seg['end_seconds'],nominal_bpm=nominal,pools={})
            for name,pool in bank['pools'].items():
                matching=[h for h in pool if abs(h['bpm']-nominal)<1e-8]
                phase=[]
                for h in matching:
                    p=60/h['bpm'];values=h['phase']+np.arange(math.ceil((seg['start_seconds']-h['phase'])/p),math.ceil((seg['end_seconds']-h['phase'])/p))*p
                    phase.append(float(np.mean(nearest_error(values,qtrue)<=.07)) if len(values) else 0.)
                record['pools'][name]=dict(nominal_rate_present=bool(matching),best_candidate_grid_fraction_70ms=max(phase,default=0.),
                                           full_phase_candidate=max(phase,default=0.)>=.9)
            record['methods']={}
            for method in ('A_GLOBAL_MATCHED','A_INTERVAL_FIXED','A_RETAINED','A_BROAD_PHASE','A_PHASOR','A_PHASE_REFIT','A_RATE_PHASE_REFIT'):
                scored=next(r for r in evaluation['rows'][method+'/initial_exact'] if r['id']==row['id'])
                record['methods'][method]=scored['score']['segment_rows'][k]
            result.append(record)
    write(run/'primary-real-failure-analysis.json',dict(rows=result,candidate_phase_metrics_are_oracle_diagnostics=True,
          same_candidate_budget=True,phase_fraction_does_not_prove_unique_notation=True))
    return result


def table_line(method,summary):
    return f"| {method} | {100*summary.get('correct_fraction_macro',0):.2f}% | {100*summary.get('wrong_fraction_macro',0):.2f}% | {100*summary.get('unknown_fraction_macro',0):.2f}% | {100*summary.get('ambiguity_fraction_macro',0):.2f}% | {100*summary.get('proposal_oracle_containing_fraction_macro',0):.2f}% |"


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();references_unchanged(a.run)
    evaluation=read(a.run/'frozen-evaluation.json');summaries=evaluation['summaries'];index=read(a.run/'evaluation-index.json')['rows']
    sources={r['id']:r for r in read(a.run/'source-inputs.json')['samples']};protocol=read(a.run/'protocol.json')
    policy=protocol['primary_direction_gate_policy'];global_rows=evaluation['rows']['A_GLOBAL_MATCHED/'+policy];interval_rows=evaluation['rows']['A_INTERVAL_FIXED/'+policy]
    pair=[]
    for row in interval_rows:
        if row['role']=='real_variable':
            before=next(r for r in global_rows if r['id']==row['id'])
            pair.append(dict(id=row['original_id'],global_correct=before['score']['correct_fraction'],interval_correct=row['score']['correct_fraction'],
                             difference=row['score']['correct_fraction']-before['score']['correct_fraction'],wrong=row['score']['wrong_fraction'],
                             initial_scope_overrun_seconds=row['score']['initial_scope_beyond_true_first_segment_seconds']))
    fixed=lambda rows:[r for r in rows if r['scope']=='quarter4' and r['role'] in ('formal_fixed','additional_fixed')]
    gfixed=aggregate(fixed(global_rows));ifixed=aggregate(fixed(interval_rows))
    improvement=float(np.mean([r['difference'] for r in pair]));positive=sum(r['difference']>0 for r in pair)
    fixed_safe=ifixed['wrong_fraction_macro']<=gfixed['wrong_fraction_macro']+1e-10
    passed=improvement>=.05 and positive>=2 and fixed_safe
    gates=dict(primary_policy=policy,actual_human_inputs_collected=False,paired_real=pair,
               improvement_percentage_points=100*improvement,positive_real_sources=positive,
               fixed_global=gfixed,fixed_interval=ifixed,fixed_nonincrease_passed=fixed_safe,
               direction_gate_passed=passed,research_gate_not_product_requirement=True,
               B_C_H4_not_executed=True,source_clocks_are_not_complete_variable_maps=True)
    write(a.run/'decision-gate.json',gates)
    failures=failure_analysis(a.run,index,sources,evaluation)
    write(a.run/'candidate-phase-summary.json',dict(segment_denominator=len(failures),pools={name:dict(
          nominal_rate_present=sum(r['pools'][name]['nominal_rate_present'] for r in failures),
          full_phase_candidate_70ms=sum(r['pools'][name]['full_phase_candidate'] for r in failures))
          for name in ('final','retained','broad_phase','phasor')},oracle_diagnostic_not_automatic_performance=True))
    parents={}
    for key,rows in evaluation['rows'].items():
        groups=defaultdict(list)
        for row in rows:
            if row['role'] in ('new_development','new_prospective'):groups[(row['parent_group'],row['variant'])].append(row)
        parents[key]={parent+'/'+variant:aggregate(values) for (parent,variant),values in groups.items()}
    write(a.run/'constructed-parent-variant-summary.json',parents)
    for k in ('A_GLOBAL_MATCHED','A_INTERVAL_FIXED','A_RETAINED','A_BROAD_PHASE','A_PHASOR','A_PHASE_REFIT','A_RATE_PHASE_REFIT','A_INTERVAL_NO_PERIOD_GUARD'):
        write(a.run/'comparison-summary'/f'{k}.json',summaries[k+'/'+policy])
    # Operating-point curves expose abstention/coverage rather than selecting another final config.
    curves=[]
    cal=read(a.run/'calibration-evaluation.json')
    for name,groups in cal['summaries'].items():
        curves.append(dict(condition=name,groups=groups))
    write(a.run/'risk-coverage.json',dict(calibration_operating_points=curves,frozen_settings_reselected=False))
    figures=a.run/'figures';figures.mkdir(exist_ok=True)
    methods=('A_GLOBAL_MATCHED','A_INTERVAL_FIXED','A_BROAD_PHASE','A_PHASOR','A_RATE_PHASE_REFIT')
    for row in index:
        if row['role']!='real_variable':continue
        ref=reference(row,sources[row['id']]['duration_seconds']);fig,axes=plt.subplots(len(methods)+1,1,figsize=(15,10),sharex=True)
        for seg in ref['segments']:axes[0].plot([seg['start_seconds'],seg['end_seconds']],[seg['quarter_bpm']]*2,color='black',lw=2)
        axes[0].set_ylabel('Reference\nquarter BPM')
        for axis,method in zip(axes[1:],methods):
            prediction=read(a.run/'frozen-predictions'/method/policy/f"{row['id']}.json")
            for e in prediction['episodes']:axis.plot([e['start'],e['end']],[e['bpm']]*2,color='#9ac9df',alpha=.3,lw=2)
            for e in prediction['accepted']:axis.plot([e['start'],e['end']],[e['bpm']]*2,color='#14683d',lw=3)
            scope=prediction.get('initial_information_scope')
            if scope:axis.axvspan(*scope,color='#e0bd46',alpha=.18)
            axis.set_ylabel(method.replace('A_','').replace('_','\n'),fontsize=8)
            axis.set_ylim(35,310);axis.grid(alpha=.2)
        axes[-1].set_xlabel('Original audio seconds');fig.suptitle(row['original_id']+' — assumed initial unit/BPM; episodes are not tempo boundaries')
        fig.tight_layout();fig.savefig(figures/f"{row['original_id']}.png",dpi=160);fig.savefig(figures/f"{row['original_id']}.svg");plt.close(fig)
    lines=['# MCC 후속 A 실험 결과 — 2026-10-08','',
           '시작 부분의 박 단위와 BPM을 사람이 제공했다고 가정한 조건이 주 비교입니다. 실제 사람 입력을 수집한 성능은 아니며, 무입력·단위만 제공한 조건도 별도로 평가했습니다. 입력에는 시작 BPM과 단위만 있으며 박 위치·변경 시점은 없습니다.','',
           '이번 출력은 시계별 지원 구간과 판단 불가/경쟁 후보입니다. 전체 자동 템포 지도나 정확한 변경 시점의 복원은 시험하지 않았습니다.','',
           f"사전 연구 게이트: {'통과' if passed else '미통과'}. 같은 점수의 전역 평가 대비 올바른 지원 시간의 평균 차이는 {100*improvement:+.2f}%p, 개선된 실제 곡은 {positive}/3입니다. 고정 실음악의 잘못된 지원 시간 비증가 조건은 {'충족' if fixed_safe else '미충족'}입니다.",'',
           '| 조건 · 초기 정보 가정 | 올바른 지원 시간 | 잘못된 지원 시간 | 미복원 시간 | 경쟁 후보 시간 | 후보 중 정답 포함 시간 · oracle 진단 |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for method in ('O_FROZEN',)+methods+('A_RETAINED','A_PHASE_REFIT','A_INTERVAL_NO_PERIOD_GUARD'):
        key='O_FROZEN/none' if method=='O_FROZEN' else method+'/'+policy
        lines.append(table_line(method,summaries[key]['real_variable']))
    lines+=['','곡별 차이:']
    for r in pair:lines.append(f"- {r['id']}: 전역 {100*r['global_correct']:.2f}% → 구간 {100*r['interval_correct']:.2f}%, 차이 {100*r['difference']:+.2f}%p. 초기 입력 범위가 참조상 첫 구간 이후까지 남은 시간 {r['initial_scope_overrun_seconds']:.2f}초.")
    lines+=['','입력 가정에 따른 실제 세 곡의 A_INTERVAL_FIXED 비교:']
    for mode,label in [('none','무입력'),('initial_unit','초기 박 단위'),('initial_exact','초기 단위와 BPM')]:
        group=summaries['A_INTERVAL_FIXED/'+mode]['real_variable']
        lines.append(f"- {label}: 올바른 지원 {100*group['correct_fraction_macro']:.2f}%, 잘못된 지원 {100*group['wrong_fraction_macro']:.2f}%, 미복원 {100*group['unknown_fraction_macro']:.2f}%, 경쟁 후보 {100*group['ambiguity_fraction_macro']:.2f}%.")
    lines+=['','고정 실음악은 원래26개 중4/4 범위24개와 별도 Meet Your Maker를 합친25개입니다. 원래26의 분모를 수정하지 않았습니다.',
            f"- 전역 조건: 올바른 지원 {100*gfixed['correct_fraction_macro']:.2f}%, 잘못된 지원 {100*gfixed['wrong_fraction_macro']:.2f}%.",
            f"- 같은 후보의 구간 조건: 올바른 지원 {100*ifixed['correct_fraction_macro']:.2f}%, 잘못된 지원 {100*ifixed['wrong_fraction_macro']:.2f}%.",'',
            '새 구성 음악의 보류 부모 두 개 · 12개 입력:']
    for method in methods:
        group=summaries[method+'/'+policy].get('new_prospective',{})
        lines.append(f"- {method}: 올바른 지원 {100*group.get('correct_fraction_macro',0):.2f}%, 잘못된 지원 {100*group.get('wrong_fraction_macro',0):.2f}%, 미복원 {100*group.get('unknown_fraction_macro',0):.2f}%.")
    lines+=['','원인 구분과 범위:','- 후보 BPM 존재와 올바른 박 위치, 지원 구간, 실제 선택은 별개입니다. `primary-real-failure-analysis.json`에서15개 실제 구간별로 확인할 수 있습니다.',
            '- 파란 선은 경쟁 시계의 제안, 초록 선은 실제 채택한 지원, 노란 영역은 초기 정보의 적용 범위입니다. 선의 끝을 변경 시점으로 읽지 않습니다.',
            '- 24개 새 구성 음악은4개 부모×6조건이며2개 부모는 개발,2개는 보류입니다. 새 실음악 일반화나 음악적 박 단위의 유일성을 증명하지 않습니다.',
            '- 527개 입력 ID는 독립적인527곡이 아닙니다. 원래26, 과거499, reserved98과 formal catalog를 보존했습니다.',
            '- 지원 시간은70ms 박 위치 진단과 명목 BPM 일치를 함께 요구합니다.20/30ms·박/마디 F1, 최대오차와 미매칭은 별도입니다. 제품 합격 기준은 아닙니다.',
            '- 초기 정보는 source-supported 첫 구간에서만 쓰며 관측 박 밀도 변화로도 종료합니다. 끝은 참조 경계가 아니라 추정 범위이므로 첫 구간 초과 적용 시간도 공개합니다.',
            '- 비무음에서 신경망이 일관된 가짜 시계를 내는 경우, 같은 logits만으로 그 오류를 독립적으로 인증할 수 없습니다. PCM 보조 검증은 이 실행의 범위에 포함하지 않았습니다.',
            '- 코드 논리/좌표/실행 검증 통과와 음악 정확도는 별개입니다. B·C·H4나 앱 통합은 진행하지 않았습니다.','']
    for row in index:
        if row['role']=='real_variable':lines.append(f"![{row['original_id']}](figures/{row['original_id']}.png)")
    (a.run/'report.ko.md').write_text('\n'.join(lines)+'\n')
    english=['# Interval consensus A decision gate','',json.dumps(gates,indent=2),'',
             'All methods, assistance policies and scoped cohorts: frozen-evaluation.json. Accepted nominal+phase time, false time and abstention are distinct. Oracle-containing proposals are not automatic performance.']
    (a.run/'report.md').write_text('\n'.join(english)+'\n')
    html=['<!doctype html><meta charset="utf-8"><title>Interval consensus A</title><style>body{max-width:1500px;margin:30px auto;font:16px system-ui}img{width:100%}pre{white-space:pre-wrap}</style>',
          '<h1>Interval consensus A</h1><p>Assumed initial unit/BPM. Green: accepted support; blue: proposals; yellow: initial information scope. Episode endpoints are not tempo changes.</p>']
    for row in index:
        if row['role']=='real_variable':html.append(f'<img src="figures/{row["original_id"]}.png">')
    html.append('<pre>'+json.dumps(gates,indent=2)+'</pre>');(a.run/'overview.html').write_text('\n'.join(html))
    print(json.dumps(gates,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
