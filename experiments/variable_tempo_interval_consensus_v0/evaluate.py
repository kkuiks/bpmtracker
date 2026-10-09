"""Independent evaluator; approved clocks enter only after source predictions exist."""
import argparse
from collections import defaultdict
from pathlib import Path
import math
import numpy as np
from experiments.variable_clock_exploration_v1.evaluate import reference
from experiments.metronome_benchmark_v1.metrics import event_f1
from .core import quantize
from .io import read,write


def nearest_error(value,events):
    if not len(events):return np.full(len(value),np.inf)
    k=np.searchsorted(events,value)
    return np.minimum(abs(value-events[np.clip(k-1,0,len(events)-1)]),abs(value-events[np.clip(k,0,len(events)-1)]))


def events(spans,bar=False):
    result=[]
    for r in spans:
        if bar and r.get('bar_status')!='SUPPORTED':continue
        period=r.get('bar_period',4*r['period']) if bar else r['period']
        phase=r['bar_phase'] if bar else r['phase']
        first=math.ceil((r['start']-phase)/period);last=math.ceil((r['end']-phase)/period)
        result.extend((phase+np.arange(first,last)*period).tolist())
    return np.array(sorted(set(result)))


def score(prediction,row,duration,prepared_reference=None):
    ref=prepared_reference if prepared_reference is not None else reference(row,duration)
    if row['scope']=='rate_only' or ref['rate_only']:
        rates=ref['rates'];episodes=prediction.get('episodes',[])
        return dict(rate_only=True,inputs=1,target_rates=len(rates),
                    target_rates_present=sum(any(abs(r['bpm']-quantize(rate))<1e-8 for r in episodes) for rate in rates))
    dt=.02;t=np.arange(.01,duration,dt)
    support=np.zeros(len(t),dtype=bool);truth=np.full(len(t),np.nan)
    for a,b in ref['support']:support|=(t>=a)&(t<b)
    for s in ref['segments']:truth[(t>=s['start_seconds'])&(t<s['end_seconds'])]=quantize(s['quarter_bpm'])
    support&=np.isfinite(truth)
    quarters=np.array(ref['quarters']);quarters.sort();bars=np.array(row.get('bar_events',[]));bars.sort()
    selected=np.zeros(len(t),dtype=bool);correct=np.zeros(len(t),dtype=bool);correct_rate=np.zeros(len(t),dtype=bool)
    bar_selected=np.zeros(len(t),dtype=bool);bar_correct=np.zeros(len(t),dtype=bool)
    scopes=prediction.get('initial_information_scope')
    for r in prediction.get('accepted',[]):
        use=(t>=r['start'])&(t<r['end']);selected|=use
        positions=np.flatnonzero(use&support)
        if not len(positions):continue
        q=r['phase']+np.rint((t[positions]-r['phase'])/r['period'])*r['period']
        rate=abs(truth[positions]-r['bpm'])<1e-8
        correct_rate[positions]|=rate
        correct[positions]|=rate&(nearest_error(q,quarters)<=.070)
        if r.get('bar_status')=='SUPPORTED':
            bar_selected|=use
            period=r.get('bar_period',4*r['period']);b=r['bar_phase']+np.rint((t[positions]-r['bar_phase'])/period)*period
            bar_correct[positions]|=rate&(nearest_error(b,bars)<=.070)
    ambiguous=np.zeros(len(t),dtype=bool)
    for a in prediction.get('ambiguous',[]):ambiguous|=(t>=a['start'])&(t<a['end'])
    proposed=np.zeros(len(t),dtype=bool);proposed_correct=np.zeros(len(t),dtype=bool)
    for r in prediction.get('episodes',[]):
        use=(t>=r['start'])&(t<r['end']);proposed|=use
        positions=np.flatnonzero(use&support)
        if not len(positions):continue
        q=r['phase']+np.rint((t[positions]-r['phase'])/r['period'])*r['period']
        proposed_correct[positions]|=(abs(truth[positions]-r['bpm'])<1e-8)&(nearest_error(q,quarters)<=.070)
    denominator=max(int(support.sum()),1)
    wrong=(selected&support)&~correct
    predicted=events(prediction.get('accepted',[]));predicted_bars=events(prediction.get('accepted',[]),True)
    in_support=lambda values:np.array([v for v in values if any(a<=v<b for a,b in ref['support'])])
    predicted=in_support(predicted);predicted_bars=in_support(predicted_bars)
    qtrue=in_support(quarters);btrue=in_support(bars)
    errors=nearest_error(predicted,qtrue);berrors=nearest_error(predicted_bars,btrue)
    exact_changes=sum(quantize(a['quarter_bpm'])!=quantize(b['quarter_bpm']) for a,b in zip(ref['segments'],ref['segments'][1:]))
    segment_rows=[]
    for s in ref['segments']:
        use=support&(t>=s['start_seconds'])&(t<s['end_seconds']);n=max(int(use.sum()),1)
        segment_rows.append(dict(start=s['start_seconds'],end=s['end_seconds'],nominal_bpm=quantize(s['quarter_bpm']),
                                 correct_time_fraction=float(correct[use].sum()/n),rate_fraction=float(correct_rate[use].sum()/n),
                                 proposal_containing_correct_fraction=float(proposed_correct[use].sum()/n)))
    initial_mask=support&(t>=scopes[0])&(t<scopes[1]) if scopes else np.zeros(len(t),dtype=bool)
    after=support&~initial_mask
    first_end=ref['segments'][0]['end_seconds'] if ref['segments'] else 0.
    overrun=initial_mask&(t>=first_end)
    return dict(rate_only=False,scope=row['scope'],reference_seconds=float(support.sum()*dt),reference_segments=len(ref['segments']),reference_changes=exact_changes,
                correct_fraction=float(correct.sum()/denominator),wrong_fraction=float(wrong.sum()/denominator),
                selected_fraction=float((selected&support).sum()/denominator),rate_fraction=float(correct_rate.sum()/denominator),
                ambiguity_fraction=float((ambiguous&support).sum()/denominator),unknown_fraction=float((support&~selected&~ambiguous).sum()/denominator),
                proposal_oracle_containing_fraction=float(proposed_correct.sum()/denominator),proposal_oracle_is_not_automatic_accuracy=True,
                bar_selected_fraction=float((bar_selected&support).sum()/denominator),bar_correct_fraction=float(bar_correct.sum()/denominator),
                quarter_f1={str(ms):event_f1(predicted,qtrue,ms/1000) for ms in (20,30,70)},
                bar_f1={str(ms):event_f1(predicted_bars,btrue,ms/1000) for ms in (20,30,70)},
                quarter_maximum_nearest_error_seconds=float(errors.max()) if len(errors) else None,
                bar_maximum_nearest_error_seconds=float(berrors.max()) if len(berrors) else None,
                quarter_unmatched_70ms=int(np.sum(errors>.070)),bar_unmatched_70ms=int(np.sum(berrors>.070)),
                accepted_regions=len(prediction.get('accepted',[])),proposal_regions=len(prediction.get('episodes',[])),
                initial_scope_seconds=float(initial_mask.sum()*dt),initial_correct_fraction=float(correct[initial_mask].sum()/max(initial_mask.sum(),1)),
                initial_scope_beyond_true_first_segment_seconds=float(overrun.sum()*dt),
                after_initial_correct_fraction=float(correct[after].sum()/max(after.sum(),1)),
                supported_claim_outside_reference_seconds=float((selected&~support).sum()*dt),
                source_failure=prediction.get('candidate_preparation_status')=='failed' or prediction.get('status') in ('failed','missing','inference_failed'),
                abstained=not bool(prediction.get('accepted')),segment_rows=segment_rows)


