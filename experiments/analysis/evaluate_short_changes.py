"""Oracle-input clock-fitting diagnostics; never report as automatic music accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from compare_clock_candidates import evaluate_times
from clock_candidates import tempo_events
from fit_clock import fit_clock, clock_time
from fit_clock_v2 import FitConfig, fit_clock_v2
from grid_metrics import indexed_grid_metrics
from inspect_inputs import sha256


def score_fit(reference, truth, quarter_indices, proposal):
    relative = quarter_indices - quarter_indices[0]
    estimated = clock_time(relative, proposal['knot_pulse_indices'], proposal['coefficients'])
    result = evaluate_times(reference, estimated, tempo_events(proposal))
    result['indexed_oracle_grid'] = indexed_grid_metrics(
        [{'index': float(q), 'time_seconds': float(t)} for q,t in zip(quarter_indices,truth)],
        [{'index': float(q), 'time_seconds': float(t)} for q,t in zip(quarter_indices,estimated)],
        origin_status='shared_explicit_origin')
    result['origin_certification_scope'] = 'oracle fixture indices known by construction; not acoustic inference'
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalogs',type=Path,nargs='+',required=True)
    p.add_argument('--track',nargs='+',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    if args.output_dir.exists():p.error('output must be new')
    entries={t['id']:t for path in args.catalogs for t in json.loads(path.read_text())['tracks']}
    if not set(args.track)<=entries.keys():p.error('missing track IDs')
    args.output_dir.mkdir(parents=True)
    report={'configuration':{'schema_version':'short-change-fit-v2-diagnostic',
              'input_scope':'exact reference pulse indices/times plus controlled noise; oracle diagnostic ONLY',
              'automatic_accuracy_claim':False,'fit_config':FitConfig().__dict__,
              'fitter_v1_sha256':sha256(Path(__file__).with_name('fit_clock.py')),
              'fitter_v2_sha256':sha256(Path(__file__).with_name('fit_clock_v2.py')),
              'evaluator_sha256':sha256(__file__),
              'source_metrics_sha256':sha256(Path(__file__).with_name('compare_clock_candidates.py')),
              'conditions':[{'name':'reference_exact','jitter_seconds':0,'quantization_hz':None},
                            {'name':'reference_jitter_4ms','jitter_seconds':.004,'quantization_hz':None},
                            {'name':'reference_jitter_4ms_50hz','jitter_seconds':.004,'quantization_hz':50}]},
            'tracks':[],'complete':False}
    for track_id in args.track:
        entry=entries[track_id];record=entry['reference']
        if sha256(record['path'])!=record['sha256']:raise ValueError('reference changed')
        reference=json.loads(Path(record['path']).read_text())
        full=np.asarray(reference['beats_seconds'],dtype=float)
        quarters=np.asarray(reference.get('quarter_indices',np.arange(len(full))),dtype=float)
        lo,hi=reference['evaluation_support_seconds'];keep=(full>=lo)&(full<=hi)
        truth=full[keep];quarters=quarters[keep];relative=quarters-quarters[0]
        row={'id':track_id,'dataset':entry['dataset'],'reference_sha256':record['sha256'],
             'oracle_input':True,'conditions':{}}
        seed=int.from_bytes(hashlib.sha256(('short-clock-v2:'+track_id).encode()).digest()[:4],'little')
        for condition in report['configuration']['conditions']:
            observed=truth+np.random.default_rng(seed).normal(0,condition['jitter_seconds'],len(truth))
            if condition['quantization_hz']:
                observed=np.rint(observed*condition['quantization_hz'])/condition['quantization_hz']
            variants={}
            for name,function in [('v1',fit_clock),('v2',fit_clock_v2)]:
                started=time.perf_counter()
                extra={'config':FitConfig(observation_quantization_seconds=1/condition['quantization_hz']
                                         if condition['quantization_hz'] else 0)} if name=='v2' else {}
                proposal=function(observed,pulse_indices=relative,**extra)
                seconds=time.perf_counter()-started
                variants[name]={'proposal':proposal,'metrics':score_fit(reference,truth,quarters,proposal),
                                 'elapsed_seconds':seconds,'input_is_reference_diagnostic':True}
            row['conditions'][condition['name']]={'seed':seed,'variants':variants}
            print(track_id,condition['name'],{k:{'knots':len(v['proposal']['knot_pulse_indices']),
                'matched_changes_100ms':v['metrics']['tempo_changes_100ms']['full_change_scores']['true_positives'],
                'matched_changes_500ms':v['metrics']['tempo_changes_500ms']['full_change_scores']['true_positives'],
                'seconds':round(v['elapsed_seconds'],3)} for k,v in variants.items()},flush=True)
        report['tracks'].append(row);report['complete']=len(report['tracks'])==len(args.track)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
