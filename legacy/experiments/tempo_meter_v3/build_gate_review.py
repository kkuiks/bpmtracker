"""Build gate-1 rule auditions from approved clocks and constructed controls.

No inference, training, reference changes, or production scoring takes place.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from .equivalence_probe import compare, time_at
from .review_audio import render_click
from .probe_resources import digest


def make_map(signatures, bpm=100, q0=0, t0=0):
    bars=[];q=q0
    for value in signatures:
        n,d,*g=value
        bars.append(dict(q=q,n=n,d=d,grouping=g[0] if g else None));q+=4*n/d
    return dict(clock=[[q0,t0],[q,t0+(q-q0)*60/bpm]],bars=bars)


def events(value):
    clock=value['clock'];bars=value['bars']
    end=bars[-1]['q']+4*bars[-1]['n']/bars[-1]['d']
    beats=[time_at(clock,float(q)) for q in np.arange(np.ceil(bars[0]['q']),end,1)]
    starts=[time_at(clock,b['q']) for b in bars]
    groups=[]
    for b in bars:
        q=b['q']
        for g in b.get('grouping') or []:
            groups.append(time_at(clock,q));q+=4*g/b['d']
    return beats,starts,groups


def synth(value, rate, frames):
    # Fixed reference groove shared by both auditions; candidate does not alter music.
    beats,bars,groups=events(value)
    audio=np.zeros((frames,2),dtype=np.float32)
    rng=np.random.default_rng(20260930)
    for i,t in enumerate(beats):
        ix=round(t*rate)
        if ix<0 or ix>=frames:continue
        count=min(round(.13*rate),frames-ix);s=np.arange(count)/rate
        wave=.18*np.sin(2*np.pi*(64*s+3*(1-np.exp(-25*s))))*np.exp(-25*s)
        if i%2:wave+=.06*rng.standard_normal(count)*np.exp(-40*s)
        audio[ix:ix+count]+=wave[:,None]
    for t in bars:
        ix=round(t*rate)
        if ix<0 or ix>=frames:continue
        count=min(round(.4*rate),frames-ix);s=np.arange(count)/rate
        chord=.04*sum(np.sin(2*np.pi*f*s) for f in (130.81,164.81,196))*np.exp(-8*s)
        audio[ix:ix+count]+=chord[:,None]
    return audio


def build(output, root, wage_job):
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    cases=[]
    def add(ident,title,description,reference,candidate,expected,source=None,rate=22050,origin=0,labels=None):
        duration=max(reference['clock'][-1][1],candidate['clock'][-1][1])
        frames=round(duration*rate)
        if source is None:source=synth(reference,rate,frames)
        else:frames=len(source);duration=frames/rate
        directory=output/ident;directory.mkdir()
        sf.write(directory/'source.wav',source,rate,subtype='PCM_16')
        tracks=[]
        for name,value in [('reference',reference),('candidate',candidate)]:
            beats,bars,groups=events(value)
            click,indices=render_click(rate,frames,beats,bars,groups)
            sf.write(directory/(name+'.wav'),click,rate,subtype='PCM_16')
            tracks.append(dict(id=name,label=(labels or {}).get(name,{'reference':'기준 해석','candidate':'비교 해석'}[name]),
                click=f'{ident}/{name}.wav',bars=bars,beats=beats,
                signatures=[f"{b['n']}/{b['d']}" for b in value['bars']],
                click_event_frames=indices,map=value))
        result=compare(reference,candidate)
        actual='strict' if result['strict'] else 'eligible' if result['eligible_local_rebar'] else 'reject'
        if actual!=expected:raise AssertionError((ident,actual,expected))
        cases.append(dict(id=ident,title=title,description=description,expected_rule_result=expected,
            source=f'{ident}/source.wav',sample_rate=rate,sample_frames=frames,duration=duration,
            source_origin_seconds=origin,tracks=tracks,probe=result))
    four=(4,4)
    # Derive the illustrative 6/4 candidate from B, never read the old whitelist.
    accepted=json.loads((wage_job/'tempo-owner-accepted-v1.json').read_text())
    source_path=wage_job/'master.wav'
    if digest(source_path)!=accepted['master_sha256']:raise ValueError('Wage War source changed')
    meter=accepted['meter_events']
    short=[m for m in meter if (m['numerator'],m['denominator'])==(2,4)]
    if len(short)!=1:raise ValueError('expected single reviewed short bar')
    bpm=accepted['tempo_events'][0]['bpm_quarter']; q0=short[0]['quarter']-16
    exact_origin=accepted['tempo_events'][0]['master_seconds']+q0*60/bpm
    rate=sf.info(source_path).samplerate;first=round(exact_origin*rate);origin=first/rate
    t0=exact_origin-origin
    ref=make_map([four]*4+[(2,4)]+[four]*7,bpm,q0,t0)
    alt=make_map([four]*3+[(6,4)]+[four]*7,bpm,q0,t0)
    audio,_=sf.read(source_path,start=first,frames=round(ref['clock'][-1][1]*rate),dtype='float32',always_2d=True)
    add('wage_local','1. Wage War — 4/4+2/4와 6/4',
        '승인된 B 지도에서 앞 4/4와 짧은 2/4를 합친 비교입니다. 이후 마디 위치는 같습니다. 기존 오프셋 재검토가 아닙니다.',
        ref,alt,'eligible',audio,rate,origin,{'reference':'승인된 B · 4/4+2/4','candidate':'일반 병합으로 만든 6/4'})
    source4=make_map([four]*12,bpm,q0,t0)
    add('wage_missing','2. Wage War — 짧은 마디를 놓친 일정 4/4',
        '똑같은 박 속도라도 짧은 마디를 놓치면 이후 강박이 어긋납니다. 이 경우까지 허용하면 안 됩니다.',
        ref,source4,'reject',audio,rate,origin,{'reference':'승인된 B','candidate':'일정 4/4 통제 해석'})
    base=make_map([four]*8)
    add('global_rebar','3. 같은 100 BPM · 전곡 4/4와 2/4',
        '박 간격은 같고 마디 크기만 다릅니다. 합의대로 전곡 재묶음은 자동 인정하지 않습니다.',
        base,make_map([(2,4)]*16),'reject')
    add('compound','4. 같은 길이의 3/4와 6/8',
        '마디의 초 단위 길이가 같아도 내부 박 묶음이 다릅니다. 3/4와 6/8을 자동 동등 처리하지 않습니다.',
        make_map([(3,4,[1,1,1])]*8),make_map([(6,8,[3,3])]*8),'reject')
    add('ordinary_merge','5. 일정 4/4 중 두 마디를 8/4로 병합',
        '사용자 판단: 원래 4/4 마디 경계를 유지해야 합니다. 같은 박자가 이어지는 경계를 병합으로 지우는 해석은 거부합니다.',
        base,make_map([four]*2+[(8,4)]+[four]*4),'reject')
    wrong=make_map([four]*8,t0=.16)
    add('phase_error','6. 같은 표기 · 전체 클릭이 160ms 늦음',
        '표기만 같고 실제 박 위치가 다릅니다. 복수정답 규칙으로 시계 오차를 숨기지 않습니다.',base,wrong,'reject')
    odd=make_map([(7,8,[2,2,3])]*6)
    add('odd_render','7. 7/8 마디 시작과 클릭 렌더 확인',
        '두 해석은 같습니다. 마디 시작이 정수 4분음표 사이에 있어도 강한 클릭을 출력하는지 확인하는 렌더 통제입니다.',odd,odd,'strict')
    manifest=dict(policy_revision=2,kind='gate1_rule_review_not_model_prediction',policy_status='awaiting_owner_review',
        training_performed=False,production_scoring_modified=False,cases=cases,
        source_binding=dict(path=str(source_path),sha256=accepted['master_sha256'],reference_sha256=digest(wage_job/'tempo-owner-accepted-v1.json')),
        policy_limits=['Common quarter origin and complete bars are required by this probe; arbitrary prediction-origin alignment is future work.',
            'At most four bars per edited block; two matching bars required on either side.',
            'Stable-meter boundaries must survive in both directions, including inside mixed-meter edited blocks.',
            'Grouping is preserved when supplied; unknown grouping does not certify musical equivalence.',
            'The probe is not a complete evaluator or trained analyzer.'])
    (output/'review.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (output/'index.html').write_text(Path(__file__).with_name('gate_review.html').read_text())
    protected=[]
    for file in sorted(output.rglob('*')):
        if file.is_file():protected.append(dict(path=str(file.relative_to(output)),sha256=digest(file),bytes=file.stat().st_size))
    (output/'files.json').write_text(json.dumps(protected,indent=2)+'\n')
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--wage-job',type=Path,required=True)
    a=p.parse_args();v=build(a.output,Path.cwd(),a.wage_job);print(f"Built {len(v['cases'])} review cases; no trained model or adopted policy")


if __name__=='__main__':main()
