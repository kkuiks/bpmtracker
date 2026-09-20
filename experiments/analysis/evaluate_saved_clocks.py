"""Compare clock paths on frozen predictions, with no new acoustic inference."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from ablate_clock_inputs import fit_prediction
from inspect_inputs import sha256
from pulse_gaps import infer_pulse_indices
from run_corpus_benchmark import score_events, score_clock
from decode_pulses import decode_pulses, retain_nearby_downbeats


def summarize(rows):
    result = {}
    for dataset in sorted({r['dataset'] for r in rows}):
        selected = [r for r in rows if r['dataset']==dataset]
        methods = {}
        for name in selected[0]['methods']:
            metrics = {}
            for key in ('beats_seconds','downbeats_seconds'):
                eligible = [r for r in selected if r['methods'][name]['scores'][key] is not None]
                metrics[key] = {'count':len(eligible), 'macro_f1':{
                    str(t):float(np.mean([r['methods'][name]['scores'][key][str(t)]['f1'] for r in eligible])) if eligible else None for t in (.02,.07)}}
            delta = [r['methods'][name]['scores']['beats_seconds']['0.07']['f1']-r['methods']['old_clock']['scores']['beats_seconds']['0.07']['f1'] for r in selected]
            methods[name] = {'metrics':metrics,'tracks_improved_over_old_by_1pp':sum(d>.01 for d in delta),
                             'tracks_worsened_over_old_by_1pp':sum(d<-.01 for d in delta),
                             'fallback_count':sum(r['methods'][name].get('status','').startswith('fallback') for r in selected)}
        result[dataset] = {'count':len(selected),'methods':methods}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports',type=Path,nargs='+',required=True)
    parser.add_argument('--catalogs',type=Path,nargs='+',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--decode-meter-free',action='store_true')
    args = parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    args.output_dir.mkdir(parents=True)
    references = {t['id']:t['reference'] for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    tracks = [t for p in args.reports for t in json.loads(p.read_text())['tracks']]
    locations = {t['id']:p.parent/t['id'] for p in args.reports for t in json.loads(p.read_text())['tracks']}
    report = {'configuration':{'source_reports':[{'path':str(p),'sha256':sha256(p)} for p in args.reports],
                              'runner_sha256':sha256(__file__),
                              'source_hashes':{p:sha256(Path(__file__).with_name(p)) for p in ('fit_clock.py','pulse_gaps.py','ablate_clock_inputs.py','decode_pulses.py')},
                              'meter_free_decoder':args.decode_meter_free,
                              'reference_in_prediction':False,'gap_context_intervals_each_side':4,'gap_timing_tolerance_seconds':.06},
              'tracks':[],'complete':False}
    for i,track in enumerate(tracks):
        started = time.perf_counter()
        raw = track['variants']['official_minimal']
        methods = {'official_raw':{'prediction':raw,'clock':None,'status':'unreviewed_original_predictions'},
                   'old_clock':{'prediction':track['variants']['clock_pipeline'],'clock':track['clock'],'status':track['clock_status']}}
        for name,indices,gaps in [('minimal_clock',None,[]),('gap_clock',*infer_pulse_indices(raw['beats_seconds']))]:
            proposal,fitted,status = fit_prediction(raw,indices)
            methods[name] = {'prediction':fitted,'clock':proposal,'status':status,'gap_hypotheses':gaps}
        if args.decode_meter_free:
            logits = np.load(locations[track['id']]/'logits.npz')
            pulses = decode_pulses(logits['beat'],fps=float(logits['fps']))
            downbeats = retain_nearby_downbeats(pulses,raw['downbeats_seconds'])
            prediction = {'beats_seconds':pulses.tolist(),'downbeats_seconds':downbeats.tolist()}
            methods['meter_free_raw'] = {'prediction':prediction,'clock':None,'status':'unreviewed_meter_free_pulses'}
            proposal,fitted,status = fit_prediction(prediction)
            methods['meter_free_clock'] = {'prediction':fitted,'clock':proposal,'status':status}
        record = references[track['id']]
        if sha256(record['path']) != record['sha256']:raise ValueError('reference hash mismatch')
        reference = json.loads(Path(record['path']).read_text())
        for value in methods.values():
            value['scores'] = score_events(reference,value['prediction'],0)
            value['clock_metrics'] = score_clock(reference,value['clock'])
        row = {'id':track['id'],'dataset':track['dataset'],'genre':track['genre'],'methods':methods,
               'reference_sha256':record['sha256'],'elapsed_seconds':time.perf_counter()-started}
        report['tracks'].append(row)
        report['summary'] = summarize(report['tracks'])
        report['complete'] = i+1==len(tracks)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(f"{i+1}/{len(tracks)} {track['id']} {row['elapsed_seconds']:.2f}s",flush=True)
    print(json.dumps(report['summary'],indent=2))


if __name__=='__main__':main()
