"""Evaluation after serialization; scores the map actually used by the native click."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np

from experiments.multiple_rhythm_continuity_v1.common import PRIMARY_READINGS
from experiments.multiple_rhythm_continuity_v1.references import inside,templates,arrays
from experiments.multiple_rhythm_continuity_v1.metrics import match_arrays,score as pulse_score
from experiments.variable_clock_composition_v1.evaluate import score as canonical_score
from experiments.metronome_benchmark_v1.metrics import event_f1
from .common import SOURCE,FIXED,POLICIES,read,write,guard,digest,stamp
from .map import sections,validate,as_legacy_prediction,grid

def native_arrays(prediction,times):
    fields={k:np.full(len(times),np.nan) for k in ['bpm','phase','numerator','denominator']}
    for s in sections(prediction):
        use=(times>=s['start'])&(times<s['end'])
        for key in fields:fields[key][use]=s[key]
    return fields

def validity(fields,times,reference):
    alternatives=templates(reference,PRIMARY_READINGS)
    pulse=match_arrays(fields['bpm']*fields['denominator']/4,fields['phase'],times,reference,alternatives)
    _,region,support=arrays(times,reference)
    bars=np.zeros(len(times),dtype=bool);exact_meter=bars.copy();canonical_rate=bars.copy()
    for index,state in enumerate(reference['states']):
        use=support&(region==index)&np.isfinite(fields['bpm'])
        if not use.any():continue
        predicted_period=60/fields['bpm'][use]*fields['numerator'][use]*4/fields['denominator'][use]
        reference_period=60/state['bpm']*state['numerator']*4/state['denominator']
        available=np.asarray(reference['bars']);anchors=available[(available>=state['start']-1e-7)&(available<state['end']-1e-7)]
        anchor=float(anchors[0]) if len(anchors) else float(available[np.argmin(abs(available-state['start']))]) if len(available) else state['start']
        ticks=fields['phase'][use]+np.rint((times[use]-fields['phase'][use])/predicted_period)*predicted_period
        phase_error=abs((ticks-anchor+reference_period/2)%reference_period-reference_period/2)
        bars[use]=(abs(predicted_period/reference_period-1)<=.005+1e-12)&(phase_error<=.07+1e-12)
        exact_meter[use]=(fields['numerator'][use]==state['numerator'])&(fields['denominator'][use]==state['denominator'])
        canonical_rate[use]=abs(fields['bpm'][use]/state['bpm']-1)<=.005+1e-12
    return pulse,bars,exact_meter,canonical_rate,support

def classify_events(prediction,reference):
    segments=sections(prediction);records=[]
    for event in prediction.get('events',[]):
        time=event['time'];kind='TEMPO_AND_METER' if 'bpm'in event and 'numerator'in event else 'TEMPO' if 'bpm'in event else 'METER'
        record={**event,'kind':kind}
        if not inside(np.asarray([time]),reference['support'])[0]:
            record['classification']='OUTSIDE_APPROVED_SCOPE';records.append(record);continue
        before=next((s for s in reversed(segments) if s['start']<time-1e-8),None)
        after=next((s for s in segments if s['start']>=time-1e-8),None)
        if before is None or after is None:raise RuntimeError('Missing event neighbor')
        def acceptable(section,where):
            fields={k:np.asarray([section[k]],float) for k in ['bpm','phase','numerator','denominator']}
            pulse,bar,_,_,_=validity(fields,np.asarray([where]),reference)
            return bool(pulse[:,0].any() and bar[0])
        legitimate=[]
        for index in range(1,len(reference['states'])):
            left,right=reference['states'][index-1:index+1];boundary=right['start']
            tempo_change=abs(left['bpm']-right['bpm'])>1e-8
            meter_change=(left['numerator'],left['denominator'])!=(right['numerator'],right['denominator'])
            compatible_kind=('bpm' in event and tempo_change) or ('numerator' in event and meter_change)
            if compatible_kind and abs(time-boundary)<=4 and acceptable(before,boundary-1e-5) and acceptable(after,boundary+1e-5):
                legitimate.append({'reference_time':boundary,'error_seconds':time-boundary})
        if legitimate:
            record.update(classification='MUSICAL_CHANGE',matches=legitimate)
        else:
            old_after=acceptable(before,time+1e-4);new_after=acceptable(after,time+1e-4)
            old_before=acceptable(before,time-1e-4)
            record.update(old_valid_before=old_before,old_still_valid_after=old_after,new_valid_after=new_after)
            record['classification']='UNNECESSARY_CHANGE' if old_after or old_before and new_after else 'RECOVERY' if new_after else 'UNSUPPORTED_CHANGE'
        records.append(record)
    return records

def score(prediction,reference):
    times=np.arange(.025,max(b for _,b in reference['support']),.05)
    fields=native_arrays(prediction,times);pulse,bar,meter,rate,support=validity(fields,times,reference)
    n=int(support.sum());coherent=np.zeros(len(times),bool);joint=coherent.copy();choices=[]
    for state in reference['states']:
        use=support&(times>=state['start'])&(times<state['end'])
        if not use.any():continue
        pulse_counts=pulse[:,use].sum(axis=1);joint_counts=(pulse[:,use]&bar[use]).sum(axis=1)
        winner=int(np.argmax(joint_counts));pulse_winner=int(np.argmax(pulse_counts))
        coherent[use]=pulse[pulse_winner,use];joint[use]=pulse[winner,use]&bar[use]
        choices.append({'start':state['start'],'end':state['end'],'reading':PRIMARY_READINGS[winner]['name'],
                        'native_map_valid_fraction':float(joint_counts[winner]/use.sum())})
    changes=classify_events(prediction,reference)
    penalty=np.zeros(len(times),bool)
    for event in changes:
        if event['classification']=='UNNECESSARY_CHANGE':penalty|=(times>=event['time'])&(times<event['time']+8)
    fraction=lambda mask:float((mask&support).sum()/n)
    native_bars=grid(prediction,'bar');native_bars=native_bars[inside(native_bars,reference['support'])]
    return {'native_pulse_coherent_fraction':fraction(coherent),'native_map_valid_fraction':fraction(joint),
            'stable_native_map_fraction':fraction(joint&~penalty),'bar_period_and_phase_fraction':fraction(bar),
            'canonical_declared_meter_fraction':fraction(meter),'canonical_quarter_rate_fraction':fraction(rate),
            'native_coverage_fraction':fraction(np.isfinite(fields['bpm'])),
            'native_bar_f1_70':event_f1(native_bars,np.asarray(reference['bars']),.07),
            'native_changes':changes,'unnecessary_native_changes':sum(e['classification']=='UNNECESSARY_CHANGE' for e in changes),
            'unsupported_native_changes':sum(e['classification']=='UNSUPPORTED_CHANGE' for e in changes),
            'musical_native_changes':sum(e['classification']=='MUSICAL_CHANGE' for e in changes),
            'native_tempo_changes':sum('bpm'in e for e in prediction.get('events',[])),
            'native_meter_changes':sum('numerator'in e for e in prediction.get('events',[])),
            'native_region_readings':choices,'native_map_legality':validate(prediction)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);args=parser.parse_args();run=args.run;guard(run)
    index=read(run/'evaluation-index.json')['rows'];rows=[];contracts=[];same_unit=[]
    for item in index:
        ident=item['id'];ref=read(item['reference_path'])
        for method in ['C0_CONSTANT_MAP','C1_CONTINUOUS_MAP']:
            for policy in POLICIES:
                pred=read(run/'predictions'/method/policy/(ident+'.json'))
                legacy=as_legacy_prediction(pred);old=pulse_score(legacy,ref);canonical=canonical_score(legacy,item,ref)
                record={**{k:item[k] for k in ['id','original_id','title','role','partition','model_seeded_reference_diagnostic_only']},
                        'method':method,'policy':policy,**score(pred,ref),
                        'comparable_quarter_pulse_stable_fraction':old['stable_valid_fraction'],
                        'comparable_quarter_unnecessary_changes':old['unnecessary_changes'],
                        'canonical_strict_successful_transitions':canonical['successful_transitions'],
                        'canonical_strict_eligible_transitions':canonical['eligible_transitions'],
                        'canonical_transition_details':canonical['transitions']}
                rows.append(record);contracts.append({'id':ident,'method':method,'policy':policy,**validate(pred)})
            primary=read(run/'predictions'/method/'proxy100'/(ident+'.json'));primary.pop('policy')
            for policy in ['proxy97','proxy103']:
                other=read(run/'predictions'/method/policy/(ident+'.json'));other.pop('policy')
                packet=read(run/'encoded-units'/policy/(ident+'.json'));p0=read(run/'encoded-units/proxy100'/(ident+'.json'))
                same_unit.append({'id':ident,'method':method,'policy':policy,'same_unit':packet==p0,
                                  'identical_prediction':other==primary})
        print('SCORED',ident,flush=True)
    common={x['id'] for x in read(FIXED/'selection.json')['primary_common_complete_recordings']}
    summary=[]
    for method in ['C0_CONSTANT_MAP','C1_CONTINUOUS_MAP']:
        for policy in POLICIES:
            for group in ['all32','fixed13','fixed17','variable10','meter5']:
                selected=[r for r in rows if r['method']==method and r['policy']==policy and not r['model_seeded_reference_diagnostic_only']
                          and (group=='all32' or group=='fixed13' and r['id']in common or group=='fixed17' and r['role']=='fixed_control'
                               or group=='variable10' and r['role']=='variable' or group=='meter5' and r['role']=='meter_control')]
                if not selected:continue
                fields=['native_pulse_coherent_fraction','native_map_valid_fraction','stable_native_map_fraction',
                        'bar_period_and_phase_fraction','canonical_declared_meter_fraction','canonical_quarter_rate_fraction',
                        'native_coverage_fraction','comparable_quarter_pulse_stable_fraction']
                summary.append({'method':method,'policy':policy,'group':group,'inputs':len(selected),
                                **{key:float(np.mean([r[key] for r in selected])) for key in fields},
                                **{key:sum(r[key] for r in selected) for key in ['unnecessary_native_changes','unsupported_native_changes',
                                    'native_tempo_changes','native_meter_changes','canonical_strict_successful_transitions','canonical_strict_eligible_transitions']},
                                'useful_native_maps':sum(r['stable_native_map_fraction']>=.85 and r['native_coverage_fraction']>=.95 and r['unnecessary_native_changes']==0 for r in selected)})
    before=read(SOURCE/'metrics.json');hashes={**read(run/'input-freeze.json')['files'],**read(run/'source-before-tap-freeze.json')['files']}
    changed=[path for path,sha in hashes.items() if digest(path)!=sha]
    workers=[read(p) for p in sorted((run/'worker-audit').glob('*.json'))];forbidden=sum(len(w['forbidden_reads']) for w in workers)
    passed=not changed and not forbidden and all(c['legal'] and c['continuous_source_coverage'] for c in contracts) and all(not p['same_unit'] or p['identical_prediction'] for p in same_unit)
    write(run/'metrics.json',{'rows':rows,'summary':summary,'baseline_summary':before['summary'],
                            'historical_baseline_is_quarter_pulse_only_not_full_native_map':True})
    write(run/'audit.json',{'at_utc':stamp(),'all_pass':passed,'map_contracts':contracts,'same_unit_pairs':same_unit,
                          'changed_inputs':changed,'input_hashes_checked':len(hashes),'source_forbidden_reads':forbidden,
                          'worker_audits':len(workers),'native_windows_playback_not_tested':True})
    if not passed:raise RuntimeError('Map experiment contract audit failed')
    print('EVALUATED',len(rows),'AUDIT',passed,flush=True)

if __name__=='__main__':main()
