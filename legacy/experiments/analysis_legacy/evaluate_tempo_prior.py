"""Frozen, source-only tempo-prior ablation on cached development evidence.

All predictions are saved before any reference labels are opened. Full clocks,
partial regions and a conditional full-song assembly are reported separately.
This runner never selects a map or prior strength with reference scores.
"""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import shutil
import time

import numpy as np

from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from complete_song_clock import assemble_clock
from decode_pulses import decode_pulses
from fit_clock import clock_time
from inspect_inputs import sha256
from tempo_prior import PriorConfig, refine_tempo_clock


METHODS=('existing','continuous_refit','soft_prior')


def save(path,value):
    with Path(path).open('x') as handle:
        json.dump(value,handle,indent=2,allow_nan=False);handle.write('\n')


def prediction(clock,duration,span=None):
    lo,hi=span or clock['pulse_index_span']
    q=np.arange(np.ceil(lo),np.floor(hi)+1)
    values=clock_time(q,clock['knot_pulse_indices'],clock['coefficients'])
    return values[(values>=0)&(values<duration)].tolist()


def summarize(rows):
    output={}
    for scope,cohort,model in sorted({(r['scope'],r['cohort'],r['model']) for r in rows}):
        subset=[r for r in rows if (r['scope'],r['cohort'],r['model'])==(scope,cohort,model)]
        summary={'case_count':len(subset),'distinct_songs':len({r['track_id'] for r in subset}),'methods':{}}
        for method in METHODS:
            metrics=[r['methods'][method]['metrics'] for r in subset]
            summary['methods'][method]={key:float(np.mean([m[key]['f1'] for m in metrics])) for key in ('event_20ms','event_70ms')}
            changes=[m['tempo_changes_100ms']['full_change_scores'] for m in metrics if m['tempo_changes_100ms']['status']=='scored']
            summary['methods'][method]['changes_100ms']={k:sum(m[k] for m in changes) for k in ('true_positives','false_positives','false_negatives')}
        for control in ('existing','continuous_refit'):
            delta=[r['methods']['soft_prior']['metrics']['event_20ms']['f1']-r['methods'][control]['metrics']['event_20ms']['f1'] for r in subset]
            summary['vs_'+control]={'improved_over_1pp':sum(d>.01 for d in delta),'regressed_over_1pp':sum(d<-.01 for d in delta),
                                    'within_1pp':sum(abs(d)<=.01 for d in delta)}
        output['/'.join((scope,cohort,model))]=summary
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--meter-free-report',type=Path,required=True)
    parser.add_argument('--cross-reports',type=Path,nargs='+',required=True)
    parser.add_argument('--region-report',type=Path,required=True)
    parser.add_argument('--catalogs',type=Path,nargs='+',required=True)
    parser.add_argument('--light-completion',type=Path,required=True)
    parser.add_argument('--strength',type=float,default=1.,help='predeclared sensitivity setting; never chosen with labels')
    args=parser.parse_args();output=args.output_dir
    if output.exists():parser.error('output directory must be new')
    config=PriorConfig(strength=args.strength)
    records={t['id']:t for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    jobs=[];verified=set()
    def check_audio(track_id):
        record=records[track_id]
        if track_id not in verified:
            if sha256(record['input']['path'])!=record['input']['sha256']:raise ValueError('source audio changed')
            verified.add(track_id)
        return record
    # Raw decoded pulses are retained in this baseline report; never fit a
    # previously smoothed grid as if it were independent acoustic evidence.
    for row in json.loads(args.meter_free_report.read_text())['tracks']:
        if row['id'] not in records:continue
        record=check_audio(row['id']);method=row['methods']['meter_free_clock']
        clock=method['clock'];raw=row['methods']['meter_free_raw']['prediction']['beats_seconds']
        jobs.append({'id':row['id']+'__beat_this__full','track_id':row['id'],'model':'beat_this','scope':'full_clock',
            'cohort':record['dataset'],'duration':record['duration_seconds'],'clock':clock,
            'times':raw,'indices':clock['input_pulse_indices'] if clock else None,'quantization':.02,
            'baseline_prediction':method['prediction']['beats_seconds'],'baseline_source':str(args.meter_free_report)})
    cross_rows=[r for p in args.cross_reports for r in json.loads(p.read_text())['tracks']]
    for row in cross_rows:
        record=check_audio(row['id'])
        for model,provenance in row['model_provenance'].items():
            if any(j['track_id']==row['id'] and j['model']==model and j['scope']=='full_clock' for j in jobs):continue
            if sha256(provenance['logits_path'])!=provenance['logits_sha256']:raise ValueError('model evidence changed')
            values=np.load(provenance['logits_path']);fps=float(values['fps'])
            if any(k in values and float(values[k])!=0 for k in ('source_frame_offset','frame_time_offset_seconds')):
                raise ValueError('nonzero frame origin')
            raw=decode_pulses(values['beat'],fps=fps);raw=raw[(raw>=0)&(raw<record['duration_seconds'])]
            method=row['methods'][model+'__clock_current'];clock=method['clock']
            if clock and len(raw)!=clock['input_event_count']:raise ValueError('decoded input differs from frozen clock')
            jobs.append({'id':row['id']+'__'+model+'__full','track_id':row['id'],'model':model,'scope':'full_clock',
                'cohort':record['dataset'],'duration':record['duration_seconds'],'clock':clock,
                'times':raw.tolist(),'indices':clock['input_pulse_indices'] if clock else None,'quantization':1/fps,
                'baseline_prediction':method['prediction']['beats_seconds'],'baseline_source':provenance})
    # One evidence-ranked candidate per retained region, without changing the
    # pulse level/phase choice in response to validation results.
    for row in json.loads(args.region_report.read_text())['tracks']:
        if row['id'] not in records:continue
        record=check_audio(row['id'])
        for model,path in row['candidate_sets'].items():
            candidates=json.loads(Path(path).read_text());fps=float(np.load(candidates['input_provenance']['logits_path'])['fps'])
            for region in sorted({c['region']['id'] for c in candidates['candidates']}):
                chosen=max((c for c in candidates['candidates'] if c['region']['id']==region),key=lambda c:c['evidence_score_not_confidence'])
                indexed=chosen['input_event_indexing'];phase=chosen['phase_offset_quarters']
                jobs.append({'id':row['id']+'__'+model+'__region'+str(region),'track_id':row['id'],'model':model,
                    'scope':'partial_region','cohort':record['dataset'],'duration':record['duration_seconds'],
                    'clock':chosen['clock'],'times':indexed['source_seconds'],
                    'indices':(np.asarray(indexed['quarter_positions'])-phase).tolist(),'quantization':1/fps,
                    'baseline_prediction':[v['source_seconds'] for v in chosen['indexed_grid']],
                    'fixed_evaluation_window':[min(indexed['source_seconds']),max(indexed['source_seconds'])],
                    'selected_candidate_id':chosen['id'],'baseline_source':{'path':path,'sha256':sha256(path)}})
    output.mkdir(parents=True);snapshot=output/'source-snapshot';snapshot.mkdir()
    names=('tempo_prior.py','evaluate_tempo_prior.py','complete_song_clock.py','fit_clock_v2.py','fit_clock.py',
           'compare_clock_candidates.py','grid_metrics.py','decode_pulses.py','legacy_dbn.py','clock_candidates.py')
    for name in names:shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    configuration={'schema_version':'tempo-prior-ablation-v1','prior':asdict(config),
        'source_hashes':{name:sha256(snapshot/name) for name in names},
        'inputs':[{'path':str(p),'sha256':sha256(p)} for p in
                  [args.meter_free_report,*args.cross_reports,args.region_report,*args.catalogs]],
        'cases':[{'id':j['id'],'track_id':j['track_id'],'scope':j['scope'],'model':j['model']} for j in jobs],
        'default_promoted':False,'unseen_validation':False,'reference_used_for_prediction':False,
        'selection_rule':'frozen correlated-noise Huber loss plus simple-rate preference; continuous escape permitted',
        'limitations':['Previously inspected development examples.','BabySlakh 09/12/20 authored semantics unresolved.',
            'Three creator songs share one artist group.','Topology, indexing and acoustic-model failures are not repaired here.',
            'Partial-region scores are not whole-song performance.']}
    save(output/'configuration.json',configuration)
    rows=[]
    for job in jobs:
        started=time.perf_counter();methods={};baseline=job['clock']
        for name in METHODS:
            if name=='existing' or baseline is None:
                methods[name]={'clock':baseline,'prediction':job['baseline_prediction'],
                               'status':'frozen_baseline' if baseline else 'unchanged_no_clock_fallback'}
                continue
            try:
                fit=refine_tempo_clock(job['times'],job['indices'],baseline,
                    replace(config,quantization_seconds=job['quantization'],strength=0 if name=='continuous_refit' else config.strength))
                methods[name]={'clock':fit,'prediction':prediction(fit,job['duration'],baseline['pulse_index_span']),
                               'status':'refitted_unaccepted_proposal'}
            except ValueError as error:
                methods[name]={'clock':baseline,'prediction':job['baseline_prediction'],'status':'unchanged_rejected_refit',
                               'reason':str(error)}
        row={k:v for k,v in job.items() if k not in ('clock','times','indices','baseline_prediction')}
        row.update(methods=methods,elapsed_seconds=time.perf_counter()-started)
        path=output/(job['id']+'.json');save(path,{'case':row,'observations':{'source_seconds':job['times'],'pulse_indices':job['indices']}})
        row['prediction_path']=str(path);row['prediction_sha256_before_reference']=sha256(path);rows.append(row)
        print('PREDICT',job['id'],round(row['elapsed_seconds'],2),
              methods['soft_prior']['clock'].get('rate_constraints_bpm') if methods['soft_prior']['clock'] else 'no_clock',flush=True)
    # Reassemble the actual one-song completion with both control and prior.
    original=json.loads((args.light_completion/'automatic-proposal.json').read_text())
    region_path=Path('data/runs/candidate-clock/region-restart-v2/forestry_light-has-come/beat_this/candidates.json')
    regions=json.loads(region_path.read_text());light=next(r for r in cross_rows if r['id']=='forestry_light-has-come')
    observations={m:light['methods'][m+'__common_minimal']['prediction']['beats_seconds'] for m in light['model_provenance']}
    logits={}
    for model,info in light['model_provenance'].items():
        values=np.load(info['logits_path']);logits[model]=(values['beat'],float(values['fps']))
    methods={}
    for method in METHODS:
        assembled=original if method=='existing' else assemble_clock(regions,observations,logits,light['source']['duration_seconds'],
            tempo_prior_config=replace(config,strength=0 if method=='continuous_refit' else config.strength))
        clock=next(c['clock'] for c in assembled['candidates'] if c['id']==assembled['selected_candidate_id'])
        methods[method]={'clock':clock,'prediction':clock['beats_seconds'],'status':'conditional_bridge_not_certified','assembly':assembled}
    row={'id':'forestry_light-has-come__combined__completion','track_id':'forestry_light-has-come','model':'combined',
         'scope':'conditional_completion','cohort':records['forestry_light-has-come']['dataset'],'methods':methods}
    path=output/(row['id']+'.json');save(path,row);row['prediction_path']=str(path)
    row['prediction_sha256_before_reference']=sha256(path);rows.append(row)
    # Evaluation begins only after ALL source-only predictions are saved.
    report={'configuration':configuration,'rows':[],'complete':False}
    for row in rows:
        record=records[row['track_id']]['reference']
        if sha256(record['path'])!=record['sha256']:raise ValueError('reference changed')
        reference=json.loads(Path(record['path']).read_text());row['reference_sha256']=record['sha256']
        if row['scope']=='partial_region':
            lo,hi=row['fixed_evaluation_window'];a,b=reference['evaluation_support_seconds']
            reference={**reference,'evaluation_support_seconds':[max(a,lo),min(b,hi)]}
        for method,value in row['methods'].items():
            value['metrics']=evaluate_times(reference,value['prediction'],tempo_events(value['clock']) if value['clock'] else None)
        assert sha256(row['prediction_path'])==row['prediction_sha256_before_reference']
        report['rows'].append(row)
    report['summary']=summarize(rows);report['complete']=True
    assert all(sha256(Path(__file__).with_name(name))==digest for name,digest in configuration['source_hashes'].items())
    save(output/'report.json',report)
    print(json.dumps(report['summary'],indent=2))


if __name__=='__main__':main()
