from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
from .common import ROOT,PARENT,CONFIG,METHODS,POLICIES,PILOT_IDS,read,write,digest,code_hashes,stamp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path);parser.add_argument('--pilot',action='store_true')
    parser.add_argument('--methods',nargs='+',choices=list(METHODS),default=list(METHODS))
    args=parser.parse_args();run=args.run or ROOT/'data/research/runs/beat_event_map_v1'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-v1')
    run.mkdir(parents=True,exist_ok=False)
    index=read(PARENT/'evaluation-index.json')['rows'];sources=read(PARENT/'source-inputs.json')['samples']
    if args.pilot:index=[r for r in index if r['id'] in PILOT_IDS]
    ids={r['id'] for r in index};sources=[r for r in sources if r['id'] in ids]
    catalog={r['id']:r for r in read(ROOT/'data/samples/catalog.json')['tracks']}
    exclusions=read(ROOT/'data/samples/excluded-candidates.json')['candidates']
    hashes={};selected=[]
    for item in index:
        entry=catalog[item['original_id']]
        canonical=ROOT/'data/samples'/entry['reference']['path']
        if digest(canonical)!=item['reference_sha256']:raise RuntimeError('Accepted reference changed')
        if any(e.get('permanent_exclusion') and (item['original_id']==e.get('id') or e.get('slug','!') in entry['audio']['path']) for e in exclusions):
            raise RuntimeError('Permanently excluded source')
        target=run/'references'/(item['id']+'.json');target.parent.mkdir(exist_ok=True)
        shutil.copy2(item['reference_path'],target);selected.append({**item,'reference_path':str(target.resolve())})
        hashes[str(canonical)]=digest(canonical)
    actual=[]
    for row in sources:
        source={k:row[k] for k in ['id','audio_path','duration_seconds','sample_rate','sample_frames','channels','source_audio_sha256','events_path','family_path']}
        for key in ['events_path','family_path']:
            if source.get(key):hashes[source[key]]=digest(source[key])
        actual.append(source)
    write(run/'source-inputs.json',{'samples':actual,'old_time_window_banks_or_tables_used':False})
    write(run/'evaluation-index.json',{'rows':selected})
    write(run/'input-freeze.json',{'at_utc':stamp(),'files':hashes,'original_audio_geometry_and_hashes_reused_from_parent_receipts':True})
    write(run/'freeze.json',{'at_utc':stamp(),'config':CONFIG,'methods':METHODS,'code_hashes':code_hashes()})
    for p in code_hashes():
        target=run/'code-snapshot'/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,target)
    write(run/'protocol.json',{'at_utc':stamp(),'scope':'pilot' if args.pilot else 'complete_known_cohort',
        'recordings':len(selected),'main_recordings':sum(not r['model_seeded_reference_diagnostic_only'] for r in selected),
        'selected_methods':args.methods,
        'family_initial_prior_uses_total_neural_beat_mass':True,
        'E3_rate_policy':'nearest octave-related rate to the active map for each proposed neural pulse clock; other signatures remain hypotheses',
        'known_material_not_unseen':True,'config':CONFIG,'methods':METHODS,'policies':POLICIES,
        'initial_tap_proxy_percent':3,'reference_numeric_taps_only_in_separate_encoder':True,
        'same_initial_unit_requires_identical_complete_map':True,'no_initial_meter_hint':True,
        'no_fixed_wall_clock_analysis_windows_or_hold_timers':True,
        'initial_hypotheses_from_adaptive_opening_evidence_and_audio_family_proposals':True,
        'full_song_family_is_a_proposal_not_constant_tempo_requirement':True,
        'each_possible_old_beat_considered_before_source_and_resource_pruning':True,
        'source_episode_edges_are_not_output_change_boundaries':True,
        'declarations_on_old_notated_beats_only':True,'tempo_preserves_bar':True,'signature_can_end_partial_bar':True,
        'low_confidence_does_not_mute_known_clock':True,'independent_output_phase_parameters_after_start':0,
        'no_new_neural_runs_training_acquisition_reference_edits_or_source_git_actions':True,
        'success_assessment':['structural_contract','short_and_early_change_search_controls','whole_map_native_click_accuracy',
                              'unnecessary_changes','variable_boundary_recovery','initial_alignment_and_meter_errors'],
        'followup_policy':'Preserve each failure and freeze each generic corrective iteration. No per-song exceptions or winners.',
        'native_listening_pairs_required_at_final_delivery':True,'no_app_estimator_adoption':True})
    print('PREPARED',str(run),len(selected),flush=True)

if __name__=='__main__':main()
