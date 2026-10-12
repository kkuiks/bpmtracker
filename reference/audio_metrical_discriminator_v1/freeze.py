import argparse
from pathlib import Path
import shutil
from .common import ROOT,CONFIG,CRITERIA,LEARNED,read,write,stamp,code_hashes

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    if (a.run/'freeze.json').exists():raise RuntimeError('Never overwrite a freeze')
    if not read(a.run/'pre-target-controls.json')['all_pass']:raise RuntimeError('Pre-target controls failed')
    hashes=code_hashes()
    for path in hashes:
        target=a.run/'code-snapshot'/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,target)
    protocol=read(a.run/'protocol.json');protocol.update({'config':CONFIG,'criteria':CRITERIA,'learned':LEARNED,
                'no_input_augmentation_on_development_only':True,
                'two_confirmatory_audio_methods_declared_before_test':True,
                'each_bootstrap_lower_tail_025_for_two_prespecified_hypotheses':True})
    write(a.run/'protocol.json',protocol)
    plan=a.run/'preregistered-plan.ko.md'
    with plan.open('a') as f:f.write('\n초기 원음 패턴 모델과 원음·신경망 결합 모델 두 가설을 사전에 확인 대상으로 지정한다. 각각 곡 단위 개선의 2.5% 부트스트랩 하한을 요구하며, 나머지 방법은 대조다. 결과를 보고 기본 알고리즘을 바꾸거나 성공 기준을 낮추지 않는다. 초기 단위 사용 모델은 개발곡에서 무입력 예도 함께 학습하며 검증곡의 라벨은 학습하지 않는다.\n')
    write(a.run/'freeze.json',{'frozen_at_utc':stamp(),'config':CONFIG,'criteria':CRITERIA,
                             'learned':LEARNED,'code_hashes':hashes,'no_target_feature_scoring_before_freeze':True})
    print('FROZEN',len(hashes),flush=True)

if __name__=='__main__':main()
