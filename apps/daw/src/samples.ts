import { createProject, importAssets, uid, type Asset, type Project } from "./model";
import { positionAtQuarter, refreshMusicalAnchors, timeAtQuarter } from "./music";

export type ReferenceTempo = { seconds: number; bpm: number };
export type ReferenceMeter = { seconds: number; numerator: number; denominator: number };
export type ReferenceClicks = { beats: number[]; bars: number[] };
export type SampleComparison = ReferenceClicks & {
  label: string; tempos: ReferenceTempo[]; meters: ReferenceMeter[]; maxShiftMs: number;
};
export type SampleSummary = {
  id: string; title: string; role: string; duration: number; error?: string;
  bpmLabels: string[]; meterLabels: string[]; offset: number | null;
  support: number[][]; noGrid: number[][]; unknown:number[][];
  availableClock?:boolean; description?:string;
  audit: { codes: string[]; questions: string[]; notes:string[]; previousComparisonOffsetMs:number|null } | null; hasComparison?: boolean;
};
export type SampleReference = SampleSummary & ReferenceClicks & {
  libraryRoot: string; audioPath: string; referencePath: string;
  referenceVersion: { bytes: number; modifiedMs: number; catalogSha256: string };
  tempos: ReferenceTempo[]; meters: ReferenceMeter[];
  comparison: SampleComparison | null; previouslyAccepted: boolean;
  candidateDescriptorPath?:string;
  candidateDescriptorVersion?:{bytes:number;modifiedMs:number};
  sourceOffsetAlternatives?:{label:string;offset_seconds:number}[];
};
export type SampleLibrary = { root: string | null; tracks: SampleSummary[];descriptorPath?:string };
export type SampleReview = {
  reference: SampleReference; clipId: string; initialAudioOrigin: number;
  loadedVariant: "accepted" | "comparison"; note: string; mapImportWarning?: string;
};

const EPS = 1e-7;
/** Build a separate sample workspace, using accepted audio coordinates once.
 * Project padding preserves a cropped lead-in while putting the first audible
 * downbeat on a real bar. It does not redefine source or original DAW bar labels.
 */
