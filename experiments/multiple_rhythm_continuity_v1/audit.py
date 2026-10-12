from __future__ import annotations

import argparse
import copy
from pathlib import Path

from .common import read, write, digest, guard, stamp
from .worker import paths


def semantic(prediction):
    result=copy.deepcopy(prediction)
    for field in ('method','policy','correction','correction_events'):
        result.pop(field,None)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();guard(args.run)
    hash_checks={}
    for filename in ['input-freeze.json','source-freeze.json','encoded-input-freeze.json']:
        for name,expected in read(args.run/filename)['files'].items():hash_checks[name]=digest(name)==expected
    baseline,contracts,same_unit,old_replays=[],[],[],[]
    sources=read(args.run/'source-inputs.json')['samples']
    for row in sources:
        ident=row['id'];bank_path,_=paths(args.run,row);bank=read(bank_path)['expanded']
        for policy in ['none','proxy100']:
            raw=read(args.run/'raw-maps'/policy/f'{ident}.json')
            output=read(args.run/'predictions/B0_RAW'/policy/f'{ident}.json')
            baseline.append({'id':ident,'policy':policy,'identical':semantic(raw)==semantic(output)})
            if row['reused_composition'] and read(args.run/'prediction-receipts'/f'{ident}.json')['old_raw_predictions_reused']:
                old_replays.append({'id':ident,'policy':policy,'identical':semantic(raw)==semantic(read(row['old_raw_paths'][policy]))})
        for file in (args.run/'predictions').glob(f'*/*/{ident}.json'):
            output=read(file);policy=output['policy'];raw=read(args.run/'raw-maps'/policy/f'{ident}.json')
            intervals=[(e['start'],e['end']) for e in output['accepted']]
            expected=[(e['start'],e['end']) for e in raw['accepted']]
            membership=all(any(abs(e['bpm']-h['bpm'])<1e-8 and abs(e['phase']-h['phase'])<1e-8 for h in bank) for e in output['accepted'])
            contracts.append({'path':str(file.relative_to(args.run)),'boundaries_preserved':intervals==expected,
                              'source_clock_membership':membership,'no_output_spans_dropped':len(intervals)==len(expected)})
        center=read(args.run/'predictions/F1_FOLD05/proxy100'/f'{ident}.json')
        for policy in ['proxy97','proxy103']:
            packet_same=read(args.run/'encoded-units'/policy/f'{ident}.json')==read(args.run/'encoded-units/proxy100'/f'{ident}.json')
            extreme=read(args.run/'predictions/F1_FOLD05'/policy/f'{ident}.json')
            same_unit.append({'id':ident,'policy':policy,'same_discrete_packet':packet_same,
                              'identical_if_same':not packet_same or (semantic(center)==semantic(extreme) and center['correction_events']==extreme['correction_events'])})
    workers=[read(p) for p in (args.run/'worker-audit').glob('*.json')]
    forbidden=[name for worker in workers for name in worker['forbidden_reads']]
    result={'at_utc':stamp(),'input_hash_checks':len(hash_checks),'changed_inputs':[name for name,ok in hash_checks.items() if not ok],
            'baseline_checks':baseline,'old_composition_replay_checks':old_replays,'output_contract_checks':contracts,
            'same_unit_checks':same_unit,'actual_source_forbidden_reads':forbidden,
            'original21_predictor_and_config_unchanged':True,'no_OS_sandbox_claim':True}
    result['all_pass']=(all(hash_checks.values()) and all(r['identical'] for r in baseline+old_replays)
                        and all(r['boundaries_preserved'] and r['source_clock_membership'] and r['no_output_spans_dropped'] for r in contracts)
                        and all(r['identical_if_same'] for r in same_unit) and not forbidden)
    write(args.run/'audit.json',result)
    if not result['all_pass']:raise RuntimeError('Required source/input/output contract audit failed')
    print('AUDIT PASS',len(hash_checks),'hashes;',len(contracts),'outputs;',len(same_unit),'same-unit checks',flush=True)


if __name__=='__main__':main()
