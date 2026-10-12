"""Native project conversion and evaluation-only accepted-map compatibility audit."""
from __future__ import annotations
import argparse
import math
import os
from pathlib import Path
import uuid
import numpy as np
from experiments.multiple_rhythm_continuity_v1.references import seconds
from experiments.metronome_benchmark_v1.metrics import event_f1
from .common import read,write,guard,digest,stamp
from .map import validate,grid

def reference_map(item,normalized):
    raw=read(item['canonical_reference_path']);states=normalized['states']
    tempos=[{'time':seconds(e),'bpm':float(e.get('bpm_quarter',e.get('bpm',e.get('quarter_bpm'))))} for e in raw.get('tempo_events',[])]
    if not tempos:tempos=[{'time':0.,'bpm':float(raw.get('quarter_bpm',normalized['initial_bpm']))}]
    tempos.sort(key=lambda e:e['time']);initial_rate=[e for e in tempos if e['time']<=0][-1]['bpm'] if any(e['time']<=0 for e in tempos) else tempos[0]['bpm']
    meters=[{'time':seconds(e),'numerator':int(e['numerator']),'denominator':int(e['denominator'])} for e in raw.get('meter_events',[])]
    if not meters:meters=[{'time':0.,'numerator':states[0]['numerator'],'denominator':states[0]['denominator']}]
    meters.sort(key=lambda e:e['time']);initial_meter=[e for e in meters if e['time']<=0][-1] if any(e['time']<=0 for e in meters) else meters[0]
    n,d=initial_meter['numerator'],initial_meter['denominator'];bar_seconds=60/initial_rate*n*4/d
    first_bar=float(normalized['bars'][0]) if normalized['bars'] else float(normalized['quarters'][0])
    # The first accepted bar belongs to the initial signature for these inputs.
    # Keep the explicit owner/source bar anchor when available.
    origin=float(raw.get('bar_anchor_audio_seconds',first_bar-bar_seconds*math.ceil(first_bar/bar_seconds-1e-10)))
    changes=[];last_rate=initial_rate
    for event in tempos:
        if event['time']>0 and abs(event['bpm']-last_rate)>1e-10:
            changes.append(event);last_rate=event['bpm']
    def quarter(time):
        value=-origin*initial_rate/60;at=0.;rate=initial_rate
        for event in changes:
            if event['time']>time+1e-8:break
            value+=(event['time']-at)*rate/60;at=event['time'];rate=event['bpm']
        return value+(time-at)*rate/60
    events={};simultaneous=[]
    def event_at(time):
        # The source stores simultaneous tempo/meter declarations using arithmetic
        # that can differ below a nanosecond. Merge that numerical identity; do
        # not snap any genuinely different declaration to a neighboring beat.
        key=next((k for k in events if abs(k-time)<1e-8),time)
        if key!=time:simultaneous.append({'kept_source_time':key,'other_source_time':time,'difference_seconds':time-key})
        return events.setdefault(key,{'time':key,'quarter':quarter(key)})
    for event in changes:event_at(event['time'])['bpm']=event['bpm']
    previous=(n,d)
    for event in meters:
        current=event['numerator'],event['denominator']
        if event['time']>0 and current!=previous:
            event_at(event['time']).update(numerator=current[0],denominator=current[1])
        previous=current
    return {'format':'joljak-continuous-beat-map','version':1,'status':'map','duration_seconds':item['duration_seconds'],
            'initial':{'bpm':initial_rate,'numerator':n,'denominator':d,'bar_zero_source_seconds':origin},
            'events':sorted(events.values(),key=lambda e:e['time']),
            'reference_conversion_only':True,'accepted_reference_sha256':item['reference_sha256'],
            'original_bpm_precision_preserved':True,'reference_not_resnapped_or_shifted':True,
            'simultaneous_numeric_declarations_merged':simultaneous}

def uuid_for(value):return str(uuid.uuid5(uuid.NAMESPACE_URL,'joljak-continuous-map:'+value))

