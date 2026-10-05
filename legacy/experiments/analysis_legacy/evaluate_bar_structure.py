"""Compare fixed/variable bar decoding without changing any pulse timing."""

import argparse
import json
from pathlib import Path

import numpy as np

from decode_bar_structure import bar_path
from inspect_inputs import sha256
from run_corpus_benchmark import score_events
from bar_metrics import score_bar_changes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clock-report',type=Path,required=True)
    parser.add_argument('--baselines',type=Path,nargs='+',required=True)
    parser.add_argument('--catalogs',type=Path,nargs='+',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    clocks=json.loads(args.clock_report.read_text())
    if not clocks['complete']:parser.error('clock comparison incomplete')
    locations={t['id']:p.parent/t['id'] for p in args.baselines for t in json.loads(p.read_text())['tracks']}
    references={t['id']:t['reference'] for p in args.catalogs for t in json.loads(p.read_text())['tracks']}
    report={'scope':'bar proposals on an unchanged meter-free fitted pulse grid',
            'clock_report_sha256':sha256(args.clock_report),'decoder_sha256':sha256(Path(__file__).with_name('decode_bar_structure.py')),
            'runner_sha256':sha256(__file__),'tracks':[]}
    args.output_dir.mkdir(parents=True)
    for t in clocks['tracks']:
        base=t['methods']['meter_free_clock']['prediction']
        logits=np.load(locations[t['id']]/'logits.npz')
        methods={}
        for name,variable in [('fixed',False),('variable',True)]:
            bars=bar_path(base['beats_seconds'],logits['downbeat'],fps=float(logits['fps']),variable=variable)
            methods[name]={'bars':bars,'prediction':{'beats_seconds':list(base['beats_seconds']),'downbeats_seconds':bars['downbeats_seconds']}}
        record=references[t['id']]
        if sha256(record['path'])!=record['sha256']:raise ValueError('reference changed')
        reference=json.loads(Path(record['path']).read_text())
        for m in methods.values():
            m['scores']=score_events(reference,m['prediction'],0)
            m['meter_change_scores']=score_bar_changes(reference,m['bars'])
        report['tracks'].append({'id':t['id'],'dataset':t['dataset'],'methods':methods,
                                 'source_clock_status':t['methods']['meter_free_clock']['status']})
    summary={}
    for dataset in sorted({t['dataset'] for t in report['tracks']}):
        selected=[t for t in report['tracks'] if t['dataset']==dataset]
        summary[dataset]={}
        for name in ('fixed','variable'):
            eligible=[t for t in selected if t['methods'][name]['scores']['downbeats_seconds'] is not None]
            summary[dataset][name]={'downbeat_tracks':len(eligible),'downbeat_macro_f1':{
                str(tol):float(np.mean([t['methods'][name]['scores']['downbeats_seconds'][str(tol)]['f1'] for t in eligible])) for tol in (.02,.07)}}
    report['summary']=summary
    (args.output_dir/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))
    for t in report['tracks']:
        if t['id'].endswith(('Track00005','Track00008','Track00017','Track00018')):
            print(t['id'],[(x['time_seconds'],x['pulses_per_bar']) for x in t['methods']['variable']['bars']['meter_events']],flush=True)


if __name__=='__main__':main()
