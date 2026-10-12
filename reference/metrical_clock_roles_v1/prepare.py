"""Admit the same complete recordings; retain current references separately."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from .common import ROOT, PRIOR, FOCUS, CONFIG, METHODS, CRITERIA, read, write, digest, stamp

def main():
    p=argparse.ArgumentParser(); p.add_argument('--run',type=Path); a=p.parse_args()
    run=(a.run or ROOT/'data/research/runs/metrical_clock_roles_v1'/
         (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')).resolve()
    run.mkdir(parents=True,exist_ok=False)
    catalog=read(ROOT/'data/samples/catalog.json'); tracks={t['id']:t for t in catalog['tracks']}
    exclusions=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    sources={r['id']:r for r in read(PRIOR/'source-inputs.json')['samples']}
    provenance={r['id']:r for r in read(PRIOR/'provenance.json')['rows']}
    evaluation=[]; source=[]; hashes={}; receipts=[]
    for old in read(PRIOR/'evaluation-index.json')['rows']:
        ident=old['id']; original=old['original_id']; row=sources[ident]
        if old['role']!='constructed_control':
            t=tracks[original]
            if any(e.get('permanent_exclusion') and (original==e.get('id') or
                   e.get('slug','!') in t['audio']['path'] or
                   t['title'].casefold()==e.get('title','!').casefold()) for e in exclusions):
                raise RuntimeError('Excluded input')
            ref=ROOT/'data/samples'/t['reference']['path']
            sha=digest(ref)
            if sha!=provenance[ident]['reference_sha256']:
                raise RuntimeError('Reference changed; do not silently reuse old scoring')
            hashes[str(ref)]=sha
        audio=Path(row['audio_path']); sha=digest(audio)
        if sha!=provenance[ident]['audio_sha256']: raise RuntimeError('Source recording changed')
        hashes[str(audio)]=sha
        s={k:row[k] for k in ['id','audio_path','duration_seconds','sample_rate','sample_frames','channels']}
        for key,folder,suffix in [('events_path','events','.npz'),('sensor_path','source-evidence','.npz'),
                                 ('bank_path','banks','.json')]:
            path=PRIOR/folder/f'{ident}{suffix}'; s[key]=str(path); hashes[str(path)]=digest(path)
        source.append(s)
        for suffix in ['.json','.original.json']:
            path=PRIOR/'references'/f'{ident}{suffix}'
            if path.exists():
                target=run/'references'/path.name; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,target); hashes[str(target)]=digest(target)
        r={**old,'reference_path':str(run/'references'/f'{ident}.json'),
           'partition':'focus' if ident in FOCUS else 'broad_known',
           'reference_is_known_development_material':True}
        evaluation.append(r)
        for policy in ['none','proxy100']:
            path=PRIOR/'predictions/M3_REGION_HOLD'/policy/f'{ident}.json'
            target=run/'baseline'/policy/path.name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target); hashes[str(target)]=digest(target)
        receipts.append({'id':ident,**provenance[ident]})
    write(run/'source-inputs.json',{'samples':source})
    write(run/'evaluation-index.json',{'rows':evaluation})
    write(run/'provenance.json',{'rows':receipts,'prior_run':str(PRIOR),
          'catalog_sha256':digest(ROOT/'data/samples/catalog.json'),
          'sensor_reuse':True,'new_neural_inference':False,'new_human_taps':False})
    write(run/'input-freeze.json',{'hashes':hashes})
    write(run/'protocol.json',{'created_at_utc':stamp(),'config':CONFIG,'methods':METHODS,'criteria':CRITERIA,
          'primary':'initial-unit-assisted joint interpretation of physical quarter clocks and neural metrical roles',
          'focus_ids':FOCUS,'focus_then_broad':True,'primary_policy':'proxy100',
          'tap_error_fraction':.03,'tap_is_discrete_initial_unit_only':True,
          'compound_unit_encoder_is_new_research_contract_not_app_change':True,
          'source_arrays_and_clock_bank_prepared_before_proxy_values':True,
          'all_material_previously_seen':True,'all_failed_inputs_retained':True,
          'fixed_bar_meter_not_assumed':True,'complete_time_signature_output_not_primary':True,
          'offline_future_audio_used':True,'original_audio_coordinates':True,
          'app_integration':False,'source_git_publication':False,
          'observation_diagnostics_reference_informed_and_separate':True})
    write(run/'entry-state.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)})
    (run/'preregistered-plan.ko.md').write_text('''# 박 단위·신경망 역할 공동 해석 실험\n\n시작 탭은 참조 초기 BPM의 -3%, 기준값, +3%를 모의 입력으로 사용한다. 숫자는 별도 인코더에서 음원으로 준비한 박 단위의 이산 관계로 바꾼 뒤 버린다. 정확 BPM·위상·후속 구간·변경 시점을 제공하지 않는다. 이는 사람의 탭을 측정한 결과가 아니다. 복합 박의 3:2 관계까지 허용하는 연구용 인코더이며 앱의 고정 분석 계약은 바꾸지 않는다.\n\n기존 음원 기반 물리 시계 후보를 보존하되, 관측을 무조건 매 4분음표로 보던 점수를 바꾼다. 매 박, 두 박마다, 세분 박의 관측 역할과 마디 길이를 구간별 잠재 변수로 함께 해석한다. 실제 2배 변속은 허용한다. 약한 관측에서는 기존 BPM과 위상을 계속 진행한다.\n\n먼저 Over It·Millions의 반속 오류와 Underoath의 임시 BPM 구간을 평가한다. 반속 사례는 기존 M3 단위 제공 조건보다 올바른 시계 시간 +5%p 이상, 박 F1 하락 2%p 이내이면 개선으로 센다. Underoath는 올바른 시계 시간 95%, 박 F1 98% 이상이며 참조에 없는 속도 구간이 1초 미만, 두 실제 변화의 올바른 속도 쌍 경계 오차 5초 이내이면 개선으로 센다. 세 곡 중 둘 이상 개선되고 세 곡 모두 F1 하락 2%p 이내이면 전체 11개 변속곡·4개 변박 대조군·6개 고정 대조군·기존 24개 음악 대조 자료로 확장한다. 실패하면 원인 진단 후 이 구현의 확장을 중단한다.\n\n전체 평가는 올바른 박 단위, 잘못 만든 BPM 구간, 박 위치 F1, 실제 변경 경계의 오차를 각각 보고한다. 방향성 판단 기준은 올바른 시계 시간 +5%p, 반속/배속 시간 -10%p, 대조군 잘못된 시계 증가 3%p 이내 및 85% 이상 회복한 변속곡 6개이다. 하나의 합격 숫자로 프로젝트 전체의 가능성을 판정하지 않는다. 기존 실험의 실패 기준은 그대로 보존한다.\n\n모든 곡은 이미 사용한 자료이며 미지곡 일반화 실험이 아니다. 정답을 사용한 downbeat 진단, 작성한 관측 수준 대조 자료, 실제 음악 자동 추론은 별도 집계한다. 원본 음원·참조·기존 동결 코드는 변경하지 않는다.\n''')
    print('RUN',run,flush=True)

if __name__=='__main__': main()
