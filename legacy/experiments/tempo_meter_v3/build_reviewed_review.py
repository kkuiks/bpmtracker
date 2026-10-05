"""Build a ranked, full-source listening review for a frozen reviewed-corpus run."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import soundfile as sf
from .build_prediction_review import event_view
from .evaluate_batch import load_bound
from .probe_resources import digest
from .review_audio import render_click
from .review_timeline import timeline_view, outside_regions


SCORE_KEYS = [
    ('quarter_bpm_time_within_1', 'quarter_bpm_within_1_reference_fraction'),
    ('reviewed_meter_paired_bar_fraction_70ms', 'reviewed_meter_bar_fraction_70ms'),
    ('declared_quarter_grid_f1_70ms', 'quarter_beat_f1_70ms'),
    ('bar_boundary_f1_70ms', 'bar_start_f1_70ms'),
    ('tempo_change_f1_or_no_false_positives_500ms', 'tempo_change_no_false_positives'),
    ('meter_change_f1_or_no_false_positives_500ms', 'meter_change_no_false_positives'),
]


def six_scores(score):
    return [next((score['scores'][k] for k in keys if k in score['scores']), None) for keys in SCORE_KEYS]


def worst_windows(reference, prediction, duration):
    from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
    candidates = []
    for start in range(0, max(1, int(duration)-9), 10):
        end = min(duration, start+20)
        if not any(lo <= start and end <= hi for lo,hi in reference['support']): continue
        ref_beats = [t for t in reference['beats'] if start <= t < end]
        if len(ref_beats) < 5: continue
        values = []
        for name in ('beats', 'bars'):
            ref = [t for t in reference[name] if start <= t < end]
            pred = [t for t in prediction[name] if start <= t < end]
            value = nearest_event_diagnostics(ref, pred, .07)['f1']
            values.append(value if value is not None else 0.)
        candidates.append(dict(time=start, end=end, mean_event_f1=sum(values)/2,
                               label=f'오차 큰 구간 {start}–{end:.0f}초'))
    chosen = []
    for item in sorted(candidates, key=lambda w:w['mean_event_f1']):
        if all(abs(item['time']-other['time']) >= 20 for other in chosen): chosen.append(item)
        if len(chosen) == 3: break
    return chosen


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--evaluation', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); sys.path.insert(0, str(Path.cwd()/'experiments/analysis_legacy'))
    batch = json.loads(a.manifest.read_text())
    results = json.loads((a.evaluation/'scores.json').read_text())
    if not batch['complete'] or batch['references_available_to_runner']: raise ValueError('frozen batch required')
    scores = {r['id']:r for r in results['rows']}
    priority = sorted((r for r in results['rows'] if r['role']=='finished_recording_development'),
                      key=lambda r:sum(x or 0 for x in six_scores(r['score'])[:4])/4)
    worst = [r['id'] for r in priority[:6]]
    if a.output.exists(): raise FileExistsError(a.output)
    a.output.mkdir(parents=True); cases = []
    for index,row in enumerate(batch['rows']):
        ident=row['id']; result=scores[ident]; folder=a.output/f'{index:02d}'; folder.mkdir()
        audio=Path(row['audio']); info=sf.info(audio)
        if digest(audio)!=row['source']['sha256']: raise ValueError('source changed')
        try: os.link(audio, folder/'source.wav')
        except OSError: shutil.copyfile(audio, folder/'source.wav')
        reference=json.loads((a.evaluation/(ident+'-reference.json')).read_text())
        prediction=load_bound(row['selected']); tracks=[]
        for name,label,payload in [('reference','승인 정답 클릭',reference),('prediction','모델 클릭',prediction)]:
            view=event_view(payload['map']); view.update(timeline_view(payload['map']))
            view['outside_segments']=outside_regions(payload['map'], reference=name=='reference', known_tail=result['score'].get('free_tail_false_positives') is not None)
            click,_=render_click(info.samplerate,info.frames,view['beats'],view['bars'])
            sf.write(folder/(name+'.wav'),click,info.samplerate,subtype='PCM_16')
            tracks.append(dict(id=name,label=label,click=f'{index:02d}/{name}.wav',**view))
            (folder/(name+'.json')).write_text(json.dumps(payload,indent=2)+'\n')
        windows=worst_windows(tracks[0],tracks[1],info.duration)
        jumps=[dict(time=0,label='처음')]+windows
        if result['score'].get('free_tail_false_positives') is not None:
            end=reference['map']['support_seconds'][-1][1]
            jumps.append(dict(time=max(0,end-5),label=f'무박 엔딩 경계 {end:.1f}초'))
        for change in tracks[0]['changes'][1:][:4]:
            jumps.append(dict(time=max(0,change['time']-5),label=f"정답 변박 {change['time']:.1f}초"))
        jumps.append(dict(time=max(0,info.duration-25),label='곡 끝'))
        scope=result['reference_support_seconds']
        description='현재 모델을 재학습·수정하지 않고 같은 설정으로 실행했습니다. '
        if result['score'].get('unknown_outside_reference_support_excluded'):
            description+='정답 범위 밖은 미확인으로 채점에서 제외했습니다. '
        if ident=='animals-as-leaders-red-miso':
            description+='승인된 큰 단위 4/4 지도 기준입니다. 세부 변박 정답은 확보되지 않았습니다. '
        if result['role']=='auxiliary_solo_guitar': description+='완성곡과 별도로 집계하는 기타 클립입니다. '
        description+='정답 범위: '+', '.join(f'{lo:.3f}–{hi:.3f}초' for lo,hi in scope)
        cases.append(dict(id=ident,title=result['title'],description=description,source=f'{index:02d}/source.wav',
                          sample_rate=info.samplerate,sample_frames=info.frames,duration=info.duration,
                          source_origin_seconds=0,tracks=tracks,jumps=jumps,score=result['score']['scores'],
                          six_scores=six_scores(result['score']),all_gates_pass=result['score']['all_gates_pass'],
                          role=result['role'],priority_review=ident in worst,initial_bpm=row.get('initial_bpm'),
                          runtime_seconds=row['runtime_seconds'],expected_rule_result='prediction',
                          worst_windows=windows,free_tail_false_positives=result['score'].get('free_tail_false_positives')))
    data=dict(kind='reviewed21_frozen_prediction_review',review_revision=digest(a.manifest)[:16],
              reference_mutation=False,scope='20 known development recordings and one auxiliary clip',
              worst_ids=worst,cases=cases)
    (a.output/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    template=Path(__file__).with_name('reviewed_review.html')
    (a.output/'index.html').write_text(template.read_text())
    files=[dict(path=str(f.relative_to(a.output)),sha256=digest(f),bytes=f.stat().st_size)
           for f in sorted(a.output.rglob('*')) if f.is_file()]
    (a.output/'files.json').write_text(json.dumps(files,indent=2)+'\n')
    print('Built',len(cases),'full-source reviews; priority',worst,flush=True)


if __name__=='__main__': main()
