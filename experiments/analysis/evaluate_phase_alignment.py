"""Evaluate frozen shared-phase proposals without reading labels in prediction.

Uses the previous soft-prior experiment's existing development cases. Audio is
never shifted. Whole maps receive at most one bounded phase offset; partial
regions remain partial, and accepted/user-anchored maps are not inputs.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import time

import numpy as np
import soundfile as sf

from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_times
from grid_metrics import nearest_event_diagnostics
from inspect_inputs import sha256
from phase_alignment import AttackConfig, PhaseConfig, BANDS, _band_profile, extract_attacks, propose_phase, shifted_clock


METHODS=('unchanged','pooled_calibrated','uncalibrated_consensus','calibrated_consensus')


def save(path,data):
    with Path(path).open('x') as handle:json.dump(data,handle,indent=2,allow_nan=False);handle.write('\n')


def pooled_phase(beats,attacks,calibration,config):
    profiles=[]
    for band in BANDS:
        cal=calibration['bands'][band]
        if not cal['eligible']:continue
        evidence=attacks['bands'][band];events=np.asarray(evidence['seconds']);rise=np.asarray(evidence['rise_seconds'])
        profile=_band_profile(np.asarray(beats),events[rise<=.008]-cal['bias_seconds'],config)
        profiles.append(profile)
    # A source-only comparator without per-window agreement or abstention.
    shift=float(np.median([p['offset_seconds'] for p in profiles])) if profiles else 0.
    return {'status':'ungated_pooled_comparator','applied_shift_seconds':shift,'reference_used_for_prediction':False,'profiles':profiles}


def summarize(rows):
    summary={}
    for scope,cohort,model in sorted({(r['scope'],r['cohort'],r['model']) for r in rows}):
        selected=[r for r in rows if (r['scope'],r['cohort'],r['model'])==(scope,cohort,model)]
        item={'case_count':len(selected),'distinct_songs':len({r['track_id'] for r in selected}),'methods':{}}
        for name in METHODS:
            values=[r['methods'][name] for r in selected]
            item['methods'][name]={
                'mean_f1_'+threshold:float(np.mean([v['metrics']['event_'+threshold]['f1'] for v in values]))
                for threshold in ('10ms','20ms','70ms')}
            changes=[v['metrics']['tempo_changes_100ms']['full_change_scores'] for v in values if v['metrics']['tempo_changes_100ms']['status']=='scored']
            item['methods'][name].update(changed_cases=sum(abs(v['proposal']['applied_shift_seconds'])>1e-9 for v in values),
                changes_100ms={k:sum(v[k] for v in changes) for k in ('true_positives','false_positives','false_negatives')})
        delta=[r['methods']['calibrated_consensus']['metrics']['event_20ms']['f1']-r['methods']['unchanged']['metrics']['event_20ms']['f1'] for r in selected]
        item['consensus_vs_unchanged']={'improved_over_1pp':sum(v>.01 for v in delta),'regressed_over_1pp':sum(v<-.01 for v in delta),'within_1pp':sum(abs(v)<=.01 for v in delta)}
        summary['/'.join((scope,cohort,model))]=item
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-report',required=True,type=Path)
    parser.add_argument('--catalogs',required=True,type=Path,nargs='+')
    parser.add_argument('--calibration',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--attack-cache',required=True,type=Path)
    args=parser.parse_args()
    if args.output_dir.exists():parser.error('output must be new')
    calibration=json.loads(args.calibration.read_text())
    if calibration['source_hashes']['phase_alignment.py']!=sha256(Path(__file__).with_name('phase_alignment.py')):
        parser.error('calibration and current feature implementation differ')
    prior=json.loads(args.prior_report.read_text());config=PhaseConfig();attack_config=AttackConfig(**calibration['configuration'])
    records={t['id']:t for path in args.catalogs for t in json.loads(path.read_text())['tracks']}
    output=args.output_dir;output.mkdir(parents=True);args.attack_cache.mkdir(parents=True,exist_ok=True)
    snapshot=output/'source-snapshot';snapshot.mkdir()
    files=('phase_alignment.py','calibrate_phase_attacks.py','evaluate_phase_alignment.py','compare_clock_candidates.py','grid_metrics.py','clock_candidates.py')
    for name in files:shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    configuration={'schema_version':'shared-phase-evaluation-v1','phase':asdict(config),'attacks':asdict(attack_config),
        'source_hashes':{n:sha256(snapshot/n) for n in files},
        'prior_report':{'path':str(args.prior_report),'sha256':sha256(args.prior_report)},
        'calibration':{'path':str(args.calibration),'sha256':sha256(args.calibration)},
        'catalogs':[{'path':str(p),'sha256':sha256(p)} for p in args.catalogs],
        'reference_used_for_prediction':False,'held_out_evaluation':False,'default_promoted':False,
        'scope':'source-supported constant phase proposal per existing map, same 23 development songs',
        'partial_evaluation':'same original observation window as prior benchmark',
        'limitations':['Correlated frequency details are not independent instruments.',
            'Synthetic attack timing does not certify musical beat locations.',
            'One common shift cannot repair rate drift, wrong pulse level or nonuniform performed timing.',
            'Do not apply this proposal to user-accepted or anchored maps.']}
    save(output/'configuration.json',configuration)
    rows=[];feature_manifest=[]
    for track_id in sorted({r['track_id'] for r in prior['rows']}):
        started=time.perf_counter();record=records[track_id];source=record['input']
        if sha256(source['path'])!=source['sha256']:raise ValueError('source audio changed')
        feature_file=args.attack_cache/(track_id+'.json')
        if feature_file.exists():
            attacks=json.loads(feature_file.read_text())
            if (attacks['audio_sha256']!=source['sha256'] or attacks['feature_sha256']!=configuration['source_hashes']['phase_alignment.py'] or
                    attacks['configuration']!=asdict(attack_config)):
                raise ValueError('cached attacks have incompatible provenance')
        else:
            audio,rate=sf.read(source['path'],dtype='float32',always_2d=True)
            if (rate,len(audio))!=(record['sample_rate'],record['sample_frames']):raise ValueError('source sample geometry differs')
            attacks=extract_attacks(audio,rate,attack_config)
            attacks.update(audio_sha256=source['sha256'],feature_sha256=configuration['source_hashes']['phase_alignment.py'])
            save(feature_file,attacks)
        feature_manifest.append({'track_id':track_id,'path':str(feature_file),'sha256':sha256(feature_file),
                                 'source_sha256':source['sha256'],'elapsed_seconds':time.perf_counter()-started})
        uncalibrated=deepcopy(calibration)
        for band in uncalibrated['bands'].values():band['bias_seconds']=0.
        for case in (r for r in prior['rows'] if r['track_id']==track_id):
            baseline=case['methods']['soft_prior'];beats=baseline['prediction'];clock=baseline['clock'];methods={}
            for method in METHODS:
                if method=='unchanged' or clock is None:
                    proposal={'status':'unchanged_baseline' if clock else 'no_clock_fallback','applied_shift_seconds':0.}
                elif method=='pooled_calibrated':proposal=pooled_phase(beats,attacks,calibration,config)
                else:proposal=propose_phase(beats,attacks,uncalibrated if method=='uncalibrated_consensus' else calibration,config)
                shift=proposal['applied_shift_seconds']
                fitted=shifted_clock(clock,shift,record['duration_seconds']) if clock is not None and shift else clock
                predicted=[v+shift for v in beats if 0<=v+shift<record['duration_seconds']]
                if clock is not None:
                    assert fitted['coefficients'][1:]==clock['coefficients'][1:]
                    assert fitted['knot_pulse_indices']==clock['knot_pulse_indices']
                methods[method]={'clock':fitted,'prediction':predicted,'proposal':proposal}
            row={k:case[k] for k in ('id','track_id','scope','cohort','model')}
            if 'fixed_evaluation_window' in case:row['fixed_evaluation_window']=case['fixed_evaluation_window']
            row.update(methods=methods,source_sha256=source['sha256'],feature_sha256=sha256(feature_file))
            destination=output/(case['id']+'.json');save(destination,row)
            row.update(prediction_path=str(destination),prediction_sha256_before_reference=sha256(destination));rows.append(row)
        print('PREDICT',track_id,round(time.perf_counter()-started,2),[(r['id'].split('__')[-1],r['methods']['calibrated_consensus']['proposal']['applied_shift_seconds']) for r in rows if r['track_id']==track_id],flush=True)
    save(output/'features.json',feature_manifest)
    # All proposal files now exist; only the scoring stage opens labels.
    for row in rows:
        record=records[row['track_id']]['reference']
        if sha256(record['path'])!=record['sha256']:raise ValueError('reference changed')
        reference=json.loads(Path(record['path']).read_text());row['reference_sha256']=record['sha256']
        if row['scope']=='partial_region':
            a,b=reference['evaluation_support_seconds'];lo,hi=row['fixed_evaluation_window']
            reference={**reference,'evaluation_support_seconds':[max(a,lo),min(b,hi)]}
        lo,hi=reference['evaluation_support_seconds'];truth=[t for t in reference['beats_seconds'] if lo<=t<=hi]
        for value in row['methods'].values():
            metrics=evaluate_times(reference,value['prediction'],tempo_events(value['clock']) if value['clock'] else None)
            predicted=[t for t in value['prediction'] if lo<=t<=hi]
            metrics['event_10ms']=nearest_event_diagnostics(truth,predicted,.01)
            value['metrics']=metrics
        assert sha256(row['prediction_path'])==row['prediction_sha256_before_reference']
    report={'configuration':configuration,'rows':rows,'summary':summarize(rows),'complete':True}
    assert all(sha256(Path(__file__).with_name(n))==v for n,v in configuration['source_hashes'].items())
    save(output/'report.json',report);print(json.dumps(report['summary'],indent=2))


if __name__=='__main__':main()
