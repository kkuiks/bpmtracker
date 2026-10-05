"""Render complete frozen predictions, approved references and v2 controls."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import numpy as np
import soundfile as sf
from .review_audio import render_click
from .probe_resources import digest


def event_view(raw):
    from music_map_contract import prepare_map,render_bars,interpolate_clock
    v=prepare_map(raw);rendered=render_bars(v)
    if rendered['status']!='rendered':raise ValueError(rendered['status'])
    def supported(t):return 0<=t<v['duration_seconds'] and any(lo<=t<hi for lo,hi in v['support_seconds'])
    unit=v['quarters_per_pulse']['numerator']/v['quarters_per_pulse']['denominator'];knots=v['clock_knots']
    beats=[interpolate_clock(knots,q/unit) for q in range(math.ceil(knots[0]['pulse']*unit),math.floor(knots[-1]['pulse']*unit)+1)]
    bars=[b for b in rendered['bars'] if supported(b['start_seconds'])]
    return dict(beats=[t for t in beats if supported(t)],bars=[b['start_seconds'] for b in bars],
        signatures=[f"{b['meter']['numerator']}/{b['meter']['denominator']}" for b in bars],
        changes=[dict(time=interpolate_clock(knots,m['pulse']),signature=f"{m['numerator']}/{m['denominator']}") for m in v['meter_events']],
        support=v['support_seconds'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--evaluation',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    batch=json.loads(a.manifest.read_text());baseline=json.loads(a.baseline.read_text());by_id={r['id']:r for r in baseline['rows']}
    scores=json.loads((a.evaluation/'scores.json').read_text());score_by_id={r['id']:r['score'] for r in scores['rows']}
    if not batch['complete'] or batch['references_available_to_runner']:raise ValueError('frozen predictions required')
    a.output.mkdir(parents=True);cases=[]
    for index,row in enumerate(batch['rows']):
        folder=a.output/f'{index:02d}';folder.mkdir();audio=Path(row['audio']);info=sf.info(audio)
        if digest(audio)!=row['source']['sha256']:raise ValueError('source changed')
        try:os.link(audio,folder/'source.wav')
        except OSError:shutil.copyfile(audio,folder/'source.wav')
        ref=json.loads((a.evaluation/(row['id']+'-reference.json')).read_text())
        maps=[('reference','승인된 참조',ref),('prediction','새 공통 모델',json.loads(Path(row['selected']['path']).read_text())),
              ('baseline','기존 공통 경로',json.loads(Path(by_id[row['id']]['selected']['path']).read_text()))]
        tracks=[]
        for name,label,payload in maps:
            view=event_view(payload['map']);click,_=render_click(info.samplerate,info.frames,view['beats'],view['bars'])
            sf.write(folder/(name+'.wav'),click,info.samplerate,subtype='PCM_16')
            tracks.append(dict(id=name,label=label,click=f'{index:02d}/{name}.wav',**view))
            (folder/(name+'.json')).write_text(json.dumps(payload,indent=2)+'\n')
        important=tracks[0]['changes'][1:];jumps=[dict(time=0,label='시작')]
        for knot in ref['map']['clock_knots'][1:-1][:4]:
            if 0<knot['source_seconds']<info.duration:jumps.append(dict(time=max(0,knot['source_seconds']-6),label=f"템포 경계 {knot['source_seconds']:.1f}초"))
        for change in important[:4]:jumps.append(dict(time=max(0,change['time']-6),label=f"참조 {change['time']:.1f}초 · {change['signature']}"))
        # These are review jumps only; they never influence predictions.
        for value in (.33,.66):jumps.append(dict(time=info.duration*value,label=f'{int(value*100)}% 지점'))
        jumps.append(dict(time=max(0,info.duration-25),label='엔딩'))
        cases.append(dict(id=row['id'],title=row['title'],description='네 곡 모두 같은 학습 모델·후보 생성·선택 규칙을 사용했습니다. 승인된 참조 및 기존 경로와 비교해 박 속도, 강박, 변속·변박 경계와 엔딩을 확인해주세요.',
            expected_rule_result='prediction',source=f'{index:02d}/source.wav',sample_rate=info.samplerate,sample_frames=info.frames,duration=info.duration,
            source_origin_seconds=0,tracks=tracks,jumps=jumps,score=score_by_id[row['id']]['scores'],
            initial_bpm=row.get('initial_bpm'),initial_bpm_source=row.get('initial_bpm_source'),runtime_seconds=row['runtime_seconds']))
    data=dict(kind='gate2_frozen_model_prediction_review',review_revision=digest(a.manifest)[:16],reference_mutation=False,
        scope='known development recordings; not unseen accuracy',cases=cases)
    (a.output/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    template=Path(__file__).with_name('prediction_review.html')
    (a.output/'index.html').write_text(template.read_text())
    files=[dict(path=str(f.relative_to(a.output)),sha256=digest(f),bytes=f.stat().st_size) for f in sorted(a.output.rglob('*')) if f.is_file()]
    (a.output/'files.json').write_text(json.dumps(files,indent=2)+'\n')
    print('Built full-song prediction review:',len(cases))

if __name__=='__main__':main()
