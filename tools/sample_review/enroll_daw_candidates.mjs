/** Dated owner-authorized enrollment, including the corrected Return to Earth scope. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {materializeDawMap,bpmDisplayLabel} from './daw_map_reference.mjs';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const SAMPLES=path.join(ROOT,'data/samples');
const BATCH='reviews/20261010-candidates-daw-v1';
const RECORD='records/owner-review/20261010-candidate-enrollment-v1';
const RETURN='jamie-king-the-contortionist',OVER='carl-bown-bullet-for-my-valentine';
const EXPECTED=['max-morton-jinjer-on-the-top','david-bendeth-underoath-desperate-times-desperate-measures',
 'dave-otero-allageon-allageon','buster-odeholm-oceano',OVER,RETURN,'jens-bogren-btbam-2019',
 'steve-evetts-the-dillinger-escape-plan-one-of-us-is-the-killer'];
const encoded=x=>Buffer.from(JSON.stringify(x,null,2)+'\n');
const hash=b=>createHash('sha256').update(b).digest('hex');
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const exists=async p=>fs.stat(p).then(()=>true,()=>false);
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const rel=p=>path.relative(SAMPLES,p).split(path.sep).join('/');
async function atomic(p,value){await fs.writeFile(p+'.partial',encoded(value));await fs.rename(p+'.partial',p);}
function asset(bytes,p){return {path:p,bytes:bytes.length,sha256:hash(bytes)};}
async function main(){
 if(!process.argv.includes('--write'))throw new Error('Dated explicit owner enrollment requires --write under the sample storage lock');
 const out=path.join(SAMPLES,RECORD);if(await exists(path.join(out,'acceptance.json')))throw new Error('Completed enrollment receipt exists; preserve it');
 const descriptorFile=path.join(SAMPLES,BATCH,'daw-review.json'),descriptorBytes=await fs.readFile(descriptorFile),descriptor=JSON.parse(descriptorBytes);
 if(!eq(descriptor.recordings.map(r=>r.id),EXPECTED))throw new Error('The explicitly approved eight-recording descriptor changed');
 const exclusions=await read(path.join(SAMPLES,'excluded-candidates.json'));
 const normalized=x=>String(x??'').toLowerCase().replace(/&/g,'and').replace(/[^a-z0-9]/g,'');
 for(const row of descriptor.recordings)for(const x of exclusions.candidates){
  if(!x.permanent_exclusion&&x.review_enabled!==false)continue;
  if([x.id,x.slug].includes(row.slug)||String(x.session_id)===String(row.session_id)||normalized(x.title)===normalized(row.title))
   throw new Error('Owner-excluded candidate in enrollment');
 }
 const catalogFile=path.join(SAMPLES,'catalog.json'),catalogBytes=await fs.readFile(catalogFile),catalog=JSON.parse(catalogBytes);
 if(EXPECTED.some(id=>catalog.tracks.some(t=>t.id===id)))throw new Error('One of the approved candidates is already enrolled; do not duplicate it');
 const inventoryFile=path.join(SAMPLES,'assets.json'),inventory=await read(inventoryFile);
 const indexFile=path.join(SAMPLES,'ntm-library-index.json'),index=await read(indexFile);
 const generated=[],plans=[];
 const {build}=await import(pathToFileURL(path.join(ROOT,'apps/daw/node_modules/rolldown/dist/index.mjs')).href);
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'joljak-enroll-map-math-'));
 try{
  await build({input:path.join(ROOT,'apps/daw/src/music.ts'),platform:'node',output:{file:path.join(temp,'music.mjs'),format:'esm'}});
  const music=await import(pathToFileURL(path.join(temp,'music.mjs')).href);
  for(const row of descriptor.recordings){
   const draftRoot=path.join(SAMPLES,'reviews/daw-drafts',row.id);
   const dates=(await fs.readdir(draftRoot,{withFileTypes:true})).filter(e=>e.isDirectory()).map(e=>e.name).sort();
   const folder=path.join(draftRoot,dates.at(-1)),projectFile=path.join(folder,'project.joljak'),proposalFile=path.join(folder,'proposal.json');
   const project=await read(projectFile),proposal=await read(proposalFile),review=project.sampleReview;
   const clip=project.clips.find(c=>c.id===review.clipId),audio=project.assets.find(a=>a.id===clip?.assetId);
   if(!clip||!audio||review.reference.id!==row.id||proposal.sample_id!==row.id||review.loadedVariant!=='accepted')throw new Error('Saved review identity mismatch');
   const origin=clip.start-clip.sourceStart,sourceEnd=clip.sourceStart+clip.duration;
   if(!eq(project.tempos,proposal.project_tempos)||!eq(project.signatures,proposal.project_signatures)||Math.abs(origin-proposal.source_audio_origin_seconds)>1e-9)
    throw new Error('Saved proposal/project geometry mismatch: '+row.id);
   if(Math.abs(clip.sourceStart)>1e-9||Math.abs(sourceEnd-audio.duration)>1e-9||!eq(proposal.source_range_seconds,[clip.sourceStart,sourceEnd]))
    throw new Error('Owner-approved full recording overlap changed: '+row.id);
   const sourceFile=path.join(SAMPLES,row.reference_path),source=await read(sourceFile),sourceStat=await fs.stat(sourceFile);
   if(sourceStat.size!==proposal.accepted_reference_version.bytes||Math.abs(sourceStat.mtimeMs-proposal.accepted_reference_version.modifiedMs)>1)
    throw new Error('Source version changed since owner review: '+row.id);
   const audioFile=path.join(SAMPLES,row.audio_path),audioStat=await fs.stat(audioFile);
   if(audioStat.size!==audio.originalSize||Math.abs(audio.duration-audio.frames/audio.sampleRate)>1e-9)throw new Error('Retained audio geometry changed');
   const start=0,end=row.id===RETURN?360.37:sourceEnd,excluded=row.id===RETURN?[[end,sourceEnd]]:[];
   if(!(end>start&&end<=sourceEnd))throw new Error('Invalid approved support');
   if(row.id===RETURN&&!eq(proposal.approved_support_seconds,[[0,360.37]]))throw new Error('Previously discussed Return to Earth boundary changed');
   const supplied=proposal.source_clock_available,seeded=!supplied;
   const audioAsset={path:row.audio_path,bytes:audioStat.size,sha256:source.audio_sha256??null};
   const audioHashSource=source.audio_sha256?'retained_collection_metadata':'not_recorded_in_retained_metadata; no original recording hash performed';
   const home=path.join(SAMPLES,'ntm',row.slug,'registered'),refPath=rel(path.join(home,'reference-owner-daw-20261010-v1.json'));
   const approvedProjectPath=rel(path.join(home,'owner-approved-project-20261010-v1.joljak'));
   if(await exists(path.join(SAMPLES,refPath))||await exists(path.join(SAMPLES,approvedProjectPath)))throw new Error('Versioned target already exists');
   const originalClocks=[];
   if(supplied){
    const raw=path.join(SAMPLES,'ntm',row.slug,'collection/raw-clock.json');
    originalClocks.push({path:rel(raw),bytes:(await fs.stat(raw)).size,sha256:source.clock_sha256});
    for(const file of source.clock_files??[])originalClocks.push({...file,bytes:(await fs.stat(path.join(SAMPLES,file.path))).size,sha256:null,checksum_recomputed_at_enrollment:false});
   }
   const reference={schema_version:2,kind:seeded?'owner_confirmed_model_seeded_daw_map':'owner_confirmed_saved_daw_source_map',
    id:row.id,title:row.title,decision_date_local:'2026-10-10',timezone:'Asia/Seoul',
    reference_tier:seeded?'owner_listening_confirmed_model_seeded_map':'owner_confirmed_daw_edited_map',
    source_audio_sha256:audioAsset.sha256,source_audio_hash_provenance:audioHashSource,
    source_sample_rate:audio.sampleRate,source_sample_frames:audio.frames,source_audio_duration_seconds:audio.duration,
    source_working_project:rel(projectFile),source_working_proposal:rel(proposalFile),approved_working_project:approvedProjectPath,
    previous_candidate_reference:row.reference_path,acceptance_record:RECORD+'/acceptance.json',
    supplied_producer_clock_available:supplied,reference_seed:seeded?'current_app_prediction_then_owner_listening':'supplied_clock_then_owner_daw_edits',
    derived_from_current_estimator_prediction:seeded,same_estimator_evaluation_requires_reference_origin_disclosure:seeded,
    human_alignment_accepted:true,owner_map_and_scope_accepted:true,independent_millisecond_timing_certified:false,
    independent_producer_clock_reference: false,offset_seconds:proposal.proposed_offset_seconds,
    source_origin_shift_seconds:proposal.proposed_offset_seconds,additional_reference_offset_seconds:0,
    offset_semantics:'Total DAW alignment readout; consume approved source-audio-relative geometry, never shift immutable source clocks by this value after edits.',
    ...materializeDawMap(project,origin,start,end,music),support_seconds:[[start,end]],free_time_seconds:[],
    excluded_evaluation_seconds:excluded,unknown_seconds:excluded,
    evaluation_scope:{grid_support_seconds:[start,end],excluded_tail_seconds:excluded[0]??[],no_grid_tail_seconds:[],
     boundary_semantics:'half-open source-audio intervals; owner-selected evaluation scope'},
    scope_basis:row.id===RETURN?'Owner explicitly excludes the previously discussed last 15.82043083900226 seconds from the reference scope; song remains enrolled.':'Owner approved complete recording and saved DAW map.',
    outside_support:row.id===RETURN?'owner_excluded_from_reference_evaluation; no claim that the tail has no musical grid':'none',
    source_files_original_recordings_and_saved_drafts_preserved:true,
    ...(seeded?{model_seed_prediction_records:project.analyses,model_seed_raw_prediction_preserved:true}:{}),
    ...(row.id===OVER?{owner_confirms_tail_listening:true,project_end_extension_does_not_change_map_or_audio_alignment:true}:{})};
   const bytes=encoded(reference),refAsset=asset(bytes,refPath);
   const beforeEnd=project.projectDuration;
   if(row.id===OVER)project.projectDuration=Math.max(project.projectDuration,clip.start+clip.duration+2);
   const metadata=await read(path.join(SAMPLES,'ntm',row.slug,'recording.json'));
   const entry=index.recordings.find(e=>e.slug===row.slug);if(!entry)throw new Error('Missing canonical NTM index entry');
   plans.push({row,project,proposal,origin,audio,audioAsset,audioHashSource,originalClocks,reference,refAsset,bytes,
    approvedProjectPath,beforeEnd,sourceProjectPath:rel(projectFile),sourceProposalPath:rel(proposalFile),excluded,metadata,entry});
  }
  if(!catalogBytes.equals(await fs.readFile(catalogFile))||!descriptorBytes.equals(await fs.readFile(descriptorFile)))throw new Error('Authorities changed during enrollment preparation');
  await fs.mkdir(out,{recursive:true});
  const receipt={schema_version:1,decision_date_local:'2026-10-10',timezone:'Asia/Seoul',authority:'explicit_owner_chat_instruction',
   owner_statement_ko:'over it 청취 확인 했고, retrn to earth 는 제외. 마지막 노래는 앱 예측이긴 한데 내가 직접 들었고 매우 정확해서 그대로 진행한거야. 그러면 쟤네 다 저장해주고, 정식 표본으로 반영도 해줘',
   owner_scope_correction_ko:'아니 등록 대상에서 제외하라는 게 아니라, 마지막 15초를 정답 범위에서 빼라는 뜻이었어, 모두 등록해줘',
   formal_sample_enrollment_authorized:true,registered_samples:plans.length,formal_samples_before:catalog.formal_samples,
   formal_samples_after:catalog.formal_samples+plans.length,source_descriptor:BATCH+'/daw-review.json',
   source_descriptor_before_enrollment:RECORD+'/source-descriptor-before-enrollment.json',
   return_to_earth_remains_enrolled:true,return_to_earth_excluded_tail_seconds:[360.37,plans.find(p=>p.row.id===RETURN).audio.duration],
   return_to_earth_tail_is_excluded_scope_not_an_inferred_no_grid_claim:true,
   independent_millisecond_timing_certified:false,frozen_experiment_inputs_results_and_denominators_changed:false,
   new_recording_decode_hash_playback_model_benchmark_or_cleanup_performed:false,
   registrations:[],original_recordings_and_candidate_clock_geometry_preserved:true};
  const known=new Set(inventory.assets.map(a=>a.path));
  function addInventory(a,category){if(known.has(a.path))return;inventory.assets.push({...a,category,retained:true,private_distribution:true,
   registered_owner_approved:true,decision_record:RECORD+'/acceptance.json',source_integrity_rechecked_at_enrollment:false});known.add(a.path);}
  for(const p of plans){
   const refFile=path.join(SAMPLES,p.refAsset.path);await fs.mkdir(path.dirname(refFile),{recursive:true});await fs.writeFile(refFile,p.bytes,{flag:'wx'});
   const refStat=await fs.stat(refFile),snapshot=p.project.sampleReview.reference;
   snapshot.role='finished_recording_development';snapshot.previouslyAccepted=true;
   delete snapshot.availableClock;delete snapshot.candidateDescriptorPath;delete snapshot.candidateDescriptorVersion;
   snapshot.referencePath=p.refAsset.path;snapshot.referenceVersion={bytes:p.refAsset.bytes,modifiedMs:refStat.mtimeMs,catalogSha256:p.refAsset.sha256};
   snapshot.support=p.reference.support_seconds;snapshot.noGrid=[];snapshot.unknown=p.excluded;snapshot.offset=p.proposal.proposed_offset_seconds;
   snapshot.tempos=p.reference.tempo_events.map(e=>({seconds:e.time_seconds,bpm:e.bpm_quarter}));
   snapshot.meters=p.reference.meter_events.map(e=>({seconds:e.time_seconds,numerator:e.numerator,denominator:e.denominator}));
   snapshot.beats=p.reference.approved_click_beats_seconds;snapshot.bars=p.reference.downbeats_seconds;snapshot.sourceOffsetAlternatives=[];
   snapshot.bpmLabels=[...new Set(snapshot.tempos.map(e=>bpmDisplayLabel(e.bpm)))];snapshot.meterLabels=[...new Set(snapshot.meters.map(e=>`${e.numerator}/${e.denominator}`))];
   snapshot.description=p.proposal.source_clock_available?'Owner-approved saved DAW tempo/signature map.':
    'App-prediction-seeded tempo/signature map explicitly approved by owner listening; no supplied producer clock.';
   if(p.excluded.length)snapshot.description+=' The final uncovered tail is excluded from reference evaluation.';
   p.project.sampleReview.initialAudioOrigin=p.origin;delete p.project.sampleReview.mapImportWarning;
   for(const a of p.project.assets){if(a.id!==p.audio.id)throw new Error('Unexpected extra source asset');a.sourcePath=path.relative(path.dirname(path.join(SAMPLES,p.approvedProjectPath)),path.join(SAMPLES,p.row.audio_path));}
   const projectBytes=encoded(p.project),projectAsset=asset(projectBytes,p.approvedProjectPath);await fs.writeFile(path.join(SAMPLES,p.approvedProjectPath),projectBytes,{flag:'wx'});
   const record={id:p.row.id,title:p.row.title,role:'finished_recording_development',audio:p.audioAsset,reference:p.refAsset,
    sample_rate:p.audio.sampleRate,sample_frames:p.audio.frames,channels:p.audio.channels,duration_seconds:p.audio.duration,
    reference_support_seconds:p.reference.support_seconds,reference_excluded_seconds:p.excluded,
    qualification:{reference_tier:p.reference.reference_tier,owner_map_and_scope_accepted:true,full_song_alignment_accepted:p.excluded.length===0,
     independent_millisecond_timing_certified:false,supplied_producer_clock_available:p.proposal.source_clock_available,
     derived_from_current_estimator_prediction:!p.proposal.source_clock_available,
     same_estimator_evaluation_requires_reference_origin_disclosure:!p.proposal.source_clock_available,
     scope_note:p.reference.scope_basis},known_development_material:true,not_an_unseen_generalization_test:true,
    exposure_note:p.proposal.source_clock_available?'Supplied source and owner DAW listening/edits.':'Current app prediction followed by explicit owner listening approval; retain model-derived-reference provenance.',
    independent_original_click_millisecond_accuracy_certified:false,accepted_reference_is_already_audio_relative:true,additional_reference_offset_seconds:0,
    original_clocks:p.originalClocks,owner_review_records:[],owner_approved_project:projectAsset,
    original_clock_to_audio_offset_metadata:{total_seconds:p.proposal.proposed_offset_seconds,
     semantics:'Owner-saved DAW alignment readout; approved geometry is already source-audio-relative. Null when no supplied producer clock exists.',
     already_applied_in_accepted_tempo_map:true,additional_offset_to_apply_when_consuming_accepted_map_seconds:0},
    owner_revalidation:{decision_date_local:'2026-10-10',status:'owner_confirmed_new_formal_reference',record:RECORD+'/acceptance.json'},
    ...(p.excluded.length?{owner_excluded_reference_tail:{source_audio_seconds:p.excluded[0],reason:'Owner excludes the previously discussed uncovered tail from the reference scope.',no_grid_claim:false}}:{})};
   catalog.tracks.push(record);
   const previous=p.metadata.status;Object.assign(p.metadata,{status:'owner_accepted',previous_disposition_before_owner_confirmation:previous,
    enrolled_ids:[...new Set([...(p.metadata.enrolled_ids??[]),p.row.id])],registered_home:'registered',current_approved_reference:p.refAsset.path,
    owner_approved_project:p.approvedProjectPath,owner_acceptance_record:RECORD+'/acceptance.json',reference_tier:p.reference.reference_tier,
    source_clock_available:p.proposal.source_clock_available,owner_accepted_at_local:'2026-10-10'});
   Object.assign(p.entry,{status:'owner_accepted',enrolled_ids:p.metadata.enrolled_ids,registered_home:'registered',current_approved_reference:p.refAsset.path,
    owner_approved_project:p.approvedProjectPath,owner_acceptance_record:RECORD+'/acceptance.json',reference_tier:p.reference.reference_tier});
   p.entry.batch_records=[...new Set([...(p.entry.batch_records??[]),BATCH])];
   await atomic(path.join(SAMPLES,'ntm',p.row.slug,'recording.json'),p.metadata);
   addInventory(p.refAsset,'owner_confirmed_daw_reference');addInventory(projectAsset,'owner_confirmed_daw_workspace');addInventory(p.audioAsset,'retained_ntm_owner_approved_source_audio');
   for(const a of p.originalClocks)addInventory(a,'retained_ntm_original_clock_or_source_context');
   receipt.registrations.push({id:p.row.id,title:p.row.title,audio:p.audioAsset,reference:p.refAsset,approved_project:projectAsset,
    reviewed_project:p.sourceProjectPath,reviewed_proposal:p.sourceProposalPath,reference_support_seconds:p.reference.support_seconds,
    excluded_evaluation_seconds:p.excluded,reference_tier:p.reference.reference_tier,total_alignment_readout_seconds:p.proposal.proposed_offset_seconds,
    working_project_end_before_seconds:p.beforeEnd,working_project_end_after_seconds:p.project.projectDuration,
    audio_alignment_and_working_tempo_signature_events_unchanged:true});
  }
  const beforeAsset=asset(descriptorBytes,RECORD+'/source-descriptor-before-enrollment.json');await fs.writeFile(path.join(SAMPLES,beforeAsset.path),descriptorBytes,{flag:'wx'});addInventory(beforeAsset,'owner_enrollment_source_descriptor_snapshot');
  const receiptBytes=encoded(receipt),receiptAsset=asset(receiptBytes,RECORD+'/acceptance.json');await fs.writeFile(path.join(SAMPLES,receiptAsset.path),receiptBytes,{flag:'wx'});addInventory(receiptAsset,'owner_enrollment_acceptance_record');
  for(const t of catalog.tracks.filter(t=>EXPECTED.includes(t.id)))t.owner_review_records.push(receiptAsset);
  const counts={};for(const t of catalog.tracks)counts[t.role]=(counts[t.role]??0)+1;
  const formal=Object.fromEntries(Object.entries(counts).filter(([k])=>k.startsWith('formal_')||k==='finished_recording_development'));
  catalog.finished_recordings=counts.finished_recording_development;catalog.formal_sample_role_counts=formal;catalog.formal_samples=Object.values(formal).reduce((a,b)=>a+b,0);
  catalog.count_note=`Current formal cohort: ${catalog.finished_recordings} complete recordings, ${counts.formal_original_recording_excerpt} original excerpts and ${counts.formal_synthetic_recording} approved synthetic recording.`;
  catalog.previous_owner_enrollment=catalog.latest_owner_enrollment;
  catalog.latest_owner_enrollment={decision_date_local:'2026-10-10',registered_samples:plans.length,approved_ids:EXPECTED,receipt:receiptAsset.path};
  catalog.latest_offset_declaration_audit.membership_note='This dated audit covered the earlier 36 references; eight subsequent owner-approved enrollments are recorded separately.';
  descriptor.original_candidate_recordings=descriptor.recordings;descriptor.original_counts=descriptor.counts;descriptor.recordings=[];
  descriptor.counts={supplied_clock:0,source_only:0};descriptor.owner_acceptance_pending=false;descriptor.status='all_eight_owner_accepted_and_formally_enrolled';
  descriptor.catalog_and_accepted_references_unchanged=false;descriptor.acceptance_record=receiptAsset.path;
  descriptor.already_accepted_use_formal_library=[...(descriptor.already_accepted_use_formal_library??[]),...receipt.registrations.map(r=>({id:r.id,title:r.title,reference_path:r.reference.path,approved_project:r.approved_project.path}))];
  const acceptedCatalog={status:descriptor.status,owner_acceptance_pending:false,acceptance_record:receiptAsset.path,recordings:receipt.registrations};
  const acceptedBytes=encoded(acceptedCatalog),acceptedAsset=asset(acceptedBytes,BATCH+'/accepted-catalog.json');await fs.writeFile(path.join(SAMPLES,acceptedAsset.path),acceptedBytes,{flag:'wx'});addInventory(acceptedAsset,'owner_accepted_candidate_batch_catalog');
  const retained=new Map(inventory.assets.filter(a=>a.retained||a.copied).map(a=>[a.path,a]));inventory.unique_copied_files=retained.size;inventory.unique_copied_bytes=[...retained.values()].reduce((n,a)=>n+(a.bytes??0),0);
  await atomic(inventoryFile,inventory);await atomic(indexFile,index);await atomic(catalogFile,catalog);await atomic(descriptorFile,descriptor);
  console.log(JSON.stringify({enrolled:plans.map(p=>p.row.title),formal_samples:catalog.formal_samples,finished_recordings:catalog.finished_recordings,
   reference_scope_exclusion:receipt.return_to_earth_excluded_tail_seconds,
   over_it_corrected_project:plans.find(p=>p.row.id===OVER).approvedProjectPath,
   over_it_project_end_seconds:plans.find(p=>p.row.id===OVER).project.projectDuration,receipt:receiptAsset.path},null,2));
 }finally{await fs.rm(temp,{recursive:true,force:true});}
}
await main();
