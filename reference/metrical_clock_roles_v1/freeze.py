"""Freeze all source and decision settings before musical target predictions."""
import argparse
from pathlib import Path
import shutil
from .common import CONFIG,METHODS,CRITERIA,ROOT,read,write,stamp,code_hashes

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    if (a.run/'freeze.json').exists():raise RuntimeError('Never overwrite a freeze')
    protocol=read(a.run/'protocol.json');protocol.update({'config':CONFIG,'methods':METHODS,'criteria':CRITERIA,
                   'initial_meter_prior_prefers_four_quarter_bars_but_all_meters_remain_possible':True,
                   'downbeat_observation_roles_are_separate_from_meter':True,
                   'pre_freeze_observation_controls_used_for_design':True})
    write(a.run/'protocol.json',protocol)
    hashes=code_hashes()
    for path in hashes:
        target=a.run/'code-snapshot'/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,target)
    write(a.run/'freeze.json',{'frozen_at_utc':stamp(),'config':CONFIG,'methods':METHODS,
          'criteria':CRITERIA,'code_hashes':hashes,
          'target_predictions_not_scored_before_freeze':True})
    print('FROZEN',len(hashes),flush=True)

if __name__=='__main__':main()
