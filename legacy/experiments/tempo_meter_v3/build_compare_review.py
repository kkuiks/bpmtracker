"""Full-source old/A/B/C review; musical clicks remain a separate display mode."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import soundfile as sf
from .probe_resources import digest
from .build_prediction_review import event_view
from .build_reviewed_review import six_scores,worst_windows
from .review_timeline import timeline_view,outside_regions
from .musical_click import musical_events
from .review_audio import render_click


def link(source,target):
    try:os.link(source,target)
    except OSError:shutil.copyfile(source,target)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    output=a.run/'review'
    if output.exists():raise FileExistsError(output)
    old=json.loads((a.baseline/'review/review.json').read_text());models={};summaries={}
    baseline_scores=json.loads((a.baseline/'evaluation/scores.json').read_text())['rows']
    models['frozen']=dict(scores={r['id']:r for r in baseline_scores})
    for arm in ['A','B','C']:
        manifest=json.loads((a.run/f'predictions-{arm}'/'manifest.json').read_text())
        scores=json.loads((a.run/f'evaluation-{arm}'/'scores.json').read_text())['rows']
        if not manifest['complete']:raise ValueError('all source predictions must finish')
        models[arm]=dict(manifest=manifest,rows={r['id']:r for r in manifest['rows']},scores={r['id']:r for r in scores})
    for arm,model in models.items():
        rows=list(model['scores'].values());full=[r for r in rows if r['role']=='finished_recording_development'];aux=[r for r in rows if r['role']!='finished_recording_development']
        summaries[arm]=dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
                            auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux))
    losses={arm:json.loads((a.run/f'train-{arm}'/'result.json').read_text())['best_validation_loss'] for arm in ['A','B','C']}
    default=min(losses,key=losses.get);output.mkdir();cases=[]
    for i,base_case in enumerate(old['cases']):
        c=deepcopy(base_case);ident=c['id'];folder=output/f'{i:02d}';folder.mkdir();old_folder=a.baseline/'review'/f'{i:02d}'
        c['description']=c['description'].replace('현재 모델을 재학습·수정하지 않고 같은 설정으로 실행했습니다.','선택한 모델의 예측을 승인 정답과 비교합니다.')
        link(old_folder/'source.wav',folder/'source.wav');link(old_folder/'reference.wav',folder/'reference.wav')
        reference=json.loads((old_folder/'reference.json').read_text());reftrack=deepcopy(c['tracks'][0]);reftrack.update(musical_events(reference['map']))
        (folder/'reference.json').write_text(json.dumps(reference,indent=2)+'\n');c['reference_track']=reftrack;c['models']={}
        for arm in ['frozen','A','B','C']:
            score=models[arm]['scores'][ident]['score']
            if arm=='frozen':
                payload=json.loads((old_folder/'prediction.json').read_text());link(old_folder/'prediction.wav',folder/(arm+'.wav'));runtime=c['runtime_seconds']
            else:
                row=models[arm]['rows'][ident];payload=json.loads(Path(row['selected']['path']).read_text());runtime=row['runtime_seconds']
            view=event_view(payload['map']);view.update(timeline_view(payload['map']));view.update(musical_events(payload['map']))
            view['outside_segments']=outside_regions(payload['map'],reference=False)
            if arm!='frozen':
                click,_=render_click(c['sample_rate'],c['sample_frames'],view['beats'],view['bars'])
                sf.write(folder/(arm+'.wav'),click,c['sample_rate'],subtype='PCM_16')
            (folder/(arm+'.json')).write_text(json.dumps(payload,indent=2)+'\n')
            c['models'][arm]=dict(track=dict(id='prediction',label=('기존 모델' if arm=='frozen' else arm+' 모델')+' 클릭',click=f'{i:02d}/{arm}.wav',**view),
                score=score['scores'],six_scores=six_scores(score),all_gates_pass=score['all_gates_pass'],runtime_seconds=runtime,
                worst_windows=worst_windows(reftrack,view,c['duration']),free_tail_false_positives=score.get('free_tail_false_positives'))
        c['tracks']=[reftrack,c['models'][default]['track']];c['source']=f'{i:02d}/source.wav';cases.append(c)
        print('comparison-review',ident,flush=True)
    revision=hashlib.sha256(''.join(digest(a.run/f'predictions-{arm}'/'manifest.json') for arm in ['A','B','C']).encode()).hexdigest()[:16]
    data=dict(kind='gate3_learned_model_comparison',review_revision=revision,default_model=default,
              default_selection='lowest held-out learning loss among A/B/C, not primary21 score',summary_by_model=summaries,
              model_labels=dict(frozen='기존 모델',A='A · 기존 특징 + 구조 모델',B='B · MERT 특징 추가',C='C · 마디 문맥 모델'),
              cases=cases,worst_ids=old['worst_ids'],reference_mutation=False)
    (output/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    shutil.copyfile(Path(__file__).with_name('compare_review.html'),output/'index.html')
    files=[dict(path=str(f.relative_to(output)),sha256=digest(f),bytes=f.stat().st_size) for f in sorted(output.rglob('*')) if f.is_file()]
    (output/'files.json').write_text(json.dumps(files,indent=2)+'\n')
    print('default display model',default,'selected on learning validation',flush=True)


if __name__=='__main__':main()
