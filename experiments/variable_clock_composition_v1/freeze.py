"""Source/config freeze after logical controls and before target prediction."""
import argparse
from pathlib import Path
import shutil

from .common import ROOT,CONFIG,METHODS,GATES,read,write,code_hashes,stamp
from .prepare import normalize


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    if (run/'freeze.json').exists():raise RuntimeError('Existing freeze must not be replaced')
    if not read(run/'logical-controls.json')['passed']:raise RuntimeError('Controls not passed')
    rows=read(run/'evaluation-index.json')['rows']
    for row in rows:
        if row['role']=='constructed_control':
            legacy=read(row['legacy_evaluation_path']);raw=read(legacy['reference_path'])
            nr=normalize({'reference_support_seconds':legacy['support_seconds']},raw)
            write(run/'references'/f"{row['id']}.json",nr)
            target=run/'references'/f"{row['id']}.original.json";shutil.copy2(legacy['reference_path'],target)
            row['reference_path']=str(run/'references'/f"{row['id']}.json")
    write(run/'evaluation-index.json',{'rows':rows})
    protocol=read(run/'protocol.json');protocol.update({'config':CONFIG,'methods':METHODS,'gates':GATES,
       'local_boundary_emission_window_seconds':2.,'seed_event_count_window_seconds':24.,
       'long_window_seed_count_allows_30_to_60_bpm':True,
       'pre_target_synthetic_mechanics_correction':'8-second count could not hold 8 quarters at 50 BPM; use 24-second count for seed qualification',
       'boundary_timing_correction_before_target_use':'qualify with long windows and place intervals using two-second event evidence',
       'decoder_beam_is_approximate_not_exact_dynamic_programming':True,
       'oracle_method_variants':['O_LOCAL','O_REGION_HOLD','O_LOW_CHANGE_COST','O_HIGH_CHANGE_COST'],
       'secondary_assisted_viability_also_reported':True})
    write(run/'protocol.json',protocol)
    hashes=code_hashes()
    for relative in hashes:
        target=run/'code-snapshot'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    write(run/'freeze.json',{'at_utc':stamp(),'code_hashes':hashes,'config':CONFIG,'methods':METHODS,'gates':GATES,
          'target_predictions_or_scores_inspected_before_freeze':False,'logical_controls_passed':True,
          'source_schema_has_no_song_identity_or_reference_fields':True})
    print('FROZEN',len(hashes),'source files',flush=True)


if __name__=='__main__':main()
