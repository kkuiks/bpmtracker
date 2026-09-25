"""Build a prediction-blind listening bundle for uncertain reference semantics."""
import argparse
import html
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from run_beat_this import render_clicks

BASE_FLAGS={'musical_quarter_intent_not_independently_verified',
    'tick_zero_musical_phase_not_independently_verified','synthesized_arrangement_not_recorded_studio_band'}


def review_questions(downbeat_count):
    questions=['Do the regular clicks follow the intended main musical beat throughout the scored span?']
    if downbeat_count:
        questions.append('Do the accented clicks mark the intended first beat of each bar?')
        questions.append('If not, identify an approximate source-time range and whether the error is beat level, phase, or bar phase.')
    else:
        questions.append('If not, identify an approximate source-time range and whether the clicks follow a subdivision, half/double pulse level, or a shifted phase.')
        questions.append('No downbeat reference is present, so this bundle cannot approve meter or bar phase.')
    return questions


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    if args.output_dir.exists():p.error('output directory must be new')
    catalog=json.loads(args.catalog.read_text());records={t['id']:t for t in catalog['tracks']}
    audit=json.loads(args.audit.read_text());items=[];args.output_dir.mkdir(parents=True)
    for row in audit['tracks']:
        flags=[v for v in row['qualification']['review_flags'] if v not in BASE_FLAGS]
        if not flags:continue
        track=records[row['id']];audio_path=Path(track['input']['path']);reference_path=Path(track['reference']['path'])
        if sha256(audio_path)!=track['input']['sha256'] or sha256(reference_path)!=track['reference']['sha256']:
            raise ValueError('review input hash mismatch')
        reference=json.loads(reference_path.read_text());audio,rate=sf.read(audio_path,dtype='float32',always_2d=True)
        beats=np.asarray(reference['beats_seconds']);down=np.asarray(reference['downbeats_seconds'] or [])
        clicks,skipped=render_clicks(beats,down,rate,len(audio));mix=.55*audio+clicks[:,None]*.8
        gain=min(1.,.98/max(float(np.max(abs(mix))),1e-12));target=args.output_dir/row['id'];target.mkdir()
        sf.write(target/'reference-click.wav',clicks,rate,subtype='PCM_16')
        sf.write(target/'music-with-reference-click.wav',mix*gain,rate,subtype='PCM_16')
        item={'id':row['id'],'flags':flags,'audio_sha256':track['input']['sha256'],
            'reference_sha256':track['reference']['sha256'],'reference_kind':reference['kind'],
            'review_support_seconds':reference['evaluation_support_seconds'],'beat_count':len(beats),
            'downbeat_count':len(down),'skipped_outside_audio':skipped,'model_predictions_included':False,
            'files':{'click':str(target/'reference-click.wav'),'audition':str(target/'music-with-reference-click.wav')},
            'questions':review_questions(len(down))}
        (target/'review.json').write_text(json.dumps(item,indent=2,ensure_ascii=False)+'\n');items.append(item)
    if len(items)>3:raise ValueError('review batch exceeds three tracks')
    blocks=[]
    for item in items:
        rel=Path(item['files']['audition']).relative_to(args.output_dir)
        blocks.append(f'<section><h2>{html.escape(item["id"])}</h2><p>{html.escape(", ".join(item["flags"]))}</p><audio controls preload="metadata" src="{rel.as_posix()}"></audio><ol>'+''.join('<li>'+html.escape(q)+'</li>' for q in item['questions'])+'</ol></section>')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Reference-only review</title><style>body{font:16px/1.6 system-ui;max-width:950px;margin:30px auto;padding:0 20px;background:#f3f5f7}section{background:white;padding:20px;margin:18px 0;border-radius:10px}audio{width:100%}.notice{background:#fff1cf;padding:14px}</style><h1>참조 지도 의미 검토</h1><p class="notice">모델 예측은 포함하지 않았습니다. 음악과 공급 MIDI에서 만든 박 클릭만 비교합니다. 다운비트가 없는 항목은 이 화면으로 박자나 마디 위상을 판정할 수 없습니다.</p>'''+''.join(blocks)+'</html>'
    (args.output_dir/'index.html').write_text(page,encoding='utf-8')
    (args.output_dir/'manifest.json').write_text(json.dumps({'items':items,'model_predictions_included':False},indent=2,ensure_ascii=False)+'\n')
    print(args.output_dir/'index.html',len(items))


if __name__=='__main__':main()
