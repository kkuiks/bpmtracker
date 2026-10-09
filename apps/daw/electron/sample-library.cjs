const fs = require("node:fs/promises");
const path = require("node:path");

const auditFolder = "reviews/20261010-formal-audit-v1";
const time = (event) => typeof event === "number" ? event :
  event.master_seconds ?? event.audio_seconds ?? event.time_seconds ?? event.project_seconds;
const intervals = (value) => !value?.length ? [] :
  typeof value[0] === "number" ? [value] : value;
const json = async (filename) => JSON.parse(await fs.readFile(filename, "utf8"));
const auditNotes={
  duplicate_tempo_declarations:"Equal BPM redeclarations are combined in the working timeline.",
  same_meter_phase_marker:"A repeated signature preserves phase context rather than a new meter change.",
  timing_records_outside_scope:"The stored clock has out-of-scope records; approved audition filters them.",
  substantive_decimal:"The source contains real decimal BPM. An integer comparison remains a proposal.",
  already_accepted_source_conflict:"Source projects disagree on meter. The existing owner-approved interpretation is retained.",
  accepted_large_scale_grid:"The approved grid is a large-scale interpretation; detailed source meter changes are unavailable.",
  half_note_click:"Quarter BPM and half-note click BPM use different pulse units.",
  unaccepted_review_offset:"A prior comparison offset is a draft; it has not replaced the approved offset.",
};

async function member(root, relative) {
  if (typeof relative !== "string" || path.isAbsolute(relative)) throw new Error("Invalid sample asset path");
  const filename = await fs.realpath(path.resolve(root, relative));
  const inside = path.relative(await fs.realpath(root), filename);
  if (inside.startsWith("..") || path.isAbsolute(inside)) throw new Error("Sample assets must remain in the selected library");
  return filename;
}

function bpmLabel(rate) {
  let best = { value: Math.round(rate), numerator: Math.round(rate), denominator: 1 };
  for (let d = 2; d <= 4; d++) {
    const n = Math.round(rate*d);
    if (Math.abs(n/d-rate) < Math.abs(best.value-rate)-1e-10) best = { value:n/d, numerator:n, denominator:d };
  }
  if (Math.abs(60e6/rate-60e6/best.value) > 1.00001) return Number(rate.toFixed(6)).toString();
  return best.denominator === 1 ? String(best.numerator) : `${best.numerator}/${best.denominator}`;
}

async function catalog(root) {
  const data = await json(await member(root,"catalog.json"));
  if (!Array.isArray(data.tracks)) throw new Error("Choose a sample library containing catalog.json");
  return data.tracks.filter(t=>typeof t.role === "string" && !t.role.startsWith("auxiliary"));
}

