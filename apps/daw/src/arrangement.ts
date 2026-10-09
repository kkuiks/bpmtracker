import { clipEnd, relatedClips, type ArrangementSelection, type Project, type SignatureEvent, type TempoEvent } from "./model";
import { editProjectMap, positionAtQuarter, quarterAtBar, quarterAtTime, refreshMusicalAnchors, signaturesInOrder, temposInOrder, timeAtBar, timeAtQuarter } from "./music";

const EPS = 1e-8;
const selectedIds = (selection: ArrangementSelection, kind: "tempo" | "signature") =>
  new Set(selection.maps.filter(item => item.kind === kind).map(item => item.id));

/** The destination grid excludes moving declarations and uses whole-project values. */
export function arrangementDestination(p: Project, selection: ArrangementSelection): Project {
  const tempoIds = selectedIds(selection, "tempo"), signatureIds = selectedIds(selection, "signature");
  const tempos = p.tempos.filter(event => !tempoIds.has(event.id));
  const signatures = p.signatures.filter(event => !signatureIds.has(event.id));
  return { ...p, tempos: tempos.sort((a,b) => a.quarter-b.quarter), signatures: signatures.sort((a,b) => a.bar-b.bar) };
}

export function arrangementBounds(p: Project, selection: ArrangementSelection, linked: boolean) {
  const clips = relatedClips(p, selection.clips, linked);
  const points = selection.maps.flatMap(item => {
    if (item.kind === "tempo") {
      const event = p.tempos.find(event => event.id === item.id);
      return event ? [timeAtQuarter(p, event.quarter)] : [];
    }
    const event = p.signatures.find(event => event.id === item.id);
    return event ? [timeAtBar(p, event.bar)] : [];
  });
  const starts = [...clips.map(clip => clip.start), ...points];
  return starts.length ? { start: Math.min(...starts), end: Math.max(...clips.map(clipEnd), ...points),
    audioCount: clips.length, tempoCount: selection.maps.filter(item => item.kind === "tempo").length,
    signatureCount: selection.maps.filter(item => item.kind === "signature").length } : null;
}

export function arrangementShift(p: Project, selection: ArrangementSelection, linked: boolean,
  amount: number, unit: "bars" | "beats") {
  const bounds = arrangementBounds(p, selection, linked);
  if (!bounds || !Number.isFinite(amount)) return 0;
  const grid = arrangementDestination(p, selection), quarter = quarterAtTime(grid, bounds.start);
  const position = positionAtQuarter(grid, quarter);
  let target: number;
  if (unit === "bars") {
    if (!Number.isInteger(amount) || position.bar+amount < 1) throw new Error("Enter a whole bar shift inside the project.");
    target = quarterAtBar(grid, position.bar+amount)+(quarter-position.barStart);
  } else target = quarter+amount*4/position.signature.denominator;
  if (target < -EPS) throw new Error("The selection would move before project start.");
  return timeAtQuarter(grid, Math.max(0,target))-bounds.start;
}

function movedTempos(p: Project, grid: Project, selected: Set<string>, delta: number) {
  const fixed = temposInOrder(grid);
  const moving = p.tempos.filter(event => selected.has(event.id))
    .map(event => ({ event, seconds: timeAtQuarter(p,event.quarter)+delta }))
    .sort((a,b) => a.seconds-b.seconds);
  const result: TempoEvent[] = [];
  let i=0, j=0, quarter=0, seconds=0, bpm=grid.bpm;
  while (i<fixed.length || j<moving.length) {
    const stationary = fixed[i], translated = moving[j];
    const stationaryTime = stationary ? seconds+(stationary.quarter-quarter)*60/bpm : Infinity;
    if (translated && Math.abs(translated.seconds-stationaryTime)<=EPS) {
      throw new Error("The move overlaps an unselected tempo point. Select that point too or choose another destination.");
    } else if (translated && translated.seconds<stationaryTime) {
      const targetQuarter=quarter+(translated.seconds-seconds)*bpm/60;
      if (targetQuarter < quarter-EPS) throw new Error("Tempo points would cross in this move.");
      result.push({ ...translated.event, quarter: Math.max(0,targetQuarter), origin: "manual" });
      quarter=targetQuarter;seconds=translated.seconds;bpm=translated.event.bpm;j++;
    } else {
      result.push(stationary);quarter=stationary.quarter;seconds=stationaryTime;bpm=stationary.bpm;i++;
    }
  }
  return result;
}

