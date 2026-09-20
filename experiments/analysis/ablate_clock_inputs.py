"""Isolate event decoding from clock fitting using saved baseline predictions.

Reference-input fits are diagnostic controls, never deployable predictions or
inputs to a selector. The same frozen fitter is applied to every event stream.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from fit_clock import fit_clock, propose_splits, clock_time, grid_events
from inspect_inputs import sha256
from run_corpus_benchmark import score_clock, score_events
from run_beat_this import validate_events


def fit_prediction(prediction, pulse_indices=None):
    beats = validate_events(prediction['beats_seconds'])
    if len(beats) < 8 or len(beats) > 2000:
        return None, dict(prediction), 'fallback_event_count_budget'
    if len(propose_splits(beats, pulse_indices=pulse_indices))-1 > 12:
        return None, dict(prediction), 'fallback_segment_budget'
    try:
        proposal = fit_clock(beats, pulse_indices=pulse_indices)
    except ValueError as error:
        return None, dict(prediction), 'fallback_invalid_fit: '+str(error)
    observed_grid = clock_time(proposal['input_pulse_indices'], proposal['knot_pulse_indices'], proposal['coefficients'])
    grid = grid_events(proposal)
    down = np.asarray(prediction['downbeats_seconds'])
    if not np.isin(down, beats).all():
        raise ValueError('downbeat predictions must be a subset of beat predictions')
    down_grid = observed_grid[np.searchsorted(beats, down)]
    fitted = {'beats_seconds':grid[grid >= 0].tolist(),'downbeats_seconds':down_grid[down_grid >= 0].tolist()}
    return proposal, fitted, proposal['status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--catalogs', type=Path, nargs='+', required=True)
    parser.add_argument('--track', nargs='*', help='optional IDs; omission evaluates all supplied tracks')
    parser.add_argument('--include-reference-control', action='store_true')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():parser.error('output directory must be new')
    references = {t['id']:t['reference'] for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    selected = [t for p in args.reports for t in json.loads(p.read_text())['tracks'] if not args.track or t['id'] in args.track]
    if args.track and set(args.track) != {t['id'] for t in selected}:parser.error('some requested IDs are missing')
    args.output_dir.mkdir(parents=True)
    report = {'scope':'frozen-fitter input ablation; oracle controls excluded from deployable comparisons',
              'baseline_reports':[{'path':str(p),'sha256':sha256(p)} for p in args.reports],
              'runner_sha256':sha256(__file__),'fitter_sha256':sha256(Path(__file__).with_name('fit_clock.py')),
              'tracks':[]}
    for track in selected:
        record = references[track['id']]
        if sha256(record['path']) != record['sha256']:raise ValueError('reference changed')
        reference = json.loads(Path(record['path']).read_text())
        inputs = {name:track['variants'][name] for name in ('official_minimal','legacy_dbn')}
        if args.include_reference_control:
            inputs['reference_control'] = {'beats_seconds':reference['beats_seconds'], 'downbeats_seconds':reference['downbeats_seconds'] or []}
        row = {'id':track['id'],'dataset':track['dataset'],'reference_sha256':record['sha256'],'inputs':{}}
        for name,prediction in inputs.items():
            proposal,fitted,status = fit_prediction(prediction)
            row['inputs'][name] = {'diagnostic_only':name=='reference_control','status':status,
                                  'clock':proposal,'fitted_prediction':fitted,
                                  'raw_scores':score_events(reference,prediction,0),
                                  'fitted_scores':score_events(reference,fitted,0),'clock_metrics':score_clock(reference,proposal)}
            print(track['id'],name,'segments',len(proposal['segments']) if proposal else None,
                  'clock',row['inputs'][name]['clock_metrics'],flush=True)
        report['tracks'].append(row)
        (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
