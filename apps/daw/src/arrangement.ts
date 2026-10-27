import { clipEnd, relatedClips, type ArrangementSelection, type Project, type SignatureEvent, type TempoEvent } from "./model";
import { editMapAtTimes, editProjectMap, positionAtQuarter, quarterAtBar, quarterAtTime, refreshMusicalAnchors, signaturesInOrder, temposInOrder, timeAtBar, timeAtQuarter } from "./music";

const EPS = 1e-8;
const selectedIds = (selection: ArrangementSelection, kind: "tempo" | "signature") =>
  new Set(selection.maps.filter(item => item.kind === kind).map(item => item.id));

/** The destination grid excludes moving declarations and uses whole-project values. */
export function arrangementDestination(p: Project, selection: ArrangementSelection): Project {
  const tempoIds = selectedIds(selection, "tempo"), signatureIds = selectedIds(selection, "signature");
  if (!tempoIds.size && !signatureIds.size) return p;
  const tempos = p.tempos.filter(event => !tempoIds.has(event.id));
  const signatures = p.signatures.filter(event => !signatureIds.has(event.id));
  return editMapAtTimes(p, tempos, signatures);
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
  const timed = temposInOrder(p)
    .map(event => ({ event, seconds: timeAtQuarter(p,event.quarter)+(selected.has(event.id)?delta:0) }))
    .sort((a,b) => a.seconds-b.seconds);
  let quarter=0, seconds=0, bpm=grid.bpm;
  return timed.map(({event,seconds:target},index): TempoEvent => {
    if (index && Math.abs(target-timed[index-1].seconds)<=EPS)
      throw new Error("The move overlaps an unselected tempo point. Select that point too or choose another destination.");
    quarter+=(target-seconds)*bpm/60;
    seconds=target;bpm=event.bpm;
    return {...event,quarter:Math.max(0,quarter),origin:selected.has(event.id)?"manual":event.origin};
  });
}

function movedSignatures(p: Project, grid: Project, selected: Set<string>, delta: number) {
  const result = signaturesInOrder(p).map((event): SignatureEvent => ({...event,
    quarter:quarterAtTime(grid,timeAtQuarter(p,event.quarter!)+(selected.has(event.id)?delta:0)),
    origin:selected.has(event.id)?"manual":event.origin}))
    .sort((a,b) => a.quarter!-b.quarter!);
  let quarter=0, denominator=grid.signature.denominator;
  for (let index=0; index<result.length; index++) {
    const event=result[index], target=event.quarter!;
    if (index && Math.abs(target-result[index-1].quarter!)<=EPS)
      throw new Error("The move overlaps an unselected signature point. Select that point too or choose another destination.");
    const beats=(target-quarter)*denominator/4;
    if (selected.has(event.id) && (target < -EPS || Math.abs(beats-Math.round(beats))>1e-7))
      throw new Error("Place the signature on an existing beat boundary.");
    quarter=target;denominator=event.denominator;
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
  const tempoIds=selectedIds(selection,"tempo");
  const tempos=tempoIds.size?movedTempos(p,destination,tempoIds,delta):p.tempos;
  const signatures=selection.maps.length?movedSignatures(p,{...destination,tempos},selectedIds(selection,"signature"),delta):p.signatures;
  let next=editProjectMap(p,tempos,signatures);
  next.clips=next.clips.map(clip => ids.has(clip.id)
    ? {...clip,start:Math.max(0,p.clips.find(original=>original.id===clip.id)!.start+delta)} : clip);
  next.clocks=next.clocks.map(clock => {
    const clip=next.clips.find(clip=>clip.id===clock.clipId);
    return clip ? {...clock,projectOrigin:clip.start-clip.sourceStart} : clock;
  });
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