export function sampleWorkspace(ref: SampleReference, asset: Asset, comparison = false): Project {
  if(ref.availableClock===false) {
    let project=createProject();
    project.name=`${ref.title} — source-only review`;
    project=importAssets(project,[asset],{mode:"sequence",copy:false,start:0,targetTrackId:null,beforeTrackId:null});
    project.clips[0].name=ref.title;project.tracks[0].name=ref.title;
    project.projectDuration=Math.max(30,asset.duration+2);project.rulerFormat="seconds";
    project.sampleReview={reference:ref,clipId:project.clips[0].id,initialAudioOrigin:0,loadedVariant:"accepted",note:"",
      mapImportWarning:"No supplied tempo/signature clock or offset. The whole-project working grid starts at 120 BPM and 4/4, with no declared points; these values are not source evidence."};
    return refreshMusicalAnchors(project);
  }
  const source = comparison && ref.comparison ? ref.comparison : ref;
  const tempo = [...source.tempos].sort((a,b)=>a.seconds-b.seconds);
  const meter = [...source.meters].sort((a,b)=>a.seconds-b.seconds);
  const initialRate = tempo.filter(e=>e.seconds<=0).at(-1)?.bpm ?? tempo[0].bpm;
  const initialMeter = meter.filter(e=>e.seconds<=0).at(-1) ?? meter[0];
  const changes = tempo.filter((e,i)=>e.seconds>0 && e.bpm!==(tempo[i-1]?.bpm ?? initialRate));
  function quarter(seconds: number) {
    let q=0, at=0, rate=initialRate;
    if (seconds<0) return seconds*rate/60;
    for (const event of changes) {
      if (seconds<=event.seconds) break;
      q+=(event.seconds-at)*rate/60; at=event.seconds; rate=event.bpm;
    }
    return q+(seconds-at)*rate/60;
  }
  const firstBar = source.bars[0];
  const firstBarQuarter = quarter(firstBar);
  const barLength = initialMeter.numerator*4/initialMeter.denominator;
  // Start at the previous full bar if the audio begins partway through a bar.
  let originQuarter = firstBarQuarter>EPS ? firstBarQuarter-barLength*Math.ceil(firstBarQuarter/barLength) : 0;
  if(!ref.previouslyAccepted) {
    // Whole-bar project padding permits positive offset comparisons without
    // moving audio before project zero or changing source timing.
    const latest=Math.max(0,...(ref.sourceOffsetAlternatives??[]).map(e=>e.offset_seconds-(ref.offset??0)));
    const barSeconds=barLength*60/initialRate;
    const paddingBars=Math.max(2,Math.ceil(latest/barSeconds)+1);
    originQuarter-=paddingBars*barLength;
  }
  let project=createProject();
  project.name=`${ref.title} — reference review`;
  project.bpm=initialRate;
  project.signature={numerator:initialMeter.numerator,denominator:initialMeter.denominator};
  project.tempos=[{id:uid(),quarter:0,bpm:initialRate,origin:"manual"},
    ...changes.map(e=>({id:uid(),quarter:quarter(e.seconds)-originQuarter,bpm:e.bpm,origin:"manual" as const}))];
  project.signatures=[{id:uid(),bar:1,numerator:initialMeter.numerator,denominator:initialMeter.denominator,origin:"manual"}];
  let warning="";
  for (const [index,event] of meter.entries()) {
    if (event.seconds<=0 || index===0 || event.numerator===meter[index-1]?.numerator&&event.denominator===meter[index-1]?.denominator) continue;
    const q=quarter(event.seconds)-originQuarter, pos=positionAtQuarter(project,q);
    if (Math.abs(q-pos.barStart)>EPS) {
      warning=`A stored signature boundary is between whole project bars. The ${ref.previouslyAccepted?"approved":"original supplied"} click remains available; review this boundary before editing the project signature map.`;
      break;
    }
    const existing=project.signatures.find(e=>e.bar===pos.bar);
    project.signatures=project.signatures.filter(e=>e.bar!==pos.bar);
    project.signatures.push({id:existing?.id??uid(),bar:pos.bar,numerator:event.numerator,denominator:event.denominator,origin:"manual"});
    project.signatures.sort((a,b)=>a.bar-b.bar);
  }
  const audioOrigin=timeAtQuarter(project,-originQuarter);
  project=importAssets(project,[asset],{mode:"sequence",copy:false,start:audioOrigin,targetTrackId:null,beforeTrackId:null});
  project.clips[0].name=ref.title; project.tracks[0].name=ref.title;
  project.projectDuration=Math.max(30,audioOrigin+asset.duration+2);
  project.rulerFormat="seconds";
  project.sampleReview={reference:ref,clipId:project.clips[0].id,initialAudioOrigin:audioOrigin,
    loadedVariant:comparison?"comparison":"accepted",note:"",mapImportWarning:warning||undefined};
  return refreshMusicalAnchors(project);
}

export function sampleClicks(project: Project, comparison = false): ReferenceClicks | undefined {
  const review=project.sampleReview, clip=project.clips.find(c=>c.id===review?.clipId);
  if (!review || !clip || review.reference.availableClock===false) return;
  const ref=comparison ? review.reference.comparison : review.reference;
  if (!ref) return;
  const origin=clip.start-clip.sourceStart;
  const inside=(t:number)=>t>=clip.sourceStart-1e-9&&t<clip.sourceStart+clip.duration;
  return {beats:ref.beats.filter(inside).map(t=>t+origin),bars:ref.bars.filter(inside).map(t=>t+origin)};
}

export const scopeText=(spans:number[][])=>spans.length?spans.map(([a,b])=>`${a.toFixed(3)}–${b.toFixed(3)} s`).join(", "):"None";
