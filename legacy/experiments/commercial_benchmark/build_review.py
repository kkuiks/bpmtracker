"""Full-source listening artifacts for a frozen commercial benchmark."""
import argparse
import json
import os
from pathlib import Path
import shutil

import soundfile as sf

from .prepare import digest
from .evaluate import KEYS
from experiments.tempo_meter_v3.build_prediction_review import event_view
from experiments.tempo_meter_v3.review_timeline import timeline_view
from experiments.tempo_meter_v3.review_audio import render_click
from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
    manifest=json.loads((run/'predictions/manifest.json').read_text())
    evaluation=run/'evaluation/cubase-pro15';scores=json.loads((evaluation/'scores.json').read_text())
    if not manifest['complete'] or len(manifest['rows'])!=21:raise ValueError('all21 complete frozen outputs required')
    results={r['id']:r for r in scores['rows']};out=run/'review'
    if out.exists():raise FileExistsError(out)
    out.mkdir();cases=[]
    for row in manifest['rows']:
        n=Path(row['neutral_name']).stem;folder=out/n;folder.mkdir();result=results[row['id']]
        source=Path(row['working_audio']);info=sf.info(source)
        try:os.link(source,folder/'source.wav')
        except OSError:shutil.copyfile(source,folder/'source.wav')
        payload=json.loads(Path(row['selected']['path']).read_text())
        reference=json.loads((evaluation/(row['id']+'-reference.json')).read_text())
        ref=event_view(reference['map']);ref.update(timeline_view(reference['map']))
        beats=emitted_quarters(payload['map'])
        curve=[dict(time=e['source_seconds'],bpm=e['bpm']) for e in payload['native_tempos'] if 0<=e['source_seconds']<info.duration]
        for label,bt,bar in [('cubase',beats,[]),('reference',ref['beats'],ref['bars'])]:
            click,_=render_click(info.samplerate,info.frames,bt,bar)
            sf.write(folder/(label+'.wav'),click,info.samplerate,subtype='PCM_16')
        (folder/'prediction.json').write_text(json.dumps(payload,indent=2)+'\n')
        (folder/'reference.json').write_text(json.dumps(reference,indent=2)+'\n')
        (folder/'score.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        score=result['score'];changes=score['tempo_change_counts'];tail=score['free_tail_false_positives']
        jumps=[dict(time=0,label='처음')]
        reference_tempos=[dict(time=e['start'],end=e['end'],bpm=e['bpm']) for e in ref['tempo_segments']]
        for event in reference_tempos[1:][:4]:jumps.append(dict(time=max(0,event['time']-5),label=f"정답 변속 {event['time']:.1f}초"))
        if tail is not None:
            t=result['reference_support_seconds'][-1][1];jumps.append(dict(time=max(0,t-5),label=f'무박 엔딩 경계 {t:.1f}초'))
        jumps.append(dict(time=max(0,info.duration-25),label='곡 끝'))
        cases.append(dict(id=row['id'],name=n,title=row['title'],role=result['role'],duration=info.duration,
                          source=f'{n}/source.wav',clicks={k:f'{n}/{k}.wav' for k in ('cubase','reference')},
                          scores=[score['scores'][k] for k in KEYS],beat_counts=score['beat_counts'],tempo_change_counts=changes,
                          tail=tail,scope=result['reference_support_seconds'],unknown_outside_scope=score['unknown_outside_reference_support_excluded'],
                          native_seconds=row['native_analysis_seconds'],workflow_seconds=row['workflow_seconds'],
                          curve=curve,reference_tempos=reference_tempos,reference_meters=ref['meter_segments'],jumps=jumps,
                          native_files={kind:'../'+str(Path(binding['path']).relative_to(run)) for kind,binding in payload['raw_native_exports'].items()}))
    (out/'review.json').write_text(json.dumps(dict(product=manifest['product'],revision=digest(run/'predictions/manifest.json')[:16],cases=cases),ensure_ascii=False,indent=2)+'\n')
    (out/'index.html').write_text(Path(__file__).with_name('review.html').read_text())
    print('Built',len(cases),'full-source source/Cubase-quarter/reference-bar listening cases')


if __name__=='__main__':main()
