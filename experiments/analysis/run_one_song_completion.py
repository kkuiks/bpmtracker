"""Make the Light Has Come pilot clocks and a four-way listening bundle.

All media and reports belong in a new ignored run directory. The reference is
opened only after the automatic proposal has been saved. Supplied anchors remain
visible external assistance; they never become automatic performance claims.
"""
import argparse
import json
from pathlib import Path
import shutil

import mido
import numpy as np
import soundfile as sf

from build_one_song_listening import sha256
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from complete_song_clock import assemble_clock, assist_clock, rebuild_clock
from fit_clock import clock_time
from grid_metrics import indexed_grid_metrics


def write_json(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def render_quarter_click(path, times, sample_rate, sample_frames):
    """Identical unaccented clicks on original source samples, without padding."""
    if any(not np.isfinite(v) or v<=0 or v!=int(v) for v in (sample_rate,sample_frames)):
        raise ValueError('click geometry requires positive integral sample rate and frame count')
    sample_rate,sample_frames=int(sample_rate),int(sample_frames)
    times=np.asarray(times,dtype=float)
    if times.ndim!=1 or not np.isfinite(times).all() or np.any(np.diff(times)<=0) or np.any(times<0) or np.any(times>=sample_frames/sample_rate):
        raise ValueError('click events must increase inside the source')
    indices=np.rint(times*sample_rate).astype(int)
    if np.any(indices>=sample_frames):raise ValueError('rounded click would lie beyond source frames')
    sample=np.arange(round(.020*sample_rate))
    tone=.45*np.sin(2*np.pi*1000*sample/sample_rate)*np.exp(-sample/(sample_rate*.004))
    signal=np.zeros(sample_frames,dtype=np.float32)
    for index in indices:
        end=min(index+len(tone),sample_frames);signal[index:end]+=tone[:end-index]
    if np.max(abs(signal))>=1:raise ValueError('click renderer would clip')
    sf.write(path,signal,sample_rate,subtype='PCM_16')
    return {'sha256':sha256(path),'sample_rate':sample_rate,'sample_frames':sample_frames,
            'event_count':len(times),'onset_rounding_max_seconds':float(np.max(abs(indices/sample_rate-times))) if len(times) else 0.,
            'waveform':{'frequency_hz':1000,'duration_seconds':.02,'decay_seconds':.004,'amplitude':.45,'accents':False}}


def reference_clock(reference, duration):
    events=reference['tempo_events'];ppq=reference['ticks_per_quarter']
    if not np.isfinite(ppq) or ppq<=0 or ppq!=int(ppq) or not events:
        raise ValueError('reference requires positive integral PPQ and tempo events')
    if any(not np.isfinite([e['tick'],e['time_seconds'],e['microseconds_per_quarter']]).all() for e in events):
        raise ValueError('reference tempo events must be finite')
    if events[0]['tick']!=0 or events[0]['time_seconds']!=0 or reference['source_origin_shift_seconds']!=0:
        raise ValueError('this pilot requires a declared zero reference origin')
    meters=reference['meter_events']
    if (not meters or meters[0]['tick']!=0 or meters[0]['time_seconds']!=0 or
            any(e['numerator']!=4 or e['denominator']!=4 for e in meters)):
        raise ValueError('this pilot requires creator-declared constant 4/4')
    slopes=np.array([e['microseconds_per_quarter']/1e6 for e in events])
    result=rebuild_clock([e['tick']/ppq for e in events[1:]],np.r_[0,slopes[0],np.diff(slopes)],duration)
    integrated=clock_time([e['tick']/ppq for e in events],result['knot_pulse_indices'],result['coefficients'])
    if np.max(abs(integrated-[e['time_seconds'] for e in events]))>1e-8:
        raise ValueError('reference ticks, tempos and source times disagree')
    return result


def export_midi(path, clock, duration, ppq=9600):
    """Export explicit-origin 4/4 maps and audit MIDI tick/tempo quantization."""
    if not isinstance(ppq,int) or not 1<=ppq<=32767:
        raise ValueError('MIDI requires positive 15-bit PPQ')
    if clock.get('source_origin_seconds')!=0 or clock.get('support_seconds')!=[0.,duration]:
        raise ValueError('MIDI export requires source-zero full-source support')
    rebuild_clock(clock['knot_pulse_indices'],clock['coefficients'],duration)
    meter=clock.get('meter') or {}
    if abs(clock['coefficients'][0])>1e-9 or meter.get('numerator')!=4 or meter.get('denominator')!=4:
        raise ValueError('MIDI export requires explicit source-zero 4/4 origin')
    slopes=np.cumsum(clock['coefficients'][1:]);quarters=np.r_[0,clock['knot_pulse_indices']]
    ticks=np.rint(quarters*ppq).astype(int)
    if ticks[0]!=0 or np.any(np.diff(ticks)<=0):raise ValueError('MIDI tempo ticks must increase')
    tempos=np.rint(slopes*1e6).astype(int)
    if np.any(tempos<=0) or np.any(tempos>0xffffff):raise ValueError('tempo outside MIDI range')
    midi=mido.MidiFile(type=0,ticks_per_beat=ppq);track=mido.MidiTrack();midi.tracks.append(track)
    track.append(mido.MetaMessage('track_name',name='Unaccepted source tempo map',time=0))
    track.append(mido.MetaMessage('time_signature',numerator=4,denominator=4,time=0))
    previous=0
    for tick,tempo in zip(ticks,tempos):
        track.append(mido.MetaMessage('set_tempo',tempo=int(tempo),time=int(tick-previous)));previous=int(tick)
    end=max(previous,int(np.ceil(clock['pulse_index_span'][1]*ppq)))
    track.append(mido.MetaMessage('end_of_track',time=end-previous));midi.save(path)
    # Read the actual file, not the pre-export arrays, to bound export changes.
    absolute=0;loaded=[]
    for event in mido.MidiFile(path).tracks[0]:
        absolute+=event.time
        if event.type=='set_tempo':loaded.append((absolute/ppq,event.tempo/1e6))
    reloaded=rebuild_clock([q for q,_ in loaded[1:]],np.r_[0,loaded[0][1],np.diff([s for _,s in loaded])],duration)
    q=np.array([v['quarter_position'] for v in clock['indexed_grid']])
    error=clock_time(q,reloaded['knot_pulse_indices'],reloaded['coefficients'])-clock_time(q,clock['knot_pulse_indices'],clock['coefficients'])
    maximum=float(np.max(abs(error)))
    if maximum>.001:raise ValueError('MIDI export exceeded 1 ms grid error')
    return {'sha256':sha256(path),'ticks_per_quarter':ppq,'grid_roundtrip_max_seconds':maximum,
            'origin_shift_seconds':0,'meter':'explicit 4/4','accepted':False}


def run(args):
    output=args.output_dir
    if output.exists():raise ValueError('output must be a new directory')
    source_hash=sha256(args.audio);info=sf.info(args.audio)
    if info.format!='WAV':raise ValueError('listening source must be canonical WAV')
    report_input=json.loads(args.crossed_report.read_text())
    row=next(t for t in report_input['tracks'] if t['id']==args.track)
    if row['source']['sha256']!=source_hash:raise ValueError('crossed result is not for this source')
    regions=json.loads(args.regions.read_text())
    region_input=regions['input_provenance']
    if (region_input['audio']['sha256']!=source_hash or regions.get('source_origin_seconds')!=0 or
            region_input['logits_sha256']!=sha256(args.beat_this_logits)):
        raise ValueError('region evidence belongs to another source, model or origin')
    paths={'beat_this':args.beat_this_logits,'beat_transformer':args.beat_transformer_logits}
    observations={m:row['methods'][m+'__common_minimal']['prediction']['beats_seconds'] for m in paths}
    logits={}
    for name,path in paths.items():
        with np.load(path) as values:
            if any(key in values and float(values[key])!=0 for key in ('source_frame_offset','frame_time_offset_seconds')):
                raise ValueError('nonzero model origin needs an explicit adapter')
            logits[name]=(values['beat'],float(values['fps']))
        provenance=row['model_provenance'][name]
        if sha256(path)!=provenance['logits_sha256']:raise ValueError('model evidence hash mismatch')
    output.mkdir(parents=True)
    automatic=assemble_clock(regions,observations,logits,info.duration)
    automatic['input_provenance']={'source_sha256':source_hash,'regions_sha256':sha256(args.regions),
        'logits':{name:{'path':str(path),'sha256':sha256(path)} for name,path in paths.items()}}
    write_json(output/'automatic-proposal.json',automatic)
    frozen_automatic_hash=sha256(output/'automatic-proposal.json')
    # Explicitly separated stage. No reference object enters assemble_clock.
    reference=json.loads(args.reference.read_text())
    if reference['source_audio_sha256']!=source_hash:raise ValueError('reference belongs to another source')
    assistance=json.loads(args.anchors.read_text())
    assisted=assist_clock(automatic,assistance['anchors'],assistance['quarter_origin_offset'],assistance['meter'],info.duration)
    assisted['assistance']['input_file_sha256']=sha256(args.anchors)
    selected=next(c for c in automatic['candidates'] if c['id']==automatic['selected_candidate_id'])['clock']
    selected.update({'reference_used_for_prediction':False,'bridge_certified':False,'meter':None})
    old=row['methods']['beat_this__clock_current']['clock']
    previous=rebuild_clock(old['knot_pulse_indices'],old['coefficients'],info.duration)
    previous.update({'reference_used_for_prediction':False,'meter':None,'status':'previous_clock_with_terminal_extrapolation'})
    truth=reference_clock(reference,info.duration)
    truth.update({'reference_used_for_prediction':True,'status':'creator_reference_not_prediction',
                  'meter':{'numerator':4,'denominator':4,'provenance':'creator MIDI'}})
    clocks={'previous':previous,'automatic':selected,'assisted':assisted,'reference':truth}
    metrics={};exports={};renders={}
    lo,hi=reference['evaluation_support_seconds']
    for name,clock in clocks.items():
        clock['reference_evaluation_support_seconds']=[lo,hi]
        clock['tail_status']='extrapolated_or_declared_only; no audible creator click beyond evaluation support'
        write_json(output/f'{name}-map.json',clock)
        renders[name]=render_quarter_click(output/f'{name}-click.wav',clock['beats_seconds'],info.samplerate,info.frames)
        metrics[name]=evaluate_times(reference,clock['beats_seconds'],tempo_events(clock))
        if name in ('assisted','reference'):
            ref=[{'index':q,'time_seconds':t} for q,t in zip(reference['quarter_indices'],reference['beats_seconds']) if lo<=t<=hi]
            pred=[{'index':v['quarter_position'],'time_seconds':v['source_seconds']} for v in clock['indexed_grid'] if lo<=v['source_seconds']<=hi]
            metrics[name]['indexed_grid']=indexed_grid_metrics(ref,pred,origin_status='shared_explicit_origin')
            metrics[name]['full_tempo_meter_map_status']='creator_assisted_explicit_4_4_origin_not_automatic'
            exports[name]=export_midi(output/f'{name}-tempo.mid',clock,info.duration)
    shutil.copyfile(args.audio,output/'music.wav')
    if sha256(output/'music.wav')!=source_hash:raise ValueError('source copy mismatch')
    descriptions={
        'previous':('이전 자동 결과','전곡을 한 번에 맞춘 기존 지도','중간의 빠진 박 때문에 잘못된 속도 변화가 생긴 기존 자동 결과입니다. 끝부분은 마지막 속도로 연장했습니다.'),
        'automatic':('새 자동 후보','구간을 연결한 조건부 제안','관측된 앞·뒤 구간을 하나의 템포 변경으로 연결했습니다. 중간의 박 수와 박 단위는 가정이며, 마디 시작은 확정하지 않았습니다.'),
        'assisted':('기준점 보조 지도','제작자 기준점 3개 + 4/4','제작자 자료에서 첫 박·중간 변경·후반 마디의 시각을 제공했습니다. 앞부분의 변경 위치는 모델 결과를 유지합니다. 자동 분석 성능이나 실제 수작업 횟수로 볼 수 없습니다.'),
        'reference':('제작자 정답 지도','MIDI 기준으로 만든 비교 클릭','제작자가 제공한 MIDI 템포 지도를 같은 4분음표 클릭 소리로 렌더링했습니다. 원본 제작자 클릭과 검증된 범위는 5분 14.527초까지입니다.')}
    variants=[]
    for name,clock in clocks.items():
        label,short,description=descriptions[name]
        variants.append({'id':name,'label':label,'short_description':short,'description':description,
            'status_label':{'previous':'기존 자동 제안 · 미승인','automatic':'조건부 자동 제안 · 연결 가정 미검증',
                            'assisted':'제작자 기준점 보조 · 사용자 청취 검토 전','reference':'제작자 기준 · 분석 결과 아님'}[name],
            'click_url':f'{name}-click.wav','click_sha256':renders[name]['sha256'],'map_url':f'{name}-map.json',
            **({'midi_url':f'{name}-tempo.mid'} if name in exports else {}),
            'beats_seconds':clock['beats_seconds'],'downbeats_seconds':[],
            'tempo_segments':clock['segments'],'metrics':metrics[name],
            'coverage':{'start':lo,'end':hi,'note':'제작자 클릭 검증 범위 밖입니다. 마지막 템포를 원곡 끝까지 연장한 구간입니다.'},
            'provenance':{'source_origin_shift_seconds':0,'source_audio_modified':False,
                'assistance':clock.get('assistance'),'bridge_certified':clock.get('bridge_certified'),
                'musical_origin':'creator-supplied' if name in exports else 'unresolved',
                'reference_sha256':sha256(args.reference) if name in exports else None}})
    boundary=next(c for c in automatic['candidates'] if c['id']==automatic['selected_candidate_id'])['boundary_seconds']
    boundary_delta=boundary-reference['tempo_events'][-1]['time_seconds']
    bundle={'schema_version':1,'default_variant_id':'automatic',
        'source':{'audio_url':'music.wav','sha256':source_hash,'sample_rate':info.samplerate,'sample_frames':info.frames,
                  'duration_seconds':info.duration,'label':args.label},'variants':variants,
        'sections':[{'start':0,'end':36,'label':'도입 · 첫 변경','description':'첫 박과 첫 BPM 변경 부근의 클릭을 비교합니다.'},
            {'start':100,'end':119,'label':'앞부분의 작은 변경','description':'81↔82 BPM의 작은 차이와 변경 시점을 들어봅니다.'},
            {'start':128,'end':165,'label':'중간 연결 · 핵심','description':f'새 자동 후보의 마지막 BPM 변경은 제작자 지도보다 약 {abs(boundary_delta):.2f}초 '+('늦습니다.' if boundary_delta>=0 else '빠릅니다.')+' 조용한 부분에서도 클릭 차이를 비교해 보세요.'},
            {'start':200,'end':244,'label':'모델 불일치 구간','description':'박 시각이 흔들리거나 한 모델이 놓친 구간입니다. 이전 결과와 새 연결 후보를 비교합니다.'},
            {'start':290,'end':info.duration,'label':'후반 · 검증 범위 끝','description':'5분 14.527초 뒤는 제작자 클릭으로 검증하지 못했습니다. 음원은 끝까지 그대로 재생합니다.'}],
        'reference_note':'제작자 MIDI와 별도 CLICK의 420개 4분음표가 소스 시각을 이동하지 않고 검증되었습니다. 실제 녹음에 이 클릭을 사용했는지는 별도 확인되지 않았습니다. 한 곡의 개발용 비교이며 일반화 성능을 뜻하지 않습니다.',
        'analysis_note':'자동 지도와 기준점 보조 지도를 분리합니다. 사용자 청취·수정 시간은 아직 측정하지 않았습니다.'}
    if args.creator_click:
        shutil.copyfile(args.creator_click,output/'creator-original-click.wav')
        bundle['original_creator_click']={'audio_url':'creator-original-click.wav','label':'제작자 원본 클릭 받기 (8분음표)',
                                         'description':'네 개의 비교 클릭은 동일한 4분음표 소리입니다.'}
    write_json(output/'listening-bundle.json',bundle)
    sources=('run_one_song_completion.py','complete_song_clock.py','fit_clock_v2.py','fit_clock.py','clock_candidates.py',
             'compare_clock_candidates.py','grid_metrics.py','build_one_song_listening.py','one_song_listening.html')
    snapshot=output/'source-snapshot';snapshot.mkdir()
    for name in sources:shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    report={'schema_version':1,'source_sha256':source_hash,'source_sample_rate':info.samplerate,'source_frames':info.frames,
        'reference_sha256':sha256(args.reference),'reference_support_seconds':[lo,hi],
        'source_hashes':{name:sha256(snapshot/name) for name in sources},
        'frozen_automatic_before_reference_hash':frozen_automatic_hash,
        'automatic_artifact_unchanged':sha256(output/'automatic-proposal.json')==frozen_automatic_hash,
        'inputs':{key:{'path':str(path),'sha256':sha256(path)} for key,path in
                  [('regions',args.regions),('crossed_report',args.crossed_report),('reference',args.reference),('anchors',args.anchors)]},
        'automatic_boundary_seconds':next(c for c in automatic['candidates'] if c['id']==automatic['selected_candidate_id'])['boundary_seconds'],
        'metrics':metrics,'renders':renders,'midi_exports':exports,
        'human_listening_performed':False,'human_correction_time_measured':False,'accepted':False,
        'limitations':['One previously inspected development song; no holdout claim.',
            'Automatic quarter interpretation and one-step missing-span bridge remain assumptions.',
            'Assisted variant uses creator-derived anchors and 4/4; not automatic accuracy.',
            'Full source coverage is not verified exact tempo-change recovery.',
            'Tail beyond creator click support is not acoustically verified.']}
    write_json(output/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('audio','regions','crossed-report','beat-this-logits','beat-transformer-logits','reference','anchors','output-dir'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--track',required=True);parser.add_argument('--label',default='One song')
    parser.add_argument('--creator-click',type=Path)
    report=run(parser.parse_args())
    print(json.dumps({name:{'event_20ms':value['event_20ms']['f1'],'event_70ms':value['event_70ms']['f1'],
                            'changes_100ms':value['tempo_changes_100ms']['full_change_scores']['true_positives']}
                      for name,value in report['metrics'].items()},indent=2))


if __name__=='__main__':main()