def aggregate(rows):
    scored=[r['score'] for r in rows if not r['score'].get('rate_only')]
    if not scored:return dict(inputs=len(rows),rate_only=True)
    result=dict(inputs=len(rows),timing_inputs=len(scored),failed=sum(s['source_failure'] for s in scored),abstained=sum(s['abstained'] for s in scored))
    for key in ('correct_fraction','wrong_fraction','selected_fraction','rate_fraction','ambiguity_fraction','unknown_fraction',
                'proposal_oracle_containing_fraction','bar_selected_fraction','bar_correct_fraction','after_initial_correct_fraction'):
        result[key+'_macro']=float(np.mean([s[key] for s in scored]))
    result['reference_seconds']=sum(s['reference_seconds'] for s in scored)
    result['reference_segments']=sum(s['reference_segments'] for s in scored)
    result['accepted_regions']=sum(s['accepted_regions'] for s in scored)
    result['quarter_f1_70_macro']=float(np.mean([s['quarter_f1']['70']['f1'] for s in scored]))
    result['bar_f1_70_macro']=float(np.mean([s['bar_f1']['70']['f1'] for s in scored]))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--stage',choices=['calibration','frozen'],required=True);a=p.parse_args()
    receipt=read(a.run/f'{a.stage}-receipt.json')
    if not receipt['completed'] or receipt['exceptions']:raise ValueError('Source stage incomplete')
    protocol=read(a.run/'protocol.json');source={r['id']:r for r in read(a.run/'source-inputs.json')['samples']}
    index=read(a.run/'evaluation-index.json')['rows'];calibration=set(protocol['calibration_ids'])
    if a.stage=='calibration':index=[r for r in index if r['id'] in calibration]
    refs={row['id']:reference(row,source[row['id']]['duration_seconds']) for row in index}
    full={};summaries={};selection=[]
    for condition in sorted(p for p in (a.run/f'{a.stage}-predictions').iterdir() if p.is_dir()):
        for policy in sorted(p for p in condition.iterdir() if p.is_dir()):
            rows=[]
            for row in index:
                path=policy/f"{row['id']}.json"
                if not path.exists():raise ValueError(f'Missing prediction {condition.name}/{policy.name}/{row["id"]}')
                result=score(read(path),row,source[row['id']]['duration_seconds'],refs[row['id']])
                rows.append(dict(id=row['id'],original_id=row['original_id'],role=row['role'],scope=row['scope'],parent_group=row.get('parent_group'),variant=row.get('variant'),score=result))
            groups=defaultdict(list)
            for r in rows:
                if r['scope']=='quarter4':groups[r['role']].append(r)
                else:groups['diagnostic_'+r['scope']].append(r)
            key=condition.name+'/'+policy.name;full[key]=rows;summaries[key]={role:aggregate(v) for role,v in groups.items()}
            if a.stage=='calibration' and policy.name=='initial_exact':
                variable=[r for r in rows if not r['score'].get('rate_only') and r['score']['reference_changes']>0]
                fixed=[r for r in rows if not r['score'].get('rate_only') and r['score']['reference_changes']==0]
                constructed_fixed=[r for r in fixed if r['role']!='gtzan_development']
                v=aggregate(variable);f=aggregate(constructed_fixed)
                wrong=f.get('wrong_fraction_macro',0);coverage=v.get('correct_fraction_macro',0)
                selection.append(dict(name=condition.name,constructed_fixed_wrong=wrong,variable_correct=coverage,
                                      fixed_correct=f.get('correct_fraction_macro',0),target_met=wrong<=.01))
    write(a.run/f'{a.stage}-evaluation.json',dict(rows=full,summaries=summaries,reference_read_after_source_predictions=True))
    if a.stage=='calibration':
        feasible=[r for r in selection if r['target_met']]
        candidates=feasible or selection
        chosen=max(candidates,key=lambda r:(r['variable_correct']+.25*r['fixed_correct']-(0 if feasible else 2*r['constructed_fixed_wrong']),r['name']))
        configuration=read(a.run/'calibration-configurations.json')[chosen['name']]
        write(a.run/'selected-config.json',dict(name=chosen['name'],configuration=configuration,calibration_target_met=bool(feasible),
              useful_variable_coverage=chosen['variable_correct']>.05,selection=chosen,all_candidates=selection,
              selection_criterion='Among <=1% constructed-fixed wrong-time conditions maximize variable correct-time + .25 fixed correct-time; if infeasible disclose and penalize wrong-time',
              primary_real_scores_not_used=True,prospective_parent_scores_not_used=True))
        print('SELECTED',chosen,configuration,flush=True)
    else:
        for key,roles in summaries.items():
            if 'real_variable' in roles:print(key,roles['real_variable'],flush=True)


if __name__=='__main__':main()
