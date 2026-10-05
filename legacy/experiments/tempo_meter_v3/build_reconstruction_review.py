"""Whole-source frozen/revised review with unchanged reference bindings."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import soundfile as sf
from .build_compare_review import link
from .build_prediction_review import event_view
from .build_reviewed_review import six_scores, worst_windows
from .review_timeline import timeline_view, outside_regions
from .musical_click import musical_events
from .review_audio import render_click
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    manifest=json.loads((a.run/'predictions/manifest.json').read_text());assert manifest['complete'] and not manifest['references_available_to_runner']
    predictions={r['id']:r for r in manifest['rows']}
    old=json.loads((a.baseline/'review/review.json').read_text())
    scores={arm:{r['id']:r for r in json.loads((root/'evaluation/scores.json').read_text())['rows']}
            for arm,root in [('frozen',a.baseline),('revised',a.run)]}
    out=a.run/'review';out.mkdir(exist_ok=False);cases=[];summaries={}
    for arm,rows in scores.items():
        full=[r for r in rows.values() if r['role']=='finished_recording_development'];aux=[r for r in rows.values() if r['role']!='finished_recording_development']
        summaries[arm]=dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
                            auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux))
    for i,old_case in enumerate(old['cases']):
        c=deepcopy(old_case);ident=c['id'];folder=out/f'{i:02d}';folder.mkdir();previous=a.baseline/'review'/f'{i:02d}'
        for name in ['source.wav','reference.wav']:link(previous/name,folder/name)
        ref=json.loads((previous/'reference.json').read_text());(folder/'reference.json').write_text(json.dumps(ref,indent=2)+'\n')
        track=deepcopy(c['tracks'][0]);track.update(musical_events(ref['map']));c['reference_track']=track;c['models']={}
        c['description']=c['description'].replace('현재 모델을 재학습·수정하지 않고 같은 설정으로 실행했습니다.','같은 음원의 기존 결과와 마디 점수 보완 결과를 비교합니다.')
        for arm,label in [('frozen','기존 모델'),('revised','수정 실험안')]:
            if arm=='frozen':
                payload=json.loads((previous/'prediction.json').read_text());link(previous/'prediction.wav',folder/(arm+'.wav'));runtime=c['runtime_seconds']
            else:
                row=predictions[ident];assert digest(row['selected']['path'])==row['selected']['sha256']
                payload=json.loads(Path(row['selected']['path']).read_text());runtime=row['runtime_seconds']
            view=event_view(payload['map']);view.update(timeline_view(payload['map']));view.update(musical_events(payload['map']))
            view['outside_segments']=outside_regions(payload['map'],reference=False)
            if arm=='revised':
                audio,_=render_click(c['sample_rate'],c['sample_frames'],view['beats'],view['bars'])
                sf.write(folder/(arm+'.wav'),audio,c['sample_rate'],subtype='PCM_16')
            (folder/(arm+'.json')).write_text(json.dumps(payload,indent=2)+'\n')
            score=scores[arm][ident]['score']
            c['models'][arm]=dict(track=dict(id='prediction',label=label+' 클릭',click=f'{i:02d}/{arm}.wav',**view),
                score=score['scores'],six_scores=six_scores(score),all_gates_pass=score['all_gates_pass'],runtime_seconds=runtime,
                worst_windows=worst_windows(track,view,c['duration']),free_tail_false_positives=score.get('free_tail_false_positives'))
        c['tracks']=[track,c['models']['revised']['track']];c['source']=f'{i:02d}/source.wav';cases.append(c)
        print('review',ident,flush=True)
    data=dict(kind='reconstruction_score_comparison',review_revision=digest(a.run/'predictions/manifest.json')[:16],
              default_model='revised',default_selection='Display the intervention; not a product promotion or per-song model choice.',
              summary_by_model=summaries,model_labels=dict(frozen='기존 모델',revised='수정 실험안 · 미채택'),
              cases=cases,worst_ids=['walker_he-will-hold-me-fast',*old['worst_ids']],reference_mutation=False)
    (out/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    html=Path(__file__).with_name('compare_review.html').read_text()
    html=html.replace('정답 ↔ 기존·A·B·C 모델 비교','정답 ↔ 기존·수정 실험안 비교')
    html=html.replace('</h1>', '</h1><p class="muted">이번 실험안은 전체 통과곡 증가가 없고 퇴보한 곡도 있어 채택하지 않았습니다. 개선과 퇴보를 비교하기 위한 화면입니다.</p>',1)
    html=html.replace('<option value="meter" selected>','<option value="meter">').replace('<option value="quarter">','<option value="quarter" selected>')
    html=html.replace("${k==='frozen'?'기존':k}:","${data.model_labels[k]}:")
    old_start='await chooseCase(Math.max(0,index));requestAnimationFrame(tick)'
    new_start="await chooseCase(Math.max(0,index));const requestedTime=new URLSearchParams(location.search).get('at');if(requestedTime!==null&&Number.isFinite(Number(requestedTime)))seek(Number(requestedTime));requestAnimationFrame(tick)"
    assert old_start in html;html=html.replace(old_start,new_start)
    (out/'index.html').write_text(html)
    files=[dict(path=str(p.relative_to(out)),sha256=digest(p),bytes=p.stat().st_size) for p in sorted(out.rglob('*')) if p.is_file()]
    (out/'files.json').write_text(json.dumps(files,indent=2)+'\n')


if __name__=='__main__':main()