function movedSignatures(p: Project, grid: Project, selected: Set<string>, delta: number) {
  const fixed = signaturesInOrder(grid);
  const moving = p.signatures.filter(event => selected.has(event.id))
    .map(event => ({ event, quarter: quarterAtTime(grid,timeAtBar(p,event.bar)+delta) }))
    .sort((a,b) => a.quarter-b.quarter);
  const result: SignatureEvent[] = [];
  let i=0,j=0,bar=1,quarter=0,length=grid.signature.numerator*4/grid.signature.denominator;
  while (i<fixed.length || j<moving.length) {
    const stationary=fixed[i], translated=moving[j];
    const stationaryQuarter=stationary ? quarter+(stationary.bar-bar)*length : Infinity;
    if (translated && Math.abs(translated.quarter-stationaryQuarter)<=EPS) {
      throw new Error("The move overlaps an unselected signature point. Select that point too or choose another destination.");
    } else if (translated && translated.quarter<stationaryQuarter) {
      const bars=(translated.quarter-quarter)/length;
      if (bars < -EPS || Math.abs(bars-Math.round(bars))>1e-7)
        throw new Error("This move puts a signature between whole bars. Use a compatible bar destination or include its clock context.");
      bar+=Math.round(bars);quarter=translated.quarter;
      result.push({ ...translated.event,bar,origin:"manual" });
      length=translated.event.numerator*4/translated.event.denominator;j++;
    } else {
      result.push(stationary);bar=stationary.bar;quarter=stationaryQuarter;
      length=stationary.numerator*4/stationary.denominator;i++;
    }
  }
  return result;
}

/** One atomic time translation for audio and clock points, also used for previews. */
export function moveArrangement(p: Project, selection: ArrangementSelection, delta: number, linked: boolean): Project {
  const bounds=arrangementBounds(p,selection,linked);
  if (!bounds || Math.abs(delta)<=EPS) return p;
  if (!Number.isFinite(delta) || bounds.start+delta < -EPS)
    throw new Error("The selection would move before project start.");
  const clips=relatedClips(p,selection.clips,linked), ids=new Set(clips.map(clip => clip.id));
  const destination=arrangementDestination(p,selection);
  const tempos=movedTempos(p,destination,selectedIds(selection,"tempo"),delta);
  const signatures=movedSignatures(p,{...destination,tempos},selectedIds(selection,"signature"),delta);
  let next=editProjectMap(p,tempos,signatures);
  next.clips=next.clips.map(clip => ids.has(clip.id)
    ? {...clip,start:Math.max(0,p.clips.find(original=>original.id===clip.id)!.start+delta)} : clip);
  next.clocks=next.clocks.map(clock => {
    const clip=next.clips.find(clip=>clip.id===clock.clipId);
    return clip ? {...clock,projectOrigin:clip.start-clip.sourceStart} : clock;
  });
  if (p.sampleReview && selection.maps.length && ids.has(p.sampleReview.clipId))
    next.sampleReview={...p.sampleReview,initialAudioOrigin:p.sampleReview.initialAudioOrigin+delta};
  const movedTimes=selection.maps.map(item => item.kind==="tempo"
    ? timeAtQuarter(next,next.tempos.find(event=>event.id===item.id)!.quarter)
    : timeAtBar(next,next.signatures.find(event=>event.id===item.id)!.bar));
  selection.maps.forEach((item,index)=>{
    const original=item.kind==="tempo"?timeAtQuarter(p,p.tempos.find(event=>event.id===item.id)!.quarter):timeAtBar(p,p.signatures.find(event=>event.id===item.id)!.bar);
    if(Math.abs(movedTimes[index]-original-delta)>1e-6)
      throw new Error("The destination cannot preserve the selected audio/clock alignment. No items were moved.");
  });
  next.projectDuration=Math.max(p.projectDuration,...next.clips.map(clipEnd),...movedTimes.map(time=>time+1));
  return refreshMusicalAnchors(next);
}