async function reference(root, id) {
  const track = (await catalog(root)).find(t=>t.id === id);
  if (!track) throw new Error("This recording is not an enrolled formal sample");
  const refPath = await member(root,track.reference.path);
  const [ref, stat, audioPath] = await Promise.all([json(refPath),fs.stat(refPath),member(root,track.audio.path)]);
  const duration = track.duration_seconds;
  const support = intervals(track.reference_support_seconds);
  const noGrid = [...intervals(ref.free_time_seconds),...intervals(ref.evaluation_scope?.no_grid_tail_seconds)];
  const unknown=[];
  let coveredTo=0;
  for(const [a,b] of [...support,...noGrid].sort((x,y)=>x[0]-y[0])){
    const start=Math.max(0,a),end=Math.min(duration,b);
    if(start>coveredTo+1e-4)unknown.push([coveredTo,start]);
    coveredTo=Math.max(coveredTo,end);
  }
  if(coveredTo<duration-1e-4)unknown.push([coveredTo,duration]);
  const halfOpen = !!ref.free_time_seconds || ref.evaluation_scope?.boundary_semantics?.includes("half-open");
  const audible = t=>Number.isFinite(t) && t>=-1e-9 && t<duration &&
    support.some(([a,b])=>t>=a-1e-9 && (halfOpen?t<b-1e-9:t<=b+1e-9)) &&
    !noGrid.some(([a,b])=>t>=a-1e-9 && t<b-1e-9);
  const chosen = values=>[...new Set(values.map(time).filter(audible).map(t=>Math.max(0,t)))].sort((a,b)=>a-b);
  let tempos = (ref.tempo_events??[]).map(e=>({seconds:time(e),bpm:e.bpm_quarter??e.bpm??e.quarter_bpm}));
  if (!tempos.length && ref.quarter_bpm) tempos=[{seconds:ref.first_beat_source_seconds,bpm:ref.quarter_bpm}];
  let meters=(ref.meter_events??[]).map(e=>({seconds:time(e),numerator:e.numerator,denominator:e.denominator}));
  if (!meters.length && typeof ref.meter === "object") meters=[{seconds:ref.first_beat_source_seconds,...ref.meter}];
  const beats=chosen(ref.approved_click_beats_seconds??ref.beats_seconds??ref.beat_times_seconds??ref.quarter_events??[]);
  const bars=chosen(ref.downbeats_seconds??ref.bar_starts_seconds??ref.bar_events??
    (ref.quarter_events??[]).filter(e=>e.bar_start??e.accent));
  if (!tempos.length || !meters.length || !beats.length || !bars.length) throw new Error("The accepted reference is missing readable tempo, meter or bar timing");
  if (tempos.some(e=>!Number.isFinite(e.seconds)||!Number.isFinite(e.bpm)||e.bpm<=0) ||
      meters.some(e=>!Number.isFinite(e.seconds)||!Number.isInteger(e.numerator)||!Number.isInteger(e.denominator)))
    throw new Error("The accepted map contains invalid events");
  const offset=track.original_clock_to_audio_offset_metadata?.total_seconds ?? ref.accepted_offset_seconds ?? ref.offset_seconds ?? ref.source_origin_shift_seconds ?? null;
  let audit=null;
  try {
    const report=await json(path.join(root,auditFolder,"audit.json"));
    const entry=report.tracks.find(t=>t.id===id);
    if (entry?.accepted_reference_bytes===stat.size && Math.abs(entry.accepted_reference_mtime_ns/1e6-stat.mtimeMs)<1)
      audit={codes:entry.issues.map(e=>e.code),questions:entry.issues.filter(e=>e.requires_owner_decision).map(e=>e.code),
        notes:[...new Set(entry.issues.map(e=>auditNotes[e.code]).filter(Boolean))],
        previousComparisonOffsetMs:entry.existing_revalidation_record_summary?.status==="draft"?
          entry.existing_revalidation_record_summary.comparison_offset_ms:null};
  } catch { /* Catalog and accepted reference remain usable without an audit. */ }
  let comparison=null;
  if (id==="state_shirt_hospital_hill") {
    try {
      const value=await json(path.join(root,auditFolder,"hospital-hill-comparison.json"));
      if (value.accepted_reference_version?.bytes===stat.size && Math.abs(value.accepted_reference_version.modifiedMs-stat.mtimeMs)<1)
        comparison={label:"102 / 110 BPM",tempos:value.candidate.tempo_events.map(e=>({seconds:e.time_seconds,bpm:e.bpm_quarter})),
          meters:[{seconds:0,numerator:4,denominator:4}],beats:value.candidate.beats_seconds,bars:value.candidate.downbeats_seconds,
          maxShiftMs:value.max_abs_matched_beat_shift_milliseconds};
    } catch { /* A comparison is optional and never the accepted reference. */ }
  }
  return {id,title:track.title,role:track.role,libraryRoot:root,audioPath,referencePath:track.reference.path,
    duration,support,noGrid,unknown,offset,tempos,meters,beats,bars,
    bpmLabels:[...new Set(tempos.map(e=>bpmLabel(e.bpm)))],
    meterLabels:[...new Set(meters.map(e=>`${e.numerator}/${e.denominator}`))],
    referenceVersion:{bytes:stat.size,modifiedMs:stat.mtimeMs,catalogSha256:track.reference.sha256},
    audit,comparison,previouslyAccepted:true};
}

async function list(root) {
  const tracks=await catalog(root);
  const records=await Promise.all(tracks.map(async t=>{
    try {const r=await reference(root,t.id);return {id:r.id,title:r.title,role:r.role,duration:r.duration,
      bpmLabels:r.bpmLabels,meterLabels:r.meterLabels,offset:r.offset,support:r.support,noGrid:r.noGrid,unknown:r.unknown,
      audit:r.audit,hasComparison:!!r.comparison};}
    catch(e){return {id:t.id,title:t.title,role:t.role,error:e.message};}
  }));
  return {root,tracks:records};
}

async function candidateDescriptor(root, filename) {
  const descriptorPath=await member(root,path.relative(root,filename));
  const descriptor=await json(descriptorPath);
  if(descriptor.format!=="joljak-candidate-review"||descriptor.schema_version!==1||!Array.isArray(descriptor.recordings))
    throw new Error("Select a prepared daw-review.json candidate descriptor");
  return {descriptor,descriptorPath,stat:await fs.stat(descriptorPath)};
}

async function allowedCandidate(root,row) {
  const exclusions=await json(await member(root,"excluded-candidates.json"));
  const identity=value=>String(value??"").toLowerCase().replace(/&/g,"and").replace(/[^a-z0-9]/g,"");
  for(const excluded of exclusions.candidates??[]) {
    if(!excluded.permanent_exclusion&&excluded.review_enabled!==false)continue;
    if([excluded.id,excluded.slug].includes(row.id)||[excluded.id,excluded.slug].includes(row.slug)||
       excluded.session_id!=null&&row.session_id!=null&&String(excluded.session_id)===String(row.session_id)||
       row.title&&(identity(row.title)===identity(excluded.title)||
         excluded.artist&&excluded.song&&identity(row.title).includes(identity(excluded.artist))&&identity(row.title).includes(identity(excluded.song))))
      throw new Error("This source is excluded from collection and review");
  }
}

