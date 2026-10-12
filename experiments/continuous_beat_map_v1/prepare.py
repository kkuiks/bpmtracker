from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
from .common import ROOT,SOURCE,MULTIPLE,COMPOSITION,FIXED,CONFIG,POLICIES,read,write,digest,code_hashes,stamp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path)
    args=parser.parse_args()
    run=args.run or ROOT/'data/research/runs/continuous_beat_map_v1'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')
    run.mkdir(parents=True,exist_ok=False)
    original=read(SOURCE/'source-inputs.json')['samples']
    index=read(SOURCE/'evaluation-index.json')['rows']
    by_id={x['id']:x for x in index};sources=[];hashes={}
    catalog={x['id']:x for x in read(ROOT/'data/samples/catalog.json')['tracks']}
    excluded=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    for row in original:
        ident=row['id'];item=by_id[ident];entry=catalog[item['original_id']]
        if any(e.get('permanent_exclusion') and (item['original_id']==e.get('id') or e.get('slug','!') in row['audio_path']) for e in excluded):
            raise RuntimeError('Permanently excluded source')
        canonical=ROOT/'data/samples'/entry['reference']['path']
        if digest(canonical)!=item['reference_sha256']: raise RuntimeError('Accepted reference changed')
        sources.append({k:row[k] for k in ['id','audio_path','duration_seconds','sample_rate','sample_frames','channels','source_audio_sha256']})
        source=sources[-1]
        source.update(events_path=str((MULTIPLE if ident.startswith('e') else COMPOSITION)/'events'/(ident+'.npz')),
                      bank_path=row['bank_path'],table_path=row['table_path'])
        candidates=[ROOT/'data/research/runs/metronome_reconstruction_v1/20261005-tap26-v2/source-families'/(item['original_id']+'.json'),
                    MULTIPLE/'original-families'/(ident+'.json'),COMPOSITION/'original-families'/(ident+'.json')]
        source['family_path']=next((str(p) for p in candidates if p.exists()),None)
        for key in ['events_path','bank_path','table_path','family_path']:
            if source.get(key): hashes[source[key]]=digest(source[key])
        target=run/'references'/(ident+'.json');target.parent.mkdir(exist_ok=True)
        shutil.copy2(item['reference_path'],target)
        hashes[str(canonical)]=digest(canonical);hashes[item['reference_path']]=digest(item['reference_path'])
        item['reference_path']=str(target)
    for p in [ROOT/'data/samples/catalog.json',ROOT/'data/samples/excluded-candidates.json',SOURCE/'metrics.json',FIXED/'metrics.json',FIXED/'selection.json']:
        hashes[str(p)]=digest(p)
    write(run/'source-inputs.json',{'samples':sources})
    write(run/'evaluation-index.json',{'rows':index})
    write(run/'freeze.json',{'at_utc':stamp(),'code_hashes':code_hashes(),'config':CONFIG})
    write(run/'input-freeze.json',{'at_utc':stamp(),'files':hashes,'audio_hashes_reused_from_frozen_source_receipts':True})
    for p in code_hashes():
        target=run/'code-snapshot'/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,target)
    write(run/'protocol.json',{'at_utc':stamp(),'primary_method':'C1_CONTINUOUS_MAP','primary_policy':'proxy100',
        'methods':['C0_CONSTANT_MAP','C1_CONTINUOUS_MAP'],'policies':POLICIES,'config':CONFIG,
        'complete_recordings':33,'primary_recordings':32,'actual_variable_recordings':10,'common_fixed_recordings':13,
        'known_material_not_unseen':True,'model_seeded_reference_excluded_from_main':True,
        'tap_proxy_percent':3,'tap_selects_only_audio_prepared_discrete_unit':True,
        'numeric_tap_discarded_before_map_search':True,'continuous_time_and_old_notated_beat_changes_required':True,
        'tempo_only_preserves_bar_position':True,'signature_may_close_partial_bar_at_old_beat':True,
        'no_independent_phase_parameters_after_initialization':True,'unknown_does_not_mute':True,
        'old_phase_quality_tables_are_proposals_only':True,'actual_map_scored_against_audio':True,
        'fixed_estimator_not_replaced':True,'native_project_metronome_for_listening':True,
        'no_new_neural_runs_training_acquisition_or_post_score_parameter_search':True,
        'evaluation':{'step_seconds':.05,'pulse_phase_tolerance_seconds':.070,'bpm_relative_tolerance':.005,
                      'bar_tolerance_seconds':.070,'harmful_change_penalty_seconds':8.,
                      'separate_pulse_rate_meter_bar_and_change_metrics':True},
        'decision':{'structural_correctness_is_required_even_if_accuracy_regresses':True,
                    'variable_and_fixed_accuracy_must_be_reported_separately':True,
                    'no_product_or_generalization_success_claim_from_structural_pass':True}})
    print('PREPARED',run,flush=True)

if __name__=='__main__':main()
