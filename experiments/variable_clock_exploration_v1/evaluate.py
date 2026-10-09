"""Evaluation-only worker; annotation coordinates are consumed unchanged."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np

from experiments.metronome_benchmark_v1.metrics import event_f1
from experiments.variable_tempo_step0.common import stored_reference, reference_segments
from tools.project_storage import resolve_path
from .clock import quantize


def read(path):return json.loads(resolve_path(path).read_text())
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False,ensure_ascii=False)+'\n')


def support_pairs(value,duration):
    if not value:return [[0.,duration]]
    return [value] if isinstance(value[0],(int,float)) else value


def reference(row,duration):
    ref=read(row['reference_path']);kind=row['kind']
    if kind=='encoded':
        record=next(r for r in ref['rows'] if r['id']==row['record_id'])
        rates=[60_000_000/e['value'] for e in record['source_clock']['tempos']]
        return {'rate_only':True,'rates':rates,'support':[],'segments':[],'quarters':[],
                'limits':'encoded source rates only; MIDI/audio origin unresolved'}
    support=support_pairs(row.get('support_seconds') or ref.get('support_seconds'),duration)
    if kind=='step0':
        segments=ref['labeled_segments'];quarters=ref['stored_quarter_events']
    elif kind=='gtzan':
        segments=[{'start_seconds':a,'end_seconds':b,'quarter_bpm':ref['pulse_bpm']} for a,b in support]
        quarters=ref['beat_times_seconds']
    elif kind=='generated':
        segments=[{'start_seconds':a,'end_seconds':b,'quarter_bpm':ref['quarter_bpm']} for a,b in support]
        quarters=ref['quarter_times_seconds']
    elif 'tempo_events' in ref:
        segments=reference_segments(ref,support);quarters=stored_reference(ref,support)['quarter_times_seconds']
    else:
        segments=[{'start_seconds':a,'end_seconds':b,'quarter_bpm':ref['quarter_bpm']} for a,b in support]
        quarters=ref['beat_times_seconds']
    changes=[]
    for left,right in zip(segments,segments[1:]):
        if abs(left['end_seconds']-right['start_seconds'])<1e-5 and quantize(left['quarter_bpm'])!=quantize(right['quarter_bpm']):
            changes.append({'time':right['start_seconds'],'left_bpm':quantize(left['quarter_bpm']),
                            'right_bpm':quantize(right['quarter_bpm'])})
    no_grid=ref.get('evaluation_scope',{}).get('no_grid_tail_seconds')
    return {'rate_only':False,'rates':[s['quarter_bpm'] for s in segments],
            'segments':segments,'quarters':quarters,'changes':changes,'support':support,'no_grid':no_grid}


def close(predicted,true,octave=False,exact=False):
    scales=(.5,1,2) if octave else (1,)
    return any(abs(predicted*scale-quantize(true))<1e-8 if exact else
               abs(predicted*scale/true-1)<=.01 for scale in scales)


def boundary_counts(predicted,true,octave=False):
    choices=[]
    for i,p in enumerate(predicted):
        for j,r in enumerate(true):
            error=abs(p['time']-r['time'])
            scales=(.5,1,2) if octave else (1,)
            rate_match=any(close(p['left_bpm']*s,r['left_bpm'],exact=True) and
                           close(p['right_bpm']*s,r['right_bpm'],exact=True) for s in scales)
            if error<=.5 and rate_match:choices.append((error,i,j))
    used_p=set();used_r=set();errors=[]
    for error,i,j in sorted(choices):
        if i not in used_p and j not in used_r:used_p.add(i);used_r.add(j);errors.append(error)
    tp=len(errors);fp=len(predicted)-tp;fn=len(true)-tp
    return {'tp':tp,'fp':fp,'fn':fn,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 1.,
            'absolute_error_seconds_matched':errors}


def click_events(prediction):
    events=[];unknown=prediction.get('unknown_intervals_seconds',[])
    for region in prediction['regions']:
        p,phase=region['nominal_period'],region['nominal_phase']
        first=math.ceil((region['start']-phase)/p)
        last=math.ceil((region['end']-phase)/p)
        events.extend(t for t in phase+np.arange(first,last)*p if not any(a<=t<b for a,b in unknown))
    return np.array(sorted(set(events)))


def score(prediction,ref,duration):
    regions=prediction['regions']
    if ref['rate_only']:
        recovered=[any(close(r['bpm'],rate,octave=True,exact=True) for r in regions) for rate in ref['rates']]
        return {'rate_only':True,'rate_targets':len(recovered),'octave_rate_recovered_anywhere':sum(recovered),
                'phase_or_boundary_scored':False}
    total=exact=near=folded=0.;segment_majority=segment_family=0;segment_rows=[]
    for seg in ref['segments']:
        start,end,bpm=seg['start_seconds'],seg['end_seconds'],seg['quarter_bpm'];length=end-start
        same=family=0.
        for r in regions:
            lo,hi=max(start,r['start']),min(end,r['end']);overlap=max(0,hi-lo)
            intervals=sorted([max(lo,a),min(hi,b)] for a,b in prediction.get('unknown_intervals_seconds',[]) if max(lo,a)<min(hi,b))
            merged=[]
            for a,b in intervals:
                if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
                else:merged.append([a,b])
            overlap=max(0,overlap-sum(b-a for a,b in merged))
            exact+=overlap*close(r['bpm'],bpm,exact=True)
            near+=overlap*close(r['bpm'],bpm)
            folded+=overlap*close(r['bpm'],bpm,octave=True)
            same+=overlap*close(r['bpm'],bpm,exact=True)
            family+=overlap*close(r['bpm'],bpm,octave=True,exact=True)
        total+=length;segment_majority+=same>=length*.5;segment_family+=family>=length*.5
        segment_rows.append({'start':start,'end':end,'reference_bpm':bpm,
                             'nominal_native_rate_fraction':same/length,
                             'nominal_octave_family_rate_fraction':family/length})
    predicted=click_events(prediction)
    inside=lambda ts:np.asarray([t for t in ts if any(a<=t<b for a,b in ref['support'])])
    predicted_inside=inside(predicted);true=inside(ref['quarters'])
    boundaries=[p for p in prediction['boundaries'] if p.get('kind')=='rate_change'
                and any(a<p['time']<b for a,b in ref['support'])]
    phase={str(ms):event_f1(predicted_inside,true,ms/1000) for ms in (20,70)}
    tail=ref.get('no_grid')
    return {'rate_only':False,'reference_duration':total,'reference_segments':len(ref['segments']),
            'reference_changes':len(ref['changes']),'predicted_rate_changes':len(boundaries),
            'nominal_native_rate_time_fraction':exact/total if total else 0,
            'native_rate_within_1_percent_time_fraction':near/total if total else 0,
            'octave_rate_within_1_percent_time_fraction':folded/total if total else 0,
            'nominal_native_rate_majority_segments':int(segment_majority),
            'nominal_octave_family_majority_segments':int(segment_family),'segment_rows':segment_rows,
            'quarter_event_f1':phase,'boundary_native':boundary_counts(boundaries,ref['changes']),
            'boundary_shared_octave':boundary_counts(boundaries,ref['changes'],True),
            'no_grid_tail_extra_clicks':int(sum(tail[0]<=t<tail[1] for t in predicted)) if tail else None,
            'abstention_or_failure':not bool(regions)}


def aggregate(rows):
    full=[r['score'] for r in rows if not r['score'].get('rate_only')]
    if not full:return {'inputs':len(rows),'rate_only_inputs':len(rows)}
    result={'inputs':len(rows),'timing_scored_inputs':len(full),
            'failed_or_abstained':sum(r['abstention_or_failure'] for r in full),
            'reference_segments':sum(r['reference_segments'] for r in full),
            'nominal_native_rate_majority_segments':sum(r['nominal_native_rate_majority_segments'] for r in full),
            'nominal_octave_family_majority_segments':sum(r['nominal_octave_family_majority_segments'] for r in full),
            'native_rate_within_1_percent_macro':float(np.mean([r['native_rate_within_1_percent_time_fraction'] for r in full])),
            'octave_rate_within_1_percent_macro':float(np.mean([r['octave_rate_within_1_percent_time_fraction'] for r in full])),
            'quarter_macro_f1_20ms':float(np.mean([r['quarter_event_f1']['20']['f1'] for r in full])),
            'quarter_macro_f1_70ms':float(np.mean([r['quarter_event_f1']['70']['f1'] for r in full]))}
    fixed=[r for r in full if r['reference_changes']==0]
    result.update(fixed_inputs=len(fixed),fixed_inputs_with_rate_changes=sum(r['predicted_rate_changes']>0 for r in fixed),
                  fixed_rate_change_count=sum(r['predicted_rate_changes'] for r in fixed))
    for key in ('boundary_native','boundary_shared_octave'):
        tp=sum(r[key]['tp'] for r in full);fp=sum(r[key]['fp'] for r in full);fn=sum(r[key]['fn'] for r in full)
        errors=[e for r in full for e in r[key]['absolute_error_seconds_matched']]
        result[key]={'tp':tp,'fp':fp,'fn':fn,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 1.,
                     'matched_error_median':float(np.median(errors)) if errors else None}
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--stage',choices=['calibration','frozen'],required=True);a=p.parse_args()
    protocol=read(a.run/'protocol.json');sources={r['id']:r for r in read(a.run/'source-inputs.json')['samples']}
    index=read(a.run/'evaluation-index.json')['rows']
    folder=a.run/f'{a.stage}-predictions'
    if not read(folder/'receipt.json')['completed']:raise ValueError('Prediction stage incomplete')
    expected={r['id'] for r in index if r['id'] in protocol['calibration_ids']} if a.stage=='calibration' else set(sources)
    for config in sorted(d for d in folder.iterdir() if d.is_dir()):
        available={p.stem for p in config.glob('*.json')}
        required=expected if config.name.endswith('-neural') else {r['id'] for r in sources.values() if r.get('audio_path')}
        if not required.issubset(available):raise ValueError(f'Incomplete prediction configuration: {config.name}')
    summaries={};all_rows={};selection={}
    for config in sorted(d for d in folder.iterdir() if d.is_dir()):
        rows=[]
        for row in index:
            path=config/f"{row['id']}.json"
            if not path.exists():continue
            prediction=read(path);ref=reference(row,sources[row['id']]['duration_seconds'])
            rows.append({'id':row['id'],'role':row['role'],'score':score(prediction,ref,sources[row['id']]['duration_seconds'])})
        groups=defaultdict(list)
        for row in rows:groups[row['role']].append(row)
        summaries[config.name]={key:aggregate(value) for key,value in groups.items()};all_rows[config.name]=rows
        if a.stage=='calibration':
            synthetic=[r for r in rows if r['role']=='synthetic_calibration' and r['score'].get('reference_changes',0)>0]
            fixed=[r for r in rows if not r['score'].get('rate_only') and r['score']['reference_changes']==0]
            sg=aggregate(synthetic);fg=aggregate(fixed)
            value=.5*sg['boundary_shared_octave']['f1']+.25*(1-fg['fixed_inputs_with_rate_changes']/max(len(fixed),1))+.25*fg['quarter_macro_f1_70ms']
            selection[config.name]={'objective':value,'synthetic':sg,'fixed':fg}
    write(a.run/f'{a.stage}-evaluation.json',{'summaries':summaries,'rows':all_rows})
    if a.stage=='calibration':
        chosen={}
        for method in protocol['methods']:
            options=[(r['objective'],float(name.split('-p')[1].split('-')[0]),name) for name,r in selection.items() if name.startswith(method+'-')]
            chosen[method]=max(options)[1]
        write(a.run/'calibration-selection.json',{'criterion':'.5 synthetic shared-octave boundary F1 + .25 fixed no-change proportion + .25 fixed quarter F1@70ms',
                                                 'rows':selection,'real_references_used':False,'selected':chosen})
        write(a.run/'selected-config.json',chosen);print('SELECTED',json.dumps(chosen),flush=True)
    else:
        for config,groups in summaries.items():
            if 'real_variable' in groups:print(config,json.dumps(groups['real_variable']),flush=True)


if __name__=='__main__':main()
