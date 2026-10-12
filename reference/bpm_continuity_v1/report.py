"""Korean scientific report, ten timelines and a small reproducibility bundle."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .common import ARMS,POLICIES,read,write,frozen_guard,digest
from .evaluate import arrays


def pct(value): return f'{value*100:.2f}%'


def timeline(run,row):
    ref=read(row['reference_path']);duration=row['duration_seconds']
    figure,axes=plt.subplots(6,1,figsize=(13,10),sharex=True,gridspec_kw={'height_ratios':[1,1,1,1,1,1.1]})
    for s in ref['segments']:axes[0].hlines(s['quarter_bpm'],s['start_seconds'],s['end_seconds'],color='black',linewidth=2)
    axes[0].set_ylabel('Reference BPM')
    for axis,arm,color in zip(axes[1:5],['C0_LEGACY_A',*ARMS],['#777777','#8046b0','#248b5b','#bd7a17']):
        path=(run/'legacy-predictions/initial_exact' if arm=='C0_LEGACY_A' else run/'predictions'/arm/'oracle_start')/f"{row['id']}.json"
        if path.exists():
            pred=read(path)
            for r in pred['accepted']:axis.hlines(r['bpm'],r['start'],r['end'],color=color,linewidth=2)
            for s in pred.get('spans',[]):
                if s['status']!='ACCEPTED':axis.axvspan(s['start'],s['end'],color='#d6d6d6',alpha=.55 if s['status']=='UNKNOWN' else .9)
            if arm=='C2_CONTINUITY':
                trace_path=run/'decision-traces'/arm/'oracle_start'/f"{row['id']}.jsonl.gz"
                with gzip.open(trace_path,'rt') as stream:trace=[json.loads(line) for line in stream]
                axis.plot([t['t'] for t in trace],[t['remembered']['bpm'] if t['remembered'] else np.nan for t in trace],
                          color='#315b75',linestyle='--',linewidth=.7,label='remembered clock (not output)')
                axis.legend(loc='upper right',fontsize=7)
            if arm in ('C1_STATELESS','C2_CONTINUITY'):
                t,support,truth,rate,error,labels=arrays(pred,ref,duration)
                error=np.where(np.isfinite(rate)&support,np.minimum(error*1000,200),np.nan)
                axes[5].plot(t,error,color=color,linewidth=.65,label=arm)
        else:axis.text(.02,.5,'UNAVAILABLE',transform=axis.transAxes)
        axis.set_ylabel(arm.replace('_','\n'),fontsize=8)
    axes[5].axhline(70,color='black',linestyle=':',linewidth=.8)
    axes[5].set_ylabel('Grid phase\nerror (ms)');axes[5].set_ylim(0,205);axes[5].legend(fontsize=7)
    axes[5].set_xlabel('Audio-relative seconds')
    for axis in axes:
        axis.set_xlim(0,duration);axis.grid(alpha=.15)
        for transition in ref['transitions']:axis.axvline(transition['time'],color='black',linestyle=':',linewidth=.6)
    figure.suptitle(f"{row['title']} — oracle_start; gray = no output; dashed = memory")
    figure.tight_layout();(run/'figures').mkdir(exist_ok=True)
    for suffix in ['png','svg']:figure.savefig(run/'figures'/f"{row['id']}.{suffix}",dpi=145)
    plt.close(figure)


def case_analysis(run,row,metrics):
    ident=row['id'];c1=read(run/'predictions/C1_STATELESS/oracle_start'/f'{ident}.json')
    c2=read(run/'predictions/C2_CONTINUITY/oracle_start'/f'{ident}.json')
    ref=read(row['reference_path']);truth=ref['initial_bpm']
    wrong=[r for r in c1['accepted'] if r['bpm']!=truth]
    wrong.sort(key=lambda r:r['end']-r['start'],reverse=True)
    events=[]
    for region in wrong[:3]:
        middle=(region['start']+region['end'])/2;step=np.floor(middle/.25)*.25
        path=run/'decision-traces/C2_CONTINUITY/oracle_start'/f'{ident}.jsonl.gz'
        with gzip.open(path,'rt') as stream:
            trace=next((json.loads(line) for line in stream if abs(json.loads(line)['t']-step)<1e-8),None)
        events.append({'C1_wrong_span':region,'C2_trace_at_middle':trace})
    return {'id':ident,'title':row['title'],'longest_C1_wrong_spans':events,
            'C2_changes':c2['changes'],'clock_output_and_memory_kept_separate':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();run=args.run.resolve();frozen_guard(run)
    metrics=read(run/'metrics.json');result=read(run/'run-result.json');audit=read(run/'source-isolation-audit.json')
    manifest=read(run/'evaluation-manifest.json')['samples'];agg=metrics['aggregates']
    primary=result['gates'][0];c1=agg['C1_STATELESS/oracle_start/fixed']['macro'];c2=agg['C2_CONTINUITY/oracle_start/fixed']['macro']
    gain=(c2['correct_clock_70ms']-c1['correct_clock_70ms'])*100
    change='늘렸습니다' if gain>=0 else '줄였습니다'
    lines=[f"올바른 시작 BPM을 알려준 조건에서 상태 유지 방식은 고정곡의 맞는 시계 시간을 {abs(gain):.2f}%p {change}. 사전 고정곡 판정은 **{primary['fixed_status']}**, 실제 변속 판정은 **{primary['variable_status']}**입니다.",
           '',f"최종 판정: **{result['conclusion']} / PROXY_COMPLETE**. 실제 사람의 탭은 수집하지 않았습니다.",
           '', '## 무엇을 비교했는가',
           '', 'C0는 기존 interval-consensus A의 보관된 출력을 최신 승인 reference로 다시 채점한 결과입니다. C1과 C2는 같은 source bank, 초기 seed, 국소 근거와 renderer를 공유합니다. C2는 현재 clock을 유지하고 변경에 추가 근거를 요구합니다. C_HOLD는 같은 phase 재설정을 허용하되 시작 BPM을 고정하는 보조 비교군입니다.',
           '', '정확한 시작 BPM은 정답에서 공급하는 명시적 진단 조건입니다. ±5% 조건은 숫자를 단위 power로 한 번 변환한 정답 기반 모의 입력입니다. 숫자로 BPM을 맞추거나 phase를 정하지 않았습니다. 이 실험은 오프라인 추론이며 제품의 자동 변속 분석이나 실시간 지연 검증이 아닙니다.',
           '', '## 고정곡 8개: 정확한 시작 BPM', '',
           '| 방식 | 맞는 시계 @70ms | 잘못된 BPM | phase만 틀림 | UNKNOWN | AMBIGUOUS | quarter F1@70ms | @20ms | @30ms |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm,policy in [('C0_LEGACY_A','initial_exact')]+[(a,'oracle_start') for a in ARMS]:
        a=agg[f'{arm}/{policy}/fixed']['macro']
        lines.append('| '+arm+' | '+' | '.join(pct(a[k]) for k in ['correct_clock_70ms','wrong_rate','wrong_phase_only','unknown','ambiguous','quarter_f1_70ms','correct_clock_20ms','correct_clock_30ms'])+' |')
    by={(r['id'],r['arm'],r['policy']):r['score'] for r in metrics['rows']}
    lines += ['', '위 값은 각 곡에 같은 비중을 주는 macro입니다. 시간 가중 micro와 각 범주의 초는 metrics.json/CSV에 있습니다. 시계 시간 점수는 출력 구간의 BPM과 가상 격자의 정합을 평가하며, 실제 출력한 클릭 개수는 별도의 event F1로 확인합니다.',
              '', '| 곡 | C0 맞는 시계 | C1 맞는 시계 | C2 맞는 시계 | C2 잘못된 BPM | C2 UNKNOWN+AMBIGUOUS |',
              '|---|---:|---:|---:|---:|---:|']
    for row in manifest:
        if row['role']!='fixed':continue
        ident=row['id'];old=by[(ident,'C0_LEGACY_A','initial_exact')];a=by[(ident,'C1_STATELESS','oracle_start')];b=by[(ident,'C2_CONTINUITY','oracle_start')]
        values=[old['fractions']['correct_clock_70ms'],a['fractions']['correct_clock_70ms'],b['fractions']['correct_clock_70ms'],
                b['fractions']['wrong_rate'],b['fractions']['unknown']+b['fractions']['ambiguous']]
        lines.append('| '+row['title']+' | '+' | '.join(pct(v) for v in values)+' |')
    lines += ['', '## 모의 입력: 정답의 95%, 100%, 105%', '',
              '| 조건 | C1 맞는 시계 | C2 맞는 시계 | C2 ±1% BPM | C2 quarter F1@70ms |',
              '|---|---:|---:|---:|---:|']
    for policy in POLICIES[1:]:
        a=agg[f'C1_STATELESS/{policy}/fixed']['macro'];b=agg[f'C2_CONTINUITY/{policy}/fixed']['macro']
        lines.append(f"| {policy} | {pct(a['correct_clock_70ms'])} | {pct(b['correct_clock_70ms'])} | {pct(b['rate_within_1_percent'])} | {pct(b['quarter_f1_70ms'])} |")
    lines += ['',f"同一 power 조건의 예측·trace 동일성은 {len(audit['same_unit_checks'])}쌍에서 확인했으며, 결과는 {'PASS' if all(x['identical'] for x in audit['same_unit_checks']) else 'FAIL'}입니다.",
              '이 결과는 정답 단위 근처의 숫자 오차에 대한 진단입니다. 사람이 half/double 단위를 선택하거나 박을 찾지 못하는 경우를 측정한 결과는 아닙니다.',
              '', '| 곡 | audio-only 기준 BPM | oracle seed | 모의 입력 seed | 모의 입력 power (−5/0/+5%) |',
              '|---|---:|---:|---:|---|']
    for row in manifest:
        ident=row['id'];base=read(run/'source-bootstrap'/f'{ident}.json')['audio_base_bpm']
        boots={p:read(run/'bootstrap'/p/f'{ident}.json') for p in POLICIES}
        def seed(p):return str(boots[p]['seed']['clock']['bpm']) if boots[p]['seed'] else 'NO_SEED'
        powers=[read(run/'initial-inputs/encoded'/f'{ident}.json')[p].get('power') for p in POLICIES[1:]]
        lines.append(f"| {row['title']} | {base} | {seed('oracle_start')} | {seed('proxy_unit_zero')} | {powers} |")
    held=agg['C_HOLD/oracle_start/fixed']['macro']
    lines += ['', '## 유지 정책과 BPM 변경 규칙의 효과', '',
              f"BPM 고정 비교군의 맞는 시계 시간은 {pct(held['correct_clock_70ms'])}, C2는 {pct(c2['correct_clock_70ms'])}입니다. 두 방식이 같은 출력을 낸 곡에서는 그 개선을 변속 검출기의 성과로 해석하지 않습니다.",
              'C2는 직접적인 octave 전환을 금지하는 규칙도 포함하므로, C1 대비 결과는 기억 하나의 효과가 아니라 유지·변경 정책 묶음의 효과입니다.',
              '', '## 실제 변속 두 곡', '',
              '| 곡 | C1 맞는 시계 | C2 맞는 시계 | C2 전환 성공 / 전체 | 시작 상태 |',
              '|---|---:|---:|---:|---|']
    for row in manifest:
        if row['role']!='variable':continue
        ident=row['id'];a=by[(ident,'C1_STATELESS','oracle_start')];b=by[(ident,'C2_CONTINUITY','oracle_start')]
        transitions=b['transitions'];successful=sum(x['successful_transition'] for x in transitions)
        lines.append(f"| {row['title']} | {pct(a['fractions']['correct_clock_70ms'])} | {pct(b['fractions']['correct_clock_70ms'])} | {successful}/{len(transitions)} | {b['status']} |")
        for tr in transitions:
            lines.append(f"- {tr['time']:.6f}s: {tr['left_bpm']}→{tr['right_bpm']}; 前8quarter={tr['old_last_8_correct']}, 後8quarter={tr['recovered_after']}, delay={tr['adaptation_delay']}, reason={tr['failure_or_recovery_reason']}.")
    lines += ['', 'Opeth final bank에는 시작 145와 139·130 BPM이 없고, Underoath의 새 final bank에도 175 BPM이 없습니다. 후보를 곡별로 보충하지 않았고 누락된 구간과 전환을 분모에서 제외하지 않았습니다. 이 제약 때문에 실제 변속 안전성이 확인되지 않았으면 고정곡 개선만으로 RESEARCH_GO를 주장하지 않습니다.',
              '', '## 판정 기준별 결과', '', '| 조건 | 기준 | 판정 |', '|---|---|---|']
    for gate in result['gates']:
        for c in gate['fixed_checks']+gate['variable_checks']:
            lines.append(f"| {gate['policy']} | {c['name']} | {c['status']} |")
    analyses=[case_analysis(run,row,metrics) for row in manifest if row['id'] in ['src0106','src0095','src0097','src0499']]
    write(run/'case-analysis.json',{'rows':analyses})
    lines += ['', '## 주요 실패 구간의 실제 근거', '']
    for analysis in analyses:
        lines.append('### '+analysis['title'])
        for event in analysis['longest_C1_wrong_spans']:
            span=event['C1_wrong_span'];trace=event['C2_trace_at_middle'];remembered=trace.get('remembered') if trace else None
            lines.append(f"- C1 {span['start']:.2f}–{span['end']:.2f}s: {span['bpm']} BPM. C2 중간 시각 상태={trace['status'] if trace else None}, reason={trace['reason'] if trace else None}; 기억 clock={remembered['bpm'] if remembered else None}, G={remembered['G'] if remembered else None}, primary count={remembered['primary_count'] if remembered else None}, S={remembered['S'] if remembered else None}.")
        if not analysis['longest_C1_wrong_spans']:lines.append('- C1의 잘못된 BPM 출력 구간 없음.')
        lines.append('')
    lines += ['## 구현·실행 확인과 한계', '',
              f"논리 controls: {sum(r['passed'] for r in read(run/'controls.json')['rows'])}/{len(read(run/'controls.json')['rows'])}. 서로 다른 dummy reference와 worker 수에 대한 byte 비교: {len(audit['checks'])}개, forbidden read={audit['forbidden_reads']}, {'PASS' if audit['passed'] else 'FAIL'}.",
              'drift는 실제 source event와 후보의 quarter index를 사용해 unwrap합니다. 원래 principal unwrap의 큰 변속 방향 반전은 논리 fixture에서 드러났고 수정된 방식으로 160→240 대응을 확인했습니다. 이는 후보의 quarter 해석에 조건부인 계산이며, 리듬 변화와 실제 템포를 보편적으로 구별하는 독립 센서는 아닙니다.',
              '6초 창은 낮은 BPM에서 8개의 primary match를 확보하지 못하며 작은 1% 변속도 최소 drift 기준을 만족하기 어려울 수 있습니다. 이 실험은 모든 30–400 BPM 또는 모든 변속을 검증하지 않았습니다.',
              '기존 cache는 동일한 bytes와 geometry를 C1/C2에 공유했습니다. 이전 checkpoint hash receipt가 없어 과거 모델 bytes까지 독립적으로 재인증하지는 않았습니다. 새 Underoath 관측은 현재 공식 final0와 같은 기존 전처리·final 후보 생성 방식으로 한 번 생성했습니다.',
              '8 고정곡은 이미 알려진 개발·실패 자료이고 최신 reference는 owner-reviewed 실용적인 지도입니다. 독립적인 미지곡 일반화, 제작자 시계의 밀리초 인증, 제품 playback·저장·export 검증은 아닙니다. 원본, 승인 맵, frozen 과거 결과와 제품 분석기는 변경하지 않았습니다.',
              '', '## 곡별 timeline', '']
    for row in manifest:
        timeline(run,row);lines.append(f"- [{row['title']}](figures/{row['id']}.png)")
    lines += ['', '## 재현 명령', '', '```sh', f'RUN="{run}"',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.prepare --run NEW_UNIQUE_RUN',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.controls --run "$RUN"',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.run --run "$RUN" --stage build --workers 2',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.run --run "$RUN" --stage freeze',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.run --run "$RUN" --stage predict --workers 2',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.audit --run "$RUN"',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.evaluate --run "$RUN"',
              '.venv-metronome-v1/bin/python -m experiments.bpm_continuity_v1.report --run "$RUN"','```','',
              '새 실행은 새로운 고유 run에서 시작합니다. 위 실제 run의 이미 존재하는 stage를 조용히 덮어쓰면 안 됩니다. 원본 음원과 가중치·NPZ는 결과 ZIP에 포함하지 않으며 로컬 source manifest로 찾습니다.']
    (run/'report.ko.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    predictions=list((run/'predictions').rglob('*.json'));figures=list((run/'figures').glob('*.png'))
    completion={'prediction_count':len(predictions),'expected_prediction_count':len(manifest)*len(ARMS)*len(POLICIES),
                'timeline_count':len(figures),'controls_passed':read(run/'controls.json')['passed'],
                'isolation_passed':audit['passed'],'all_targets_retained':len(manifest)==10,
                'source_git_mutations_performed':False,'product_model_replaced':False,
                'latest_reference_snapshots_preserved':True,'conclusion':result['conclusion']}
    completion['completed']=len(predictions)==completion['expected_prediction_count'] and len(figures)==10 and completion['controls_passed'] and audit['passed']
    write(run/'completion-review.json',completion)
    if not completion['completed']:raise RuntimeError('Required artifacts missing')
    archive=run/'result.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(run.rglob('*')):
            if not path.is_file() or path==archive or path.suffix in ['.npz','.ckpt','.wav','.mp3','.flac'] or 'isolation-audit' in path.parts:
                continue
            z.write(path,path.relative_to(run))
    write(run/'receipts/report.json',{'completed':True,'report':str(run/'report.ko.md'),'archive':str(archive),
                                     'archive_sha256':digest(archive),'archive_bytes':archive.stat().st_size})
    print('REPORT_COMPLETE',run/'report.ko.md',flush=True)


if __name__=='__main__': main()