def project(prediction,row,title,variant,destination):
    check=validate(prediction)
    if not check['legal']:raise ValueError(('Cannot export illegal native map',check))
    initial=prediction['initial'];bpm=initial['bpm'];n,d=initial['numerator'],initial['denominator']
    # Whole-bar lead-in is outside the recording. Audio-relative timing is exact.
    lead_q=2*n*4/d
    origin=lead_q*60/bpm-initial['bar_zero_source_seconds']
    source=Path(row['audio_path']);stat=source.stat();identity=row['id']+':'+variant+':'+str(destination)
    asset_id=uuid_for(str(source));track_id=uuid_for(identity+':track');clip_id=uuid_for(identity+':clip')
    tempos=[];signatures=[];previous_q=0.;previous_bar=1;previous_length=n*4/d
    for i,event in enumerate(prediction['events']):
        q=event['quarter']+lead_q
        if 'bpm'in event:tempos.append({'id':uuid_for(identity+f':tempo{i}'),'quarter':q,'bpm':event['bpm'],'origin':'manual'})
        if 'numerator'in event:
            bar=previous_bar+math.ceil((q-previous_q)/previous_length-1e-8)
            signatures.append({'id':uuid_for(identity+f':signature{i}'),'quarter':q,'bar':bar,
                               'numerator':event['numerator'],'denominator':event['denominator'],'origin':'manual'})
            previous_q,previous_bar,previous_length=q,bar,event['numerator']*4/event['denominator']
    return {'format':'joljak-project','version':3,'id':uuid_for(identity),'name':f'{title} — {variant}',
        'bpm':bpm,'signature':{'numerator':n,'denominator':d},'tempos':tempos,'signatures':signatures,
        'assets':[{'id':asset_id,'name':source.name,'sourcePath':os.path.relpath(source,destination.parent),
                   'pcmPath':'','peaksPath':'','sampleRate':row['sample_rate'],'channels':row['channels'],
                   'frames':row['sample_frames'],'duration':row['duration_seconds'],'peakBinFrames':1024,
                   'peakBins':math.ceil(row['sample_frames']/1024),'originalSize':stat.st_size,'originalModified':stat.st_mtime*1000}],
        'tracks':[{'id':track_id,'name':title,'color':'#5f9ec8','gain':.6,'pan':0,'mute':False,'solo':False,'timeBase':'linear'}],
        'clips':[{'id':clip_id,'trackId':track_id,'assetId':asset_id,'name':title,'start':origin,
                  'sourceStart':0,'duration':row['duration_seconds'],'groupId':None}],
        'clocks':[],'analyses':[],'masterGain':1.,'clickGain':.7*10**(.6),'clickGainPolicy':'review-plus6-v1',
        'sampleRate':48000,'notes':f'{variant}. Play the project metronome. Audio source begins at {origin:.6f} seconds.',
        'projectDuration':origin+row['duration_seconds']+2,'rulerFormat':'seconds','timingPolicy':'persistent'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--audit-references',action='store_true');args=parser.parse_args();run=args.run;guard(run)
    index=read(run/'evaluation-index.json')['rows'];sources={r['id']:r for r in read(run/'source-inputs.json')['samples']}
    compatibility=[];refs={}
    for item in index:
        ref=read(item['reference_path']);converted=reference_map(item,ref);refs[item['id']]=converted
        check=validate(converted)
        quarters=grid(converted,'quarter');bars=grid(converted,'bar')
        use=lambda values:values[np.logical_or.reduce([(values>=a)&(values<b) for a,b in ref['support']])]
        qscore=event_f1(use(quarters),np.asarray(ref['quarters']),.07);bscore=event_f1(use(bars),np.asarray(ref['bars']),.07)
        compatibility.append({'id':item['id'],'title':item['title'],**check,
                              'quarter_f1_70':qscore,'bar_f1_70':bscore,
                              'accepted_reference_unchanged':digest(item['canonical_reference_path'])==item['reference_sha256']})
        write(run/'native-reference-maps'/(item['id']+'.json'),converted)
    write(run/'reference-compatibility.json',{'rows':compatibility,'references_not_shifted_resnapped_or_excluded':True})
    if args.audit_references:
        print('REFERENCE_COMPATIBILITY',sum(r['legal'] for r in compatibility),'/',len(compatibility),flush=True);return
    metrics=read(run/'metrics.json')['rows'];primary=[r for r in metrics if r['method']=='C1_CONTINUOUS_MAP' and r['policy']=='proxy100' and not r['model_seeded_reference_diagnostic_only']]
    suitable={r['id'] for r in compatibility if r['legal'] and r['bar_f1_70']['f1']>.98 and r['quarter_f1_70']['f1']>.98}
    chosen=[]
    def choose(rows):
        for r in sorted(rows,key=lambda r:(r['stable_native_map_fraction'],r['id'])):
            if r['id']in suitable and r['id']not in chosen:chosen.append(r['id']);return
    choose([r for r in primary if r['role']=='fixed_control'])
    choose([r for r in primary if r['role']=='variable'])
    if 'r005'in suitable:chosen.append('r005')
    choose([r for r in primary if r['role']=='variable'])
    manifest=[];by_id={r['id']:r for r in index}
    for ident in chosen:
        item=by_id[ident];row=sources[ident];prediction=read(run/'predictions/C1_CONTINUOUS_MAP/proxy100'/(ident+'.json'))
        for variant,mapping in [('reference',refs[ident]),('current',prediction)]:
            target=run/'listen-projects'/ident/(variant+'.joljak');native=project(mapping,row,item['title'],variant,target);write(target,native)
            write(target.with_suffix('.map.json'),mapping)
            manifest.append({'id':ident,'title':item['title'],'variant':variant,'project_path':str(target),
                             'map_path':str(target.with_suffix('.map.json')),'audio_path':row['audio_path'],
                             'audio_project_origin_seconds':native['clips'][0]['start'],'source_start_seconds':0.,
                             'source_duration_seconds':row['duration_seconds'],'approved_support_source_seconds':read(item['reference_path'])['support'],
                             'project_metronome':True,'click_audio_tracks':0,'project_sha256':digest(target)})
    write(run/'listen-projects/manifest.json',{'created_at_utc':stamp(),'pairs':len(chosen),'rows':manifest,
        'selection_rule':'lowest full native-map scores in fixed and variable groups; Juno meter case; second variable failure',
        'audio_not_copied_or_stretched':True,'source_originals_and_accepted_references_unchanged':True,
        'paired_maps_have_explicit_whole_bar_lead_in_outside_audio':True})
    print('NATIVE_PAIRS',len(chosen),chosen,flush=True)

if __name__=='__main__':main()
