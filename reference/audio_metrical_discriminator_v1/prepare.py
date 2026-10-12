"""Admit current references without changing frozen data or source geometry."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil,subprocess
from .common import ROOT,PRIOR,DEVELOPMENT,VALIDATION,FOLDS,FACTORS,CONFIG,CRITERIA,LEARNED,HEURISTIC,read,write,digest,stamp

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path);a=p.parse_args()
    run=(a.run or ROOT/'data/research/runs/audio_metrical_discriminator_v1'/
         (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')).resolve();run.mkdir(parents=True,exist_ok=False)
    catalog=read(ROOT/'data/samples/catalog.json');tracks={t['id']:t for t in catalog['tracks']}
    exclusions=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    sources={r['id']:r for r in read(PRIOR/'source-inputs.json')['samples']}
    old_provenance={r['id']:r for r in read(PRIOR/'provenance.json')['rows']}
    evaluation=[];source=[];hashes={};provenance=[]
    for old in read(PRIOR/'evaluation-index.json')['rows']:
        ident=old['id'];original=old['original_id'];s=sources[ident];previous=old_provenance[ident]
        partition='development' if ident in DEVELOPMENT else 'validation' if ident in VALIDATION else 'constructed_control'
        if old['role']!='constructed_control':
            t=tracks[original]
            if any(e.get('permanent_exclusion') and (original==e.get('id') or e.get('slug','!') in t['audio']['path'] or t['title'].casefold()==e.get('title','!').casefold()) for e in exclusions):raise RuntimeError('Excluded input')
            ref=ROOT/'data/samples'/t['reference']['path'];sha=digest(ref)
            if sha!=previous['reference_sha256']:raise RuntimeError('Current reference differs; no silent old scoring')
            hashes[str(ref)]=sha
        audio=Path(s['audio_path']);sha=digest(audio)
        if sha!=previous['audio_sha256']:raise RuntimeError('Source recording changed')
        hashes[str(audio)]=sha
        row={k:s[k] for k in ['id','audio_path','duration_seconds','sample_rate','sample_frames','channels']}
        for key,folder,suffix in [('events_path','events','.npz'),('sensor_path','source-evidence','.npz'),('bank_path','banks','.json')]:
            path=PRIOR/folder/f'{ident}{suffix}';row[key]=str(path);hashes[str(path)]=digest(path)
        row['table_path']=str(PRIOR/'tables/expanded'/f'{ident}.npz');hashes[row['table_path']]=digest(row['table_path'])
        source.append(row)
        for suffix in ['.json','.original.json']:
            path=PRIOR/'references'/f'{ident}{suffix}'
            if path.exists():
                target=run/'references'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);hashes[str(target)]=digest(target)
        evaluation.append({**old,'partition':partition,'reference_path':str(run/'references'/f'{ident}.json'),
                           'known_material_not_new_unseen_music':True})
        provenance.append({**previous,'new_raw_pcm_features':True,'new_neural_inference':False})
    write(run/'source-inputs.json',{'samples':source})
    write(run/'learning-split.json',{'development':DEVELOPMENT,'validation':VALIDATION,
          'development_group_folds':FOLDS,'constructed_controls':[r['id'] for r in evaluation if r['partition']=='constructed_control'],
          'previously_seen_material':True,'new_ranker_fitting_song_separated':True})
    write(run/'evaluation-index.json',{'rows':evaluation})
    write(run/'provenance.json',{'rows':provenance,'prior_run':str(PRIOR),'no_source_or_reference_modification':True})
    write(run/'input-freeze.json',{'hashes':hashes})
    write(run/'protocol.json',{'created_at_utc':stamp(),'config':CONFIG,'criteria':CRITERIA,'factors':FACTORS,
          'learned':LEARNED,'heuristic':HEURISTIC,'split':'learning-split.json',
          'primary':'source-derived unit-family discrimination using original-audio rhythmic patterns',
          'not_full_clock_or_boundary_inference':True,'no_global_constant_tempo_or_meter_assumption':True,
          'no_raw_tap_as_numeric_bpm_feature':True,'human_taps_measured':False,'proxy_factors':[.97,1.,1.03],
          'initial_input_only_unit':True,'fine_bpm_phase_and_boundary_not_scored_as_success':True,
          'conditional_unit_labels_tolerance':.05,'all_supported_validation_centers_retained':True,
          'training_only_purity_filter':.85,'no_absolute_bpm_feature':True,'no_song_identity_feature':True,
          'no_fixed_4_4_rhythm_template':True,'learning_on_development_references_only':True,
          'test_reference_scoring_only_after_model_freeze_and_serialized_predictions':True,
          'not_pretrained_neural_model_replacement':True,'app_integration':False,'source_git_publication':False})
    write(run/'entry-state.json',{'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)})
    (run/'preregistered-plan.ko.md').write_text('''# 원음 리듬 패턴의 박 단위 판별 실험\n\n음원으로 구한 국소 신경망 박 시계에 대해 1/4, 1/3, 1/2, 2/3, 3/4, 1, 4/3, 3/2, 2, 3, 4 관계를 비교한다. 원음 저·중·고역 공격음의 자기상관, 여러 마디 길이에서 접은 상대 강세 패턴, 시작 박 단위에 맞춘 패턴과의 관계를 특징으로 사용한다. 단순 공격음과 클릭의 일치 점수를 더하는 실험과 다르다. 드럼 악기 종류를 인증하는 모델은 아니며 주파수별 패턴이다.\n\n개발: 변속 6곡(Opeth, ADTR, Underoath, Archspire, Deadman, Wage War), 변박 2곡(Nocturne, Jinjer), 고정 3곡(Kami Kehoe, Periphery, In Flames). 검증: 변속 5곡(Circle With Me, Juno, Over It, Roundabout, Millions), 변박 2곡(Naysayer, Return to Earth), 고정 3곡(San Quentin, Common Sense, HARD2TELL). 기존 작성 음악 대조 24개는 학습하지 않는다. 모두 과거에 사용한 자료이며 미지곡 일반화의 인증이 아니다. 이번 판별기의 학습·설정 선택은 곡 단위로 분리한다.\n\n신경망만 쓰는 학습 비교 모델과 원음 특징·초기 패턴·결합 모델을 비교한다. 정규화 비용은 개발곡 3분할 검증으로만 고른다. 검증 참조는 최종 모델과 예측을 저장한 뒤 채점에만 사용한다. 모의 시작 탭은 참조 초기 BPM의 ±3%이며 음원 특징을 모두 준비한 후 별도 인코더에서 이산 단위 관계로 바꾸고 숫자를 버린다.\n\n박 단위 성공은 국소 신경망 박 시계의 후보 관계가 해당 시각 참조 BPM의 5% 이내에 들어가는지를 기준으로 한다. 이는 미세 BPM·위상·변속 경계의 성공이 아니다. 후보군에 맞는 단위가 없거나 근거가 부족한 경우를 검증 분모에서 빼지 않는다. 학습에는 16초 창에서 참조 BPM 상태의 비중이 85% 이상인 구간만 사용한다.\n\n기본 결합 모델이 검증 변속곡 평균 80% 이상, 신경망 비교 모델보다 +5%p 이상 및 오류 25% 이상 감소, 3곡 이상 +1%p 개선·4곡 이상 하락 1%p 이내, 곡 단위 부트스트랩 개선 하한이 0보다 큰 경우를 유효한 구별력으로 본다. 고정·변박 대조군 평균 하락은 3%p 이내여야 한다. Juno의 실제 2배 변경 뒤 판별은 80% 이상이고 비교 모델보다 나빠지면 안 된다. 실제 BPM이 유지된 관측 박 단위 변경 쌍의 성공률 하락도 3%p 이내여야 한다. 필요한 쌍을 채점할 수 없는 경우에는 제한을 보고하고 통과를 주장하지 않는다.\n\n통과하면 전체 시계 선택기에 연결할 근거가 생긴 것으로 판단한다. 이 작업에서는 판별 정보의 유효성을 검증하며 기존 동결 선택기·앱·참조를 수정하지 않는다. 실패하면 이 특징·판별기에서 효과를 입증하지 못한 것으로 보고 현재 구조의 자동 확장 연구를 보류하는 방향을 권한다. 한 실험으로 모든 원음 분석이 불가능하다고 주장하지 않는다.\n''')
    print('RUN',run,flush=True)

if __name__=='__main__':main()