async function candidateReference(root,filename,id) {
  const {descriptor,descriptorPath,stat:descriptorStat}=await candidateDescriptor(root,filename);
  const row=descriptor.recordings.find(r=>r.id===id);
  if(!row)throw new Error("Candidate not found in this review descriptor");
  await allowedCandidate(root,row);
  const enrolled=await catalog(root);
  if(enrolled.some(t=>t.id===id||t.audio.path.split(/[\\/]/)[0]==="ntm"&&t.audio.path.split(/[\\/]/)[1]===row.slug))
    throw new Error("This candidate is enrolled. Open its formal library entry");
  const referencePath=await member(root,row.reference_path);
  const [source,stat,audioPath]=await Promise.all([json(referencePath),fs.stat(referencePath),member(root,row.audio_path)]);
  if(source.human_alignment_accepted)throw new Error("This source is already approved. Open its formal library entry");
  if(row.review_mode==="source_only") {
    if(source.slug!==undefined&&source.slug!==row.slug||source.audio!==undefined&&source.audio!==row.audio_path)
      throw new Error("Source-only identity or audio path changed");
    if(source.tempo_events?.length&&source.meter_events?.length&&source.quarters?.length&&source.bars?.length)
      throw new Error("A supplied clock is now prepared. Refresh this candidate descriptor");
    const duration=row.source_audio_geometry?.duration_seconds;
    if(!Number.isFinite(duration)||duration<=0||duration!==row.duration_seconds)
      throw new Error("Source-only audio duration is missing or inconsistent");
    return {id,title:row.title,role:"unreviewed_source_only",availableClock:false,libraryRoot:root,audioPath,
      referencePath:row.reference_path,duration,support:[],noGrid:[],unknown:[[0,duration]],offset:null,
      tempos:[],meters:[],beats:[],bars:[],bpmLabels:[],meterLabels:[],audit:null,comparison:null,
      referenceVersion:{bytes:stat.size,modifiedMs:stat.mtimeMs,catalogSha256:""},
      candidateDescriptorPath:descriptorPath,candidateDescriptorVersion:{bytes:descriptorStat.size,modifiedMs:descriptorStat.mtimeMs},
      sourceOffsetAlternatives:[],previouslyAccepted:false,description:row.description??"No supplied tempo/signature clock."};
  }
  if(source.slug!==row.slug||source.audio!==row.audio_path)throw new Error("Candidate source identity or audio path changed");
  const offset=row.initial_offset_seconds,scale=row.source_time_scale??1,duration=source.duration_seconds;
  if(![offset,scale,duration,source.project_end_seconds].every(Number.isFinite)||scale<=0||duration<=0)
    throw new Error("Candidate duration, source extent or offset is missing");
  const relative=e=>typeof e==="object"&&(e.master_seconds!==undefined||e.audio_seconds!==undefined);
  const audioTime=e=>relative(e)?time(e):time(e)*scale+offset;
  let tempos=(source.tempo_events??[]).map(e=>({seconds:audioTime(e),bpm:(e.bpm??e.bpm_quarter)/(relative(e)?1:scale)})).sort((a,b)=>a.seconds-b.seconds);
  let meters=(source.meter_events??[]).map(e=>({seconds:audioTime(e),numerator:e.numerator,denominator:e.denominator})).sort((a,b)=>a.seconds-b.seconds);
  if(!tempos.length||!meters.length)throw new Error("A usable supplied tempo/signature clock has not been prepared");
  if(tempos.some(e=>!Number.isFinite(e.seconds)||!Number.isFinite(e.bpm)||e.bpm<=0)||
     meters.some(e=>!Number.isFinite(e.seconds)||!Number.isInteger(e.numerator)||e.numerator<1||![1,2,4,8,16,32].includes(e.denominator)))
    throw new Error("The supplied clock contains invalid tempo or signature values");
  const start=Math.max(0,tempos[0].seconds,meters[0].seconds,(source.source_range_start_seconds??0)*scale+offset);
  const end=Math.min(duration,source.project_end_seconds*scale+offset);
  if(!(end>start))throw new Error("The supplied clock does not overlap this recording");
  const state=events=>[...events.filter(e=>e.seconds<=start).slice(-1),...events.filter(e=>e.seconds>start&&e.seconds<end)];
  tempos=state(tempos);meters=state(meters);
  const chosen=values=>[...new Set(values.map(audioTime).filter(t=>Number.isFinite(t)&&t>=start-1e-9&&t<end).map(t=>Math.max(0,t)))].sort((a,b)=>a-b);
  const beats=chosen(source.quarters??source.quarter_events??[]),bars=chosen(source.bars??source.bar_events??[]);
  if(!beats.length||!bars.length)throw new Error("The candidate has no supplied beat/bar timing in the Master scope");
  const unknown=[];if(start>1e-4)unknown.push([0,start]);if(end<duration-1e-4)unknown.push([end,duration]);
  return {id,title:row.title,role:"unreviewed_candidate",availableClock:true,libraryRoot:root,audioPath,
    referencePath:row.reference_path,duration,support:[[start,end]],noGrid:[],unknown,offset,
    tempos,meters,beats,bars,bpmLabels:[...new Set(tempos.map(e=>bpmLabel(e.bpm)))],
    meterLabels:[...new Set(meters.map(e=>`${e.numerator}/${e.denominator}`))],audit:null,comparison:null,
    referenceVersion:{bytes:stat.size,modifiedMs:stat.mtimeMs,catalogSha256:""},
    candidateDescriptorPath:descriptorPath,candidateDescriptorVersion:{bytes:descriptorStat.size,modifiedMs:descriptorStat.mtimeMs},
    sourceOffsetAlternatives:row.source_offset_alternatives??[],previouslyAccepted:false,
    description:row.description??source.description??""};
}

