/** Confirm explicitly owner-approved saved DAW maps without editing recordings.
 * Existing references, native sources and frozen runs remain at their old paths.
 * This materializes saved geometry; it is not inference or alignment fitting.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {materializeDawMap} from './daw_map_reference.mjs';

const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const SAMPLES=path.join(ROOT,'data/samples');
const REVIEW='records/owner-review/20261010-formal-daw-v1';
const OUTPUT='records/owner-review/20261010-reference-confirmation-v1';
const EPS=1e-9;
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const encoded=value=>Buffer.from(JSON.stringify(value,null,2)+'\n');
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const relative=p=>path.relative(SAMPLES,p).split(path.sep).join('/');
async function atomic(p,value){const temp=p+'.partial';await fs.writeFile(temp,encoded(value));await fs.rename(temp,p);}
function same(a,b){return JSON.stringify(a)===JSON.stringify(b);}

async function main(){
 const writing=process.argv.includes('--write');
 const report=await read(path.join(SAMPLES,REVIEW,'report.json'));
 const decision=await read(path.join(SAMPLES,REVIEW,'decisions.json'));
 const catalogFile=path.join(SAMPLES,'catalog.json');
 const catalogBytes=await fs.readFile(catalogFile),catalog=JSON.parse(catalogBytes);
 const rows=report.records.filter(r=>r.saved_draft&&r.observed_changes.length);
 const out=path.join(SAMPLES,OUTPUT);await fs.mkdir(out,{recursive:true});
 if(writing&&await fs.stat(path.join(out,'confirmation.json')).then(()=>true,()=>false))
  throw new Error('Confirmation receipt already exists; preserve it and use a new revision');
 const {build}=await import(pathToFileURL(path.join(ROOT,'apps/daw/node_modules/rolldown/dist/index.mjs')).href);
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'joljak-confirm-map-math-'));
 try{
  await build({input:path.join(ROOT,'apps/daw/src/music.ts'),platform:'node',output:{file:path.join(temp,'music.mjs'),format:'esm'}});
  const music=await import(pathToFileURL(path.join(temp,'music.mjs')).href);
  const plans=[];
  for(const row of rows){
   const track=catalog.tracks.find(t=>t.id===row.id);if(!track)throw new Error('Reviewed recording is no longer enrolled: '+row.id);
   const projectFile=path.join(SAMPLES,row.saved_draft.project_path);
   const project=await read(projectFile),proposal=await read(path.join(SAMPLES,row.saved_draft.proposal_path));
   const review=project.sampleReview,clip=project.clips.find(c=>c.id===review.clipId);
   if(!clip||review.reference.id!==row.id||review.loadedVariant!=='accepted')throw new Error('Unexpected review identity or comparison variant');
   const origin=clip.start-clip.sourceStart,start=clip.sourceStart,end=start+clip.duration;
   if(!same(project.tempos,proposal.project_tempos)||!same(project.signatures,proposal.project_signatures)||Math.abs(origin-proposal.source_audio_origin_seconds)>EPS)
    throw new Error('Saved project/proposal mismatch: '+row.id);
   if(Math.abs(start-row.saved_draft.source_range_seconds[0])>EPS||Math.abs(end-row.saved_draft.source_range_seconds[1])>EPS)
    throw new Error('Saved overlap differs from the owner-reviewed report: '+row.id);
   const oldFile=path.join(SAMPLES,track.reference.path),oldStat=await fs.stat(oldFile);
   if(oldStat.size!==review.reference.referenceVersion.bytes||Math.abs(oldStat.mtimeMs-review.reference.referenceVersion.modifiedMs)>1)
    throw new Error('Source reference version changed after review: '+row.id);
   const hiddenTail=end<track.duration_seconds-1e-7;
   const tail=track.owner_confirmed_no_grid_tail;
   if(hiddenTail&&(!tail?.trim_intent_confirmed||Math.abs(tail.source_audio_seconds[0]-end)>EPS))
    throw new Error('Trimmed tail has not been owner-confirmed: '+row.id);
   const noGrid=hiddenTail?[[end,track.duration_seconds]]:[];
   const map=materializeDawMap(project,origin,start,end,music);
   const quarters=map.quarter_events,bars=map.downbeats_seconds,clicks=map.approved_click_beats_seconds;
   const delta=(review.initialAudioOrigin-origin)*1000;
   const displayedTotal=review.reference.offset===null?null:review.reference.offset+delta/1000;
   const reference={schema_version:2,kind:'owner_confirmed_saved_daw_source_map',id:row.id,title:row.title,
    decision_date_local:'2026-10-10',timezone:'Asia/Seoul',reference_tier:'owner_confirmed_daw_edited_map',
    source_audio_sha256:track.audio.sha256,source_sample_rate:track.sample_rate,source_sample_frames:track.sample_frames,
    source_audio_duration_seconds:track.duration_seconds,source_working_project:row.saved_draft.project_path,
    source_working_proposal:row.saved_draft.proposal_path,previous_accepted_reference:track.reference,
    acceptance_record:OUTPUT+'/confirmation.json',human_alignment_accepted:true,owner_map_and_scope_accepted:true,
    independent_millisecond_timing_certified:false,alignment_fitted_to_predictions:false,
    offset_seconds:displayedTotal,source_origin_shift_seconds:displayedTotal,additional_reference_offset_seconds:0,
    offset_semantics:'Saved DAW total alignment readout. Edited geometry is defined by audio-relative events, not by adding this value to immutable native clocks.',
    audio_relative_fields:['time_seconds','master_seconds','beats_seconds','downbeats_seconds','approved_click_beats_seconds'],
    additional_offset_to_apply_when_consuming_audio_relative_fields_seconds:0,
    quarter_axis:'Saved DAW project quarters; no original DAW bar-number claim.',
    bar_anchor_quarter:0,bar_anchor_audio_seconds:-origin,
    tempo_events:map.tempo_events,meter_events:map.meter_events,
    tempo_declarations_audio_relative:map.tempo_declarations_audio_relative,meter_declarations_audio_relative:map.meter_declarations_audio_relative,
    declaration_origin_note:'Pre-audio working-project declarations retain their state and phase. The audio-start state is not a new downbeat or a native producer declaration.',
    quarter_events:quarters,quarter_beats_seconds:quarters.map(e=>e.master_seconds),beats_seconds:quarters.map(e=>e.master_seconds),
    downbeats_seconds:bars,approved_click_beats_seconds:clicks,
    evaluation_beat_unit:'quarter_note',approved_click_unit:'notated_signature_denominator',
    support_seconds:[[start,end]],free_time_seconds:noGrid,
    evaluation_scope:{grid_support_seconds:[start,end],no_grid_tail_seconds:hiddenTail?[end,track.duration_seconds]:[],
      boundary_semantics:'half-open source-audio intervals; owner-confirmed musical scope and nonmetrical tail'},
    scope_basis:'Owner-approved saved DAW source overlap; original recording remains complete.',
    render_policy:'Consume the stored audio-relative quarter/bar/click arrays directly. No extra source offset, bar reset at audio zero, or grid extrapolation into approved tails.',
    native_source_files_and_frozen_records_unchanged:true,previous_reference_preserved:true};
   const target=path.join(path.dirname(oldFile),'reference-owner-daw-20261010-v1.json');
   if(await fs.stat(target).then(()=>true,()=>false))throw new Error('Versioned reference target already exists: '+target);
   if(!quarters.length||!bars.length||!clicks.length)throw new Error('New reference has no valid quarter/bar/click events');
   const bytes=encoded(reference);
   plans.push({id:row.id,title:row.title,oldReference:track.reference,newReference:{path:relative(target),bytes:bytes.length,sha256:digest(bytes)},
    target,bytes,support:[[start,end]],noGrid,displayedTotal,delta,reference});
  }
  const receipt={schema_version:1,decision_date_local:'2026-10-10',timezone:'Asia/Seoul',authority:'explicit_owner_chat_instruction',
   owner_instruction_ko:'수정 적용된 애들까지 정답 tempo map으로 재확정',formal_samples_confirmed:catalog.formal_samples,
   changed_reference_ids:plans.map(p=>p.id),unchanged_reference_ids:catalog.tracks.filter(t=>!t.role.startsWith('auxiliary')&&!plans.some(p=>p.id===t.id)).map(t=>t.id),
   original_listening_and_change_report:REVIEW+'/report.json',original_owner_decisions:REVIEW+'/decisions.json',
   tail_confirmation:decision.owner_tail_clarification,
   revisions:plans.map(p=>({id:p.id,title:p.title,previous_reference:p.oldReference,current_reference:p.newReference,
    source_support_seconds:p.support,approved_no_grid_seconds:p.noGrid,total_alignment_offset_seconds:p.displayedTotal,
    additional_alignment_adjustment_ms:p.delta,quarter_event_count:p.reference.beats_seconds.length,
    downbeat_event_count:p.reference.downbeats_seconds.length,approved_click_event_count:p.reference.approved_click_beats_seconds.length})),
   recordings_native_clocks_previous_references_and_frozen_runs_preserved:true,
   original_recording_hashing_audio_decode_playback_or_inference_performed:false,
   current_daw_timing_functions_used_for_materialization:true};
  await atomic(path.join(out,'confirmation-plan.json'),receipt);
  if(!writing){console.log(JSON.stringify(receipt,null,2));return;}
  if(!catalogBytes.equals(await fs.readFile(catalogFile)))throw new Error('Catalog changed during confirmation preparation');
  const inventoryFile=path.join(SAMPLES,'assets.json'),inventory=await read(inventoryFile);
  const indexFile=path.join(SAMPLES,'ntm-library-index.json'),index=await read(indexFile);
  for(const p of plans){
   await fs.writeFile(p.target,p.bytes,{flag:'wx'});
   const t=catalog.tracks.find(t=>t.id===p.id);
   t.reference=p.newReference;t.reference_support_seconds=p.support;
   t.qualification={...(t.qualification??{}),reference_tier:'owner_confirmed_daw_edited_map',owner_map_and_scope_accepted:true,
    independent_millisecond_timing_certified:false,scope_note:'Owner-confirmed audible musical scope; separately confirmed no-BPM/ad-lib tail is excluded from grid scoring.'};
   t.original_clock_to_audio_offset_metadata={total_seconds:p.displayedTotal,
    semantics:'DAW initial proposal plus owner alignment adjustment; edited geometry is defined by the new audio-relative map.',
    previous_metadata:t.original_clock_to_audio_offset_metadata??null,
    already_applied_in_accepted_tempo_map:true,additional_offset_to_apply_when_consuming_accepted_map_seconds:0};
   t.owner_revalidation={decision_date_local:'2026-10-10',status:'owner_confirmed_corrected_reference',record:OUTPUT+'/confirmation.json',independent_millisecond_timing_certified:false};
   if(t.owner_confirmed_no_grid_tail)t.owner_confirmed_no_grid_tail.canonical_reference_materialization_pending=false;
   if(t.owner_selected_reference){t.owner_selected_reference.canonical_conversion_deferred_for_requested_observation_report=false;t.owner_selected_reference.confirmed_reference_path=p.newReference.path;}
   inventory.assets.push({...p.newReference,category:'owner_confirmed_daw_reference',private_distribution:true,retained:true,
    registered_owner_approved:true,supersedes_reference_path:p.oldReference.path,decision_record:OUTPUT+'/confirmation.json'});
   if(t.audio.path.startsWith('ntm/')){
    const slug=t.audio.path.split('/')[1],recordPath=path.join(SAMPLES,'ntm',slug,'recording.json');
    const entry=index.recordings.find(e=>e.slug===slug);
    if(entry){entry.current_approved_reference=p.newReference.path;entry.owner_reference_revision_record=OUTPUT+'/confirmation.json';}
    const recording=await read(recordPath);recording.current_approved_reference=p.newReference.path;recording.owner_reference_revision_record=OUTPUT+'/confirmation.json';await atomic(recordPath,recording);
   }
  }
  for(const t of catalog.tracks.filter(t=>!t.role.startsWith('auxiliary')&&!plans.some(p=>p.id===t.id)))
   t.owner_revalidation={...(t.owner_revalidation??{}),decision_date_local:'2026-10-10',status:'owner_confirmed_current_reference',record:OUTPUT+'/confirmation.json',independent_millisecond_timing_certified:false};
  const receiptBytes=encoded(receipt),receiptAsset={path:OUTPUT+'/confirmation.json',bytes:receiptBytes.length,sha256:digest(receiptBytes)};
  inventory.assets.push({...receiptAsset,category:'owner_reference_confirmation_record',retained:true,registered_owner_approved:true});
  for(const t of catalog.tracks.filter(t=>!t.role.startsWith('auxiliary'))){
   t.owner_review_records??=[];t.owner_review_records.push(receiptAsset);
  }
  const retained=inventory.assets.filter(e=>e.copied||e.retained);
  const unique=new Map(retained.map(e=>[e.path,e]));inventory.unique_copied_files=unique.size;
  inventory.unique_copied_bytes=[...unique.values()].reduce((n,e)=>n+(e.bytes??0),0);
  catalog.latest_owner_reference_confirmation={decision_date_local:'2026-10-10',formal_samples:catalog.formal_samples,
    updated_reference_ids:plans.map(p=>p.id),record:receiptAsset.path};
  if(catalog.latest_owner_review){
   catalog.latest_owner_review.initial_saved_changes_report_only_ids=catalog.latest_owner_review.saved_changes_report_only_ids??[];
   catalog.latest_owner_review.saved_changes_report_only_ids=[];
   catalog.latest_owner_review.saved_changes_confirmed_ids=plans.map(p=>p.id);
   catalog.latest_owner_review.status='all_remaining_formal_references_confirmed';
   catalog.latest_owner_review.confirmation_record=receiptAsset.path;
  }
  await fs.writeFile(path.join(out,'confirmation.json'),receiptBytes,{flag:'wx'});
  await atomic(inventoryFile,inventory);await atomic(indexFile,index);await atomic(catalogFile,catalog);
  console.log(JSON.stringify({formal_samples_confirmed:catalog.formal_samples,revised_references:plans.map(p=>({id:p.id,path:p.newReference.path,
   scope:p.support,offset:p.displayedTotal,quarter_count:p.reference.beats_seconds.length,bar_count:p.reference.downbeats_seconds.length}))},null,2));
 }finally{await fs.rm(temp,{recursive:true,force:true});}
}
await main();
