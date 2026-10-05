"""Source-only wrapper comparing learned heads on one frozen common decoder."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import numpy as np
from . import analyzer as base
from . import structure_compare
from .meter_calibrated import decode_meter as calibrated_decode
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mert-cache',type=Path,default=Path('data/cache/tempo-meter-v3/mert-v2'))
    p.add_argument('--arm',choices=['A','B','C'],required=True);p.add_argument('--meter-calibration',type=Path,required=True);p.add_argument('--wait-for-mert-cache',action='store_true');a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    from music_map_contract import prepare_map,render_bars
    inputs=json.loads(a.input.read_text())
    if not inputs['source_only'] or a.output.exists():raise ValueError('frozen inputs and new output required')
    a.output.mkdir(parents=True)
    manifest=dict(complete=False,references_available_to_runner=False,input_sha256=digest(a.input),arm=a.arm,
                  comparison_implementation_sha256={name:digest(Path(__file__).with_name(name)) for name in ['compare_runner.py','structure_compare.py']},rows=[])
    calibration=json.loads(a.meter_calibration.read_text())
    if calibration['checkpoint_sha256']!=digest(a.checkpoint) or calibration['primary21_used']:raise ValueError('calibration binding mismatch')
    manifest['meter_calibration_sha256']=digest(a.meter_calibration)
    manifest['meter_settings']=calibration['selected']
    manifest['comparison_implementation_sha256']['meter_calibrated.py']=digest(Path(__file__).with_name('meter_calibrated.py'))
    original=base.predict;original_meter=base.decode_meter
    base.decode_meter=lambda clock,logits,structural:calibrated_decode(clock,logits,structural,**calibration['selected'])
    try:
        for index,row in enumerate(inputs['rows']):
            if digest(row['audio'])!=row['audio_sha256']:raise ValueError('source changed')
            extra=None;extra_receipt=None
            if a.arm=='B':
                path=a.mert_cache/(row['audio_sha256']+'.npz')
                waited=time.monotonic()
                while a.wait_for_mert_cache and not (path.exists() and path.with_suffix('.json').exists()):
                    if time.monotonic()-waited>1800:raise TimeoutError('MERT producer stalled')
                    time.sleep(2)
                extra_receipt=json.loads(path.with_suffix('.json').read_text())
                if extra_receipt['binding']['source_sha256']!=row['audio_sha256']:raise ValueError('MERT source mismatch')
                with np.load(path) as z:extra=z['features'].astype(np.float32)
            base.predict=lambda features,logits,checkpoint:structure_compare.predict(features,logits,checkpoint,extra)
            folder=a.output/f'{index:02d}'
            result=base.analyze(row['audio'],row.get('initial_bpm'),acoustic_checkpoint=Path('data/models/beat-this/final0.ckpt'),
                                structure_checkpoint=a.checkpoint,cache_root=Path('data/cache/tempo-meter-v3/acoustic-v1'),output=folder)
            candidates=json.loads((folder/'candidate-bank.json').read_text());rejected=[];valid=None
            for rank,candidate in enumerate(candidates):
                try:
                    prepared=prepare_map(candidate['prediction']['map'])
                    if render_bars(prepared)['status']!='rendered':raise ValueError('bar map cannot render')
                except (ValueError,TypeError,KeyError) as error:
                    rejected.append(dict(rank=rank,name=candidate['name'],reason=str(error)));continue
                valid=(rank,candidate);break
            if valid is None:raise ValueError('no valid candidate for source '+row['audio_sha256'])
            rank,candidate=valid
            if rank:
                path=folder/'selected-valid.json';path.write_text(json.dumps(candidate['prediction'],indent=2)+'\n')
                result['unvalidated_selection']=result['selected'];result['selected']=dict(path=str(path.resolve()),sha256=digest(path))
            result['validity_guard']=dict(rejected_before_selection=rejected,selected_rank=rank)
            if extra_receipt:result['mert_feature_receipt']=extra_receipt
            manifest['rows'].append(dict(id=row['id'],title=row['title'],initial_bpm_source=row.get('initial_bpm_source'),**result))
            (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    finally:base.predict=original;base.decode_meter=original_meter
    manifest['complete']=True;(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