async function candidateList(root,filename) {
  const {descriptor,descriptorPath}=await candidateDescriptor(root,filename);
  const tracks=await Promise.all(descriptor.recordings.map(async row=>{
    try{return await candidateReference(root,descriptorPath,row.id);}
    catch(e){return {id:row.id,title:row.title,role:"unreviewed_candidate",error:e.message};}
  }));
  return {root,descriptorPath,tracks};
}

async function saveDraft(root, project) {
  const review=project.sampleReview;
  if (!review || !/^[a-zA-Z0-9_.-]+$/.test(review.reference.id)) throw new Error("Open a formal sample before saving its draft");
  const current=review.reference.candidateDescriptorPath?
    await candidateReference(root,review.reference.candidateDescriptorPath,review.reference.id):await reference(root,review.reference.id);
  if (current.referencePath!==review.reference.referencePath ||
      current.referenceVersion.bytes!==review.reference.referenceVersion.bytes ||
      current.referenceVersion.modifiedMs!==review.reference.referenceVersion.modifiedMs||
      current.candidateDescriptorVersion?.modifiedMs!==review.reference.candidateDescriptorVersion?.modifiedMs||
      current.candidateDescriptorVersion?.bytes!==review.reference.candidateDescriptorVersion?.bytes)
    throw new Error("The source reference changed. Reopen this recording before saving a new draft");
  const clip=project.clips.find(c=>c.id===review.clipId);
  if (!clip) throw new Error("The sample event was removed. Restore it before saving a reference draft");
  const directory=path.join(root,"reviews","daw-drafts",current.id,new Date().toISOString().replace(/[:.]/g,"-"));
  await fs.mkdir(directory,{recursive:true});
  const snapshot=structuredClone(project);
  for (const asset of snapshot.assets) asset.sourcePath=path.relative(directory,asset.sourcePath);
  const proposal={schema_version:1,status:"proposed_not_accepted",sample_id:current.id,
    saved_at_utc:new Date().toISOString(),accepted_reference_path:current.referencePath,
    accepted_reference_version:current.referenceVersion,source_audio_origin_seconds:clip.start-clip.sourceStart,
    source_reference_status:current.previouslyAccepted?"approved_formal_reference":current.availableClock===false?"unreviewed_source_only":"unreviewed_candidate",
    source_clock_available:current.availableClock!==false,
    initial_source_offset_seconds:current.offset,
    additional_alignment_adjustment_ms:current.availableClock===false?null:(review.initialAudioOrigin-clip.start+clip.sourceStart)*1000,
    proposed_offset_seconds:current.offset===null?null:current.offset+review.initialAudioOrigin-clip.start+clip.sourceStart,
    source_range_seconds:[clip.sourceStart,clip.sourceStart+clip.duration],
    approved_support_seconds:current.support,approved_no_grid_seconds:current.noGrid,
    project_bpm:project.bpm,project_signature:project.signature,
    project_tempos:project.tempos,project_signatures:project.signatures,note:review.note,
    project_file:"project.joljak",accepted_reference_and_catalog_unchanged:true};
  await fs.writeFile(path.join(directory,"project.joljak"),JSON.stringify(snapshot,null,2)+"\n",{flag:"wx"});
  await fs.writeFile(path.join(directory,"proposal.json"),JSON.stringify(proposal,null,2)+"\n",{flag:"wx"});
  return path.join(directory,"project.joljak");
}

module.exports={list,reference,saveDraft,catalog,candidateReference,candidateList};
