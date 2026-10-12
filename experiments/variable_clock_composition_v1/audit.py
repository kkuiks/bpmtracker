"""Poisoned-evaluation replay, same-layer identity and frozen-source checks."""
import argparse
from pathlib import Path
import shutil
import sys

from .common import read,write,digest,guard,code_hashes
from .worker import predict_one


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run;guard(run)
    ids=['r001','r008','r017','c003'];opened=[];forbidden=[];active=[False]
    def hook(event,args):
        if event!='open' or not active[0] or not isinstance(args[0],(str,bytes)):return
        s=args[0].decode() if isinstance(args[0],bytes) else args[0];mode=args[1] if isinstance(args[1],str) else ''
        if any(x in mode for x in 'wax+'):return
        if Path(s).suffix in ['.json','.npz']:
            opened.append(s)
            if any(x in s.lower() for x in ['evaluation','/references/','raw-proxies','catalog.json','oracle-banks']):
                forbidden.append(s);raise RuntimeError('Evaluation read during poisoned replay')
    sys.addaudithook(hook);matches=[]
    for tag,poison in [('a',{'bpm':9999,'phase':777,'reference_path':'/absent/one'}),
                       ('b',{'bpm':1,'phase':-999,'reference_path':'/absent/two'})]:
        root=run/'isolation-replay'/tag;root.mkdir(parents=True,exist_ok=True)
        write(root/'evaluation-index.json',poison)
        for ident in ids:
            for rel in [Path('banks')/f'{ident}.json',Path('tables/expanded')/f'{ident}.npz',
                        Path('encoded-units/proxy100')/f'{ident}.json']:
                target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(run/rel,target)
            write(root/'raw-proxies/proxy100'/f'{ident}.json',poison)
            active[0]=True
            try:predict_one(root,ident,['none','proxy100'],['M3_REGION_HOLD'])
            finally:active[0]=False
            for policy in ['none','proxy100']:
                rel=Path('M3_REGION_HOLD')/policy/f'{ident}.json'
                matches.append({'case':tag,'id':ident,'policy':policy,
                                'matches_normal':digest(root/'predictions'/rel)==digest(run/'predictions'/rel)})
    triplets=[]
    for row in read(run/'encoder-receipt.json')['rows']:
        ident=row['id'];policies=['proxy95','proxy100','proxy105']
        packets=[read(run/'encoded-units'/p/f'{ident}.json') for p in policies]
        preds=[read(run/'predictions/M3_REGION_HOLD'/p/f'{ident}.json') for p in policies]
        for pred in preds:pred['policy']='same_discrete_layer'
        for i in range(3):
            for j in range(i+1,3):
                if packets[i]==packets[j]:triplets.append({'id':ident,'pair':[policies[i],policies[j]],'identical':preds[i]==preds[j]})
    sensor=sorted((run/'sensor-audit').glob('*.json'));workers=sorted((run/'worker-audit').glob('*.json'))
    result={'poisoned_replays':matches,'all_poisoned_predictions_identical':all(r['matches_normal'] for r in matches),
        'same_layer_pairs':triplets,'all_same_layer_predictions_identical':all(r['identical'] for r in triplets),
        'forbidden_read_attempts':forbidden,'opened_replay_data_paths':sorted(set(opened)),
        'sensor_audits':len(sensor),'worker_audits':len(workers),
        'all_worker_forbidden_reads_zero':all(not read(p).get('forbidden_reads',[]) for p in workers),
        'all_sensor_forbidden_reads_zero':all(read(p)['forbidden_reference_reads']==0 for p in sensor),
        'source_hashes_match_freeze':read(run/'freeze.json')['code_hashes']==code_hashes(),
        'not_an_OS_sandbox_claim':True,'reference_timing_not_recertified':True}
    write(run/'source-isolation-audit.json',result)
    print('AUDIT',result['all_poisoned_predictions_identical'],result['all_same_layer_predictions_identical'],flush=True)
    if not result['all_poisoned_predictions_identical'] or not result['all_same_layer_predictions_identical'] or forbidden:
        raise RuntimeError('Source/identity audit failed')


if __name__=='__main__':main()
