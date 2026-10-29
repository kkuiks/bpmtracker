import type { AudioClock, Clock, MapSelection, Project, Snap, SignatureEvent, TempoEvent, TimeSignature } from "./model";
import { CLICK_GAIN_POLICY, upgradedClickGain } from "./click-level";
import { firstMapDownbeat, isMapDownbeat, isVariableMap, sourceMapState, sourceMapTime, validateVariableMap, type VariableMap } from "./analysis-map";

const id = () => crypto.randomUUID();
const EPS = 1e-8;
export function parseTimeSignature(text: string): TimeSignature | null {
  const match = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(text);
  if (!match) return null;
  const numerator = Number(match[1]), denominator = Number(match[2]);
  return Number.isInteger(numerator) && numerator >= 1 && numerator <= 32 && [1, 2, 4, 8, 16, 32].includes(denominator)
    ? { numerator, denominator } : null;
}
export const temposInOrder = (p: Project) => [...p.tempos].sort((a, b) => a.quarter - b.quarter);
export const signaturesInOrder = (p: Project): SignatureEvent[] => signatureSections(p)
  .filter((s) => s.id !== null).map((s) => ({ ...p.signatures.find((e) => e.id === s.id)!, quarter: s.quarter, bar: s.bar }));

function signatureSources(signatures: SignatureEvent[]): SignatureEvent[] {
  return signatures.flatMap(({ shortBar, ...point }) => !shortBar ? [point]
    : shortBar.original ? [{ ...point, ...shortBar.original }] : []);
}
/** User/analysis declarations, before calculated short bars are applied. */
export const signatureDeclarations = (p: Project) => signatureSources(signaturesInOrder(p));

/** Make every beat-aligned truncated bar explicit without changing its beat unit or phase. */
function completeSignatureBars(p: Project): SignatureEvent[] {
  const declarations = signatureDeclarations(p), result: SignatureEvent[] = [];
  let start = 0, signature = p.signature;
  for (const declaration of declarations) {
    const quarter = declaration.quarter!, length = signature.numerator * 4 / signature.denominator;
    const completeBars = Math.floor((quarter - start) / length + EPS);
    const barStart = start + completeBars * length, remainder = quarter - barStart;
    const beats = remainder * signature.denominator / 4, numerator = Math.round(beats);
    if (remainder > EPS && numerator >= 1 && numerator < signature.numerator && Math.abs(beats - numerator) < EPS) {
      const atStart = result.findIndex(point => Math.abs(point.quarter! - barStart) < EPS);
      const original = atStart >= 0 ? result[atStart] : null;
      const short: SignatureEvent = { ...(original ?? {
        id: `${declaration.id}:short-bar`, quarter: barStart, bar: 1, origin: "manual" as const,
      }), numerator, denominator: signature.denominator,
        shortBar: { followingId: declaration.id,
          ...(original ? { original: { numerator: original.numerator, denominator: original.denominator } } : {}) } };
      if (atStart >= 0) result[atStart] = short;
      else result.push(short);
    }
    result.push(declaration);
    start = quarter; signature = declaration;
  }
  return result;
}

/** Calculation sections include the whole-project value; it is not a declared point. */
export function tempoSections(p: Project): { id: string | null; quarter: number; bpm: number }[] {
  const points = temposInOrder(p);
  return points[0]?.quarter === 0 ? points : [{ id: null, quarter: 0, bpm: p.bpm }, ...points];
}
export function signatureSections(p: Project) {
  // Legacy bar-only declarations are resolved once, without moving old maps.
  const legacy = [...p.signatures].sort((a, b) => a.bar - b.bar);
  const oldPositions = new Map<string, number>();
  let oldQuarter = 0, oldBar = 1, oldLength = p.signature.numerator * 4 / p.signature.denominator;
  for (const event of legacy) {
    oldQuarter += (event.bar - oldBar) * oldLength;
    oldPositions.set(event.id, oldQuarter); oldBar = event.bar;
    oldLength = event.numerator * 4 / event.denominator;
  }
  const points: { id: string | null; quarter: number; numerator: number; denominator: number }[] = p.signatures
    .map((event) => ({ ...event, quarter: event.quarter ?? oldPositions.get(event.id)! }))
    .sort((a, b) => a.quarter - b.quarter);
  if (points[0]?.quarter !== 0) points.unshift({ id: null, quarter: 0, ...p.signature });
  let previousQuarter = 0, previousBar = 1, previousLength = p.signature.numerator * 4 / p.signature.denominator;
  return points.map((event, index) => {
    // A signature at an old beat inside a bar closes that partial bar.
    const bar = index === 0 ? 1 : previousBar + Math.ceil((event.quarter - previousQuarter) / previousLength - EPS);
    previousQuarter = event.quarter; previousBar = bar;
    previousLength = event.numerator * 4 / event.denominator;
    return { ...event, bar, barLength: previousLength };
  });
}
export function quarterAtBar(p: Project, bar: number): number {
  const section = signatureSections(p).filter((s) => s.bar <= bar).at(-1) ?? signatureSections(p)[0];
  return section.quarter + (bar - section.bar) * section.barLength;
}
export function positionAtQuarter(p: Project, quarter: number) {
  const section = signatureSections(p).filter((s) => s.quarter <= quarter + EPS).at(-1) ?? signatureSections(p)[0];
  const bars = Math.floor((quarter - section.quarter + EPS) / section.barLength);
  const barStart = section.quarter + bars * section.barLength;
  const beats = Math.max(0, (quarter - barStart) * section.denominator / 4);
  const beat = Math.floor(beats + EPS);
  const withinBeat = Math.max(0, quarter - barStart - beat * 4 / section.denominator);
  const sixteenth = Math.floor(withinBeat * 4 + EPS);
  return { bar: section.bar + bars, beat: beat + 1, sixteenth: sixteenth + 1,
    tick: Math.min(119, Math.max(0, Math.floor((withinBeat * 4 - sixteenth + EPS) * 120))), barStart, signature: section };
}
export function timeAtQuarter(p: Project, quarter: number): number {
  const events = tempoSections(p);
  let seconds = 0;
  if (quarter < 0) return quarter * 60 / events[0].bpm;
  for (let i = 0; i < events.length; i++) {
    const stop = Math.min(quarter, events[i + 1]?.quarter ?? quarter);
    seconds += Math.max(0, stop - events[i].quarter) * 60 / events[i].bpm;
    if (stop >= quarter) break;
  }
  return seconds;
}
export function quarterAtTime(p: Project, seconds: number): number {
  const events = tempoSections(p);
  let at = 0;
  if (seconds < 0) return seconds * events[0].bpm / 60;
  for (let i = 0; i < events.length; i++) {
    const duration = ((events[i + 1]?.quarter ?? Infinity) - events[i].quarter) * 60 / events[i].bpm;
    if (seconds <= at + duration + EPS) return events[i].quarter + (seconds - at) * events[i].bpm / 60;
    at += duration;
  }
  return 0;
}
export const timeAtBar = (p: Project, bar: number) => timeAtQuarter(p, quarterAtBar(p, bar));
export const tempoAtQuarter = (p: Project, quarter: number) => tempoSections(p).filter((t) => t.quarter <= quarter + EPS).at(-1) ?? tempoSections(p)[0];
export function musicalTime(p: Project, seconds: number) {
  const pos = positionAtQuarter(p, quarterAtTime(p, seconds));
  return `${pos.bar}.${pos.beat}.${pos.sixteenth}.${pos.tick}`;
}
export function parseMusicalTime(p: Project, text: string): number | null {
  const match = /^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?$/.exec(text.trim());
  if (!match) return null;
  const bar = Number(match[1]), beat = Number(match[2] ?? 1), sixteenth = Number(match[3] ?? 1), tick = Number(match[4] ?? 0);
  if (bar < 1 || beat < 1 || sixteenth < 1 || tick < 0 || tick > 119) return null;
  const quarter = quarterAtBar(p, bar), signature = positionAtQuarter(p, quarter).signature;
  if (beat > signature.numerator) return null;
  const remainder = (sixteenth - 1 + tick / 120) / 4;
  if (remainder >= 4 / signature.denominator - EPS) return null;
  const target = quarter + (beat - 1) * 4 / signature.denominator + remainder;
  // Positions beyond the end of a partial bar belong to its successor.
  if (positionAtQuarter(p, target).bar !== bar) return null;
  return timeAtQuarter(p, target);
}
export function snapToProject(p: Project, seconds: number, mode: Snap): number {
  if (mode === "off") return Math.max(0, seconds);
  if (mode === "second") return Math.max(0, Math.round(seconds));
  const quarter = quarterAtTime(p, seconds), pos = positionAtQuarter(p, quarter);
  if (mode === "bar") {
    const before = timeAtQuarter(p, pos.barStart), after = timeAtBar(p, pos.bar + 1);
    return Math.max(0, seconds - before <= after - seconds ? before : after);
  }
  const step = mode === "beat" ? 4 / pos.signature.denominator : { half: 2, quarter: 1, eighth: .5, sixteenth: .25 }[mode];
  const snapped = pos.barStart + Math.round((quarter - pos.barStart) / step) * step;
  return Math.max(0, timeAtQuarter(p, snapped));
}

/** One project grid drives the ruler, snap, transport, click and map exports. */
export function projectClocks(p: Project, end = p.projectDuration): AudioClock[] {
  const last = quarterAtTime(p, end);
  const quarters = [...new Set([0, last, ...p.tempos.map((t) => t.quarter), ...signatureSections(p).map((s) => s.quarter)])].filter((q) => q >= 0 && q <= last).sort((a, b) => a - b);
  return quarters.slice(0, -1).map((quarter, i) => {
    const tempo = tempoAtQuarter(p, quarter), pos = positionAtQuarter(p, quarter);
    const start = timeAtQuarter(p, quarter);
    return { id: `${tempo.id ?? "whole-tempo"}:${pos.signature.id ?? "whole-signature"}`, bpm: tempo.bpm, numerator: pos.signature.numerator, denominator: pos.signature.denominator,
      offset: 0, start, end: timeAtQuarter(p, quarters[i + 1]), phase: start - (quarter - pos.barStart) * 60 / tempo.bpm };
  });
}
export function gridLines(p: Project, start: number, end: number, scale: number) {
  const lines: { time: number; strong: boolean; bar: number; beat: number }[] = [];
  const from = quarterAtTime(p, Math.max(0, start)), to = quarterAtTime(p, end);
  const sections = signatureSections(p);
  for (let i = 0; i < sections.length; i++) {
    const section = sections[i], stop = Math.min(to, sections[i + 1]?.quarter ?? to);
    if (stop < from || section.quarter > to) continue;
    const beatLength = 4 / section.denominator;
    const visibleStart = Math.max(from, section.quarter);
    const fastest = Math.max(tempoAtQuarter(p, visibleStart).bpm, ...p.tempos.filter((t) => t.quarter >= visibleStart && t.quarter <= stop).map((t) => t.bpm));
    const barPixels = section.barLength * 60 / fastest * scale;
    const barsPerLine = Math.max(1, 2 ** Math.ceil(Math.log2(35 / Math.max(.001, barPixels))));
    const beatVisible = barPixels / section.numerator >= 10 && barsPerLine === 1;
    const step = beatVisible ? beatLength : section.barLength * barsPerLine;
    const first = section.quarter + Math.ceil((Math.max(from, section.quarter) - section.quarter - EPS) / step) * step;
    for (let quarter = first, count = 0; quarter <= stop + EPS && count < 12000; quarter += step, count++) {
      if (i + 1 < sections.length && quarter >= sections[i + 1].quarter - EPS) break;
      const pos = positionAtQuarter(p, quarter);
      lines.push({ time: timeAtQuarter(p, quarter), strong: pos.beat === 1, bar: pos.bar, beat: pos.beat });
    }
  }
  return lines;
}
export function refreshMusicalAnchors(p: Project): Project {
  const musical = new Set(p.tracks.filter((t) => t.timeBase === "musical").map((t) => t.id));
  return { ...p, clips: p.clips.map((clip) => ({ ...clip, musicalStart: musical.has(clip.trackId) ? quarterAtTime(p, clip.start) : undefined })) };
}
type InitialMapValues = Pick<Project, "bpm" | "signature" | "initialTempoFollowsFirst" | "initialSignatureFollowsFirst">;
/** Materialize followed values before computing coordinates, so playback and exports agree. */
function initialMapValues(p: Project, tempos: TempoEvent[], signatures: SignatureEvent[], whole: Partial<InitialMapValues>): InitialMapValues {
  const followTempo = whole.initialTempoFollowsFirst ?? (whole.bpm === undefined && p.initialTempoFollowsFirst === true);
  const followSignature = whole.initialSignatureFollowsFirst ?? (whole.signature === undefined && p.initialSignatureFollowsFirst === true);
  const firstTempo = [...tempos].sort((a, b) => a.quarter - b.quarter)[0];
  const firstSignature = signatureSources(signatures).sort((a, b) =>
    (a.quarter ?? quarterAtBar(p, a.bar)) - (b.quarter ?? quarterAtBar(p, b.bar)))[0];
  return {
    bpm: followTempo ? firstTempo?.bpm ?? 120 : whole.bpm ?? p.bpm,
    signature: followSignature ? firstSignature
      ? { numerator: firstSignature.numerator, denominator: firstSignature.denominator }
      : { numerator: 4, denominator: 4 } : whole.signature ?? p.signature,
    initialTempoFollowsFirst: followTempo && !!firstTempo,
    initialSignatureFollowsFirst: followSignature && !!firstSignature,
  };
}
export function editProjectMap(p: Project, tempos = p.tempos, signatures = p.signatures,
  whole: Partial<InitialMapValues> = {}): Project {
  const positioned = signatureSources(signatures).map((s) => s.quarter === undefined && Number(p.version) >= 3
    ? { ...s, quarter: quarterAtBar(p, s.bar) } : s);
  const next: Project = { ...p, ...initialMapValues(p, tempos, positioned, whole), version: 3,
    tempos: [...tempos].sort((a, b) => a.quarter - b.quarter), signatures: positioned };
  next.signatures = completeSignatureBars(next);
  next.signatures = signaturesInOrder(next);
  const musical = new Set(p.tracks.filter((t) => t.timeBase === "musical").map((t) => t.id));
  next.clips = p.clips.map((clip) => musical.has(clip.trackId)
    ? { ...clip, start: timeAtQuarter(next, clip.musicalStart ?? quarterAtTime(p, clip.start)) }
    : clip);
  next.clocks = p.clocks.map((clock) => {
    const clip = next.clips.find((c) => c.id === clock.clipId);
    return clip ? { ...clock, projectOrigin: clip.start - clip.sourceStart } : clock;
  });
  return refreshMusicalAnchors(next);
}
/** Manual declarations keep their audio times; only their grid coordinates change. */
export function editMapAtTimes(p: Project, tempos = p.tempos, signatures = p.signatures,
  whole: Partial<InitialMapValues> = {}): Project {
  const initial = initialMapValues(p, tempos, signatures, whole);
  const timedTempos = tempos.map(event => ({ event, seconds: timeAtQuarter(p, event.quarter) }))
    .sort((a, b) => a.seconds - b.seconds);
  let quarter = 0, seconds = 0, bpm = initial.bpm;
  const sameTempoMap = tempos === p.tempos && initial.bpm === p.bpm;
  const positionedTempos = sameTempoMap ? tempos : timedTempos.map(({ event, seconds: target }) => {
    quarter += (target - seconds) * bpm / 60;
    seconds = target; bpm = event.bpm;
    return { ...event, quarter };
  });
  const grid = { ...p, ...initial, tempos: positionedTempos };
  const positionedSignatures = signatureSources(signatures).map(event => ({ ...event,
    quarter: sameTempoMap ? event.quarter ?? quarterAtBar(p, event.bar)
      : quarterAtTime(grid, timeAtQuarter(p, event.quarter ?? quarterAtBar(p, event.bar))) }));
  return editProjectMap(p, positionedTempos, positionedSignatures, initial);
}
/** Removing the first declaration makes the next declaration the initial state, even after time zero. */
export function removeMapEvents(p: Project, selection: MapSelection[]): Project {
  const tempoIds = new Set(selection.filter(point => point.kind === "tempo").map(point => point.id));
  const signatureIds = new Set(selection.filter(point => point.kind === "signature").map(point => point.id));
  const tempos = p.tempos.filter(event => !tempoIds.has(event.id));
  const orderedSignatures = signatureDeclarations(p);
  const signatures = orderedSignatures.filter(event => !signatureIds.has(event.id));
  if (tempos.length === p.tempos.length && signatures.length === orderedSignatures.length) return p;
  const firstTempo = temposInOrder(p)[0];
  const firstSignature = orderedSignatures[0];
  const whole: Partial<InitialMapValues> = {};
  if (firstTempo && tempoIds.has(firstTempo.id)) {
    whole.bpm = temposInOrder({ ...p, tempos })[0]?.bpm ?? 120;
    whole.initialTempoFollowsFirst = tempos.length > 0;
  }
  if (firstSignature && signatureIds.has(firstSignature.id)) {
    const next = orderedSignatures.find(event => !signatureIds.has(event.id));
    whole.signature = next ? { numerator: next.numerator, denominator: next.denominator }
      : { numerator: 4, denominator: 4 };
    whole.initialSignatureFollowsFirst = signatures.length > 0;
  }
  return editMapAtTimes(p, tempos, signatures, whole);
}
export function setTrackTimeBase(p: Project, trackId: string, timeBase: "linear" | "musical"): Project {
  return refreshMusicalAnchors({ ...p, tracks: p.tracks.map((track) => track.id === trackId ? { ...track, timeBase } : track) });
}
export function putTempo(p: Project, event: TempoEvent): Project {
  const quarter = Math.max(0, event.quarter);
  const collision = p.tempos.find((t) => Math.abs(t.quarter - quarter) < EPS);
  const tempos = [...p.tempos.filter((t) => t.id !== event.id && t.id !== collision?.id), { ...event, id: collision?.id ?? event.id, quarter }];
  return editMapAtTimes({ ...p, timingPolicy: "persistent" }, tempos);
}
export function putSignature(p: Project, event: SignatureEvent): Project {
  const quarter = Math.max(0, event.quarter ?? quarterAtBar(p, Math.max(1, Math.round(event.bar))));
  const { shortBar, ...declaration } = event;
  const existing = signatureDeclarations(p), collision = existing.find((s) => Math.abs(s.quarter! - quarter) < EPS);
  const before = { ...p, signatures: existing.filter((s) => s.id !== event.id && s.id !== collision?.id) };
  const pos = positionAtQuarter(before, quarter), beats=(quarter-pos.barStart)*pos.signature.denominator/4;
  const samePosition = existing.some(s => s.id === event.id && Math.abs(s.quarter! - quarter) < EPS);
  if (!samePosition && Math.abs(beats-Math.round(beats))>EPS) throw new Error("Place the signature on an existing beat boundary.");
  const signatures = [...existing.filter((s) => s.id !== event.id && s.id !== collision?.id),
    { ...declaration, id: collision?.id ?? event.id, quarter }];
  return editMapAtTimes({ ...p, timingPolicy: "persistent" }, undefined, signatures);
}

/** Migration keeps source-relative evidence intact; old scope clocks are not silently made global. */
export function upgradeProject(input: Project): Project {
  const legacy = Number(input.version) === 1;
  type OldTempo = Omit<TempoEvent, "origin"> & { origin: "default" | "manual" | "analysis"; retainedInitialFor?: string };
  type OldSignature = Omit<SignatureEvent, "origin"> & { origin: "default" | "manual" | "analysis"; retainedInitialFor?: string };
  const tempos: OldTempo[] = legacy ? [] : input.tempos ?? [];
  const signatures: OldSignature[] = legacy ? [] : input.signatures ?? [];
  const firstTempo = [...tempos].sort((a, b) => a.quarter - b.quarter)[0];
  const firstSignature = [...signatures].sort((a, b) => a.bar - b.bar)[0];
  const explicitTempo = [...tempos].sort((a, b) => a.quarter - b.quarter).find(t => t.origin !== "default");
  const explicitSignature = [...signatures].sort((a, b) => a.bar - b.bar).find(s => s.origin !== "default");
  const oldTempo = input.timingPolicy !== "persistent" && firstTempo?.origin === "default" ? explicitTempo ?? firstTempo : firstTempo;
  const oldSignature = input.timingPolicy !== "persistent" && firstSignature?.origin === "default" ? explicitSignature ?? firstSignature : firstSignature;
  const hasWholeValues = !legacy && Number.isFinite(input.bpm) && !!input.signature;
  const p: Project = { ...input, version: 3,
    tracks: input.tracks.map((track) => ({ ...track, timeBase: legacy ? "linear" : track.timeBase })),
    bpm: hasWholeValues ? input.bpm : oldTempo?.bpm ?? 120,
    signature: hasWholeValues ? input.signature : { numerator: oldSignature?.numerator ?? 4, denominator: oldSignature?.denominator ?? 4 },
    // Only identified automatic points disappear. User/source/analysis declarations stay.
    tempos: tempos.filter((t): t is OldTempo & { origin: "manual" | "analysis" } => t.origin !== "default" && !t.retainedInitialFor)
      .map(({ retainedInitialFor, ...event }) => event),
    signatures: signatures.filter((s): s is OldSignature & { origin: "manual" | "analysis" } => s.origin !== "default" && !s.retainedInitialFor)
      .map(({ retainedInitialFor, ...event }) => event),
    projectDuration: legacy ? Math.max(1800, ...input.clips.map((c) => c.start + c.duration)) : input.projectDuration,
    rulerFormat: legacy ? "bars" : input.rulerFormat,
    timingPolicy: "persistent",
    clickGain: upgradedClickGain(input.clickGain,input.clickGainPolicy),clickGainPolicy:CLICK_GAIN_POLICY };
  p.signatures = signaturesInOrder(p);
  const leadingTempo = temposInOrder(p)[0], leadingSignature = signatureDeclarations(p)[0];
  // Earlier builds stored only a copied value. A missing identified analysis
  // initial point also proves deletion when a later edit already broke that copy.
  const deletedAnalysisStart = (kind: "tempo" | "signature", first: TempoEvent | SignatureEvent) =>
    !!first.analysisId && p.analyses.some(analysis => analysis.id === first.analysisId && isVariableMap(analysis.result))
      && !(kind === "tempo" ? p.tempos : p.signatures).some(point => point.id === `${first.analysisId}:${kind}:initial`);
  const oldFollowingTempo = !legacy && Number(input.version) === 3 && leadingTempo && leadingTempo.quarter > EPS
    && (leadingTempo.bpm === p.bpm || deletedAnalysisStart("tempo", leadingTempo));
  const oldFollowingSignature = !legacy && Number(input.version) === 3 && leadingSignature && leadingSignature.quarter! > EPS
    && ((leadingSignature.numerator === p.signature.numerator && leadingSignature.denominator === p.signature.denominator)
      || deletedAnalysisStart("signature", leadingSignature));
  const initial = initialMapValues(p, p.tempos, p.signatures, {
    initialTempoFollowsFirst: input.initialTempoFollowsFirst ?? !!oldFollowingTempo,
    initialSignatureFollowsFirst: input.initialSignatureFollowsFirst ?? !!oldFollowingSignature,
  });
  if (initial.bpm !== p.bpm || initial.signature.numerator !== p.signature.numerator
      || initial.signature.denominator !== p.signature.denominator) {
    // Repair old copied values without moving declarations or physical audio.
    const repaired = editMapAtTimes(p, p.tempos, p.signatures, initial);
    return refreshMusicalAnchors({ ...repaired, clips: p.clips, clocks: p.clocks });
  }
  Object.assign(p, initial);
  p.signatures = completeSignatureBars(p);
  p.signatures = signaturesInOrder(p);
  // Opening migrates in memory and preserves physical audio and all source evidence.
  return legacy || !hasWholeValues || p.tempos.length !== tempos.length || p.signatures.length !== signatures.length
    ? refreshMusicalAnchors(p) : p;
}

/** A result is arranged onto a real project bar; source-relative evidence is unchanged. */
function mapForClock(p: Project, clock: Clock, bar: number, phaseOffset: number) {
  const quarter = quarterAtBar(p, bar);
  const start = quarter - phaseOffset * clock.values.bpm / 60;
  if (start < -EPS) return null;
  const scopeStartQuarter = Math.max(0, Math.abs(start) < EPS ? 0 : start);
  let tempos = p.tempos;
  if (tempos.length) {
    tempos = tempos.filter((t) => Math.abs(t.quarter - scopeStartQuarter) >= EPS);
    tempos.push({ id: p.tempos.find((t) => Math.abs(t.quarter - scopeStartQuarter) < EPS)?.id ?? id(), quarter: scopeStartQuarter,
      bpm: clock.values.bpm, origin: "analysis", analysisId: clock.analysisId });
  }
  let signatures = signatureDeclarations(p);
  if (signatures.length) {
    signatures = signatures.filter((s) => s.bar !== bar);
    signatures.push({ id: p.signatures.find((s) => s.bar === bar)?.id ?? id(), bar,
      numerator: clock.values.numerator, denominator: clock.values.denominator, origin: "analysis", analysisId: clock.analysisId });
  }
  return editProjectMap({ ...p, timingPolicy: "persistent" }, tempos, signatures);
}
export function clockPlacement(p: Project, clock: Clock, linked = true) {
  if (clock.kind === "map") return variableClockPlacement(p, clock, linked);
  const reference = p.clips.find((clip) => clip.id === clock.clipId);
  if (!reference) throw new Error("Select an existing reference event to align this saved analysis.");
  const scopeStart = Math.max(clock.sourceStart, reference.sourceStart);
  const scopeEnd = Math.min(clock.sourceEnd, reference.sourceStart + reference.duration);
  if (scopeEnd <= scopeStart) throw new Error("This event contains no audio from the analyzed source range.");
  const barSeconds = 60 / clock.values.bpm * 4 / clock.values.denominator * clock.values.numerator;
  const phaseOffset = (((clock.sourceStart + clock.values.offset - scopeStart) % barSeconds) + barSeconds) % barSeconds;
  // Only arrange the evidence that remains in this fragment. Stored values and
  // the original source scope still belong to the immutable analysis receipt.
  clock = { ...clock, sourceStart: scopeStart, sourceEnd: scopeEnd };
  if (phaseOffset >= clock.sourceEnd - clock.sourceStart - EPS)
    throw new Error("This scope contains no downbeat to align. Choose a longer analyzed range or edit its saved clock.");
  const phase = reference.start - reference.sourceStart + clock.sourceStart + phaseOffset;
  // Reapplication replaces only this analysis's untouched map declarations.
  // Manual edits and other analyses remain real project points.
  const tempos = p.tempos.filter(event => event.origin !== "analysis" || event.analysisId !== clock.analysisId);
  const signatures = signatureDeclarations(p).filter(event => event.origin !== "analysis" || event.analysisId !== clock.analysisId);
  const base: Project = { ...p, tempos, signatures,
    bpm: tempos.length ? p.bpm : clock.values.bpm,
    signature: signatures.length ? p.signature : { numerator: clock.values.numerator, denominator: clock.values.denominator },
    initialTempoFollowsFirst: tempos.length > 0 && p.initialTempoFollowsFirst === true,
    initialSignatureFollowsFirst: signatures.length > 0 && p.initialSignatureFollowsFirst === true };
  const affected = p.clips.filter((clip) => clip.id === reference.id || (linked && reference.groupId && clip.groupId === reference.groupId));
  const minimum = Math.min(...affected.map((clip) => clip.start));
  const pos = positionAtQuarter(base, quarterAtTime(base, Math.max(0, phase)));
  const before = timeAtBar(base, Math.max(1, pos.bar)), after = timeAtBar(base, Math.max(1, pos.bar + 1));
  let bar = phase - before <= after - phase ? Math.max(1, pos.bar) : Math.max(1, pos.bar + 1);
  let mapped: Project | null = null, anchor = 0;
  // Include the lead-in beats at the inferred tempo. Re-evaluate the real bar
  // time after replacing the scope, rather than shifting to an obsolete grid.
  for (let attempts = 0; attempts < 10000; attempts++, bar++) {
    mapped = mapForClock(base, clock, bar, phaseOffset);
    if (!mapped) continue;
    anchor = timeAtBar(mapped, bar);
    if (anchor - phase >= -minimum - EPS) break;
    mapped = null;
  }
  if (!mapped) throw new Error("There is not enough project space before the first downbeat. Move the song later and apply again.");
  return { reference, affected, phase, phaseOffset, bar, anchor, delta: anchor - phase, mapped };
}

function variableClockPlacement(p: Project, clock: Clock, linked: boolean) {
  const analysis = p.analyses.find(item => item.id === clock.analysisId);
  const reference = p.clips.find(item => item.id === clock.clipId);
  if (!analysis || !isVariableMap(analysis.result) || !reference)
    throw new Error("The original analyzed map or reference event is missing.");
  const map: VariableMap = analysis.result;
  validateVariableMap(map);
  const from = Math.max(clock.sourceStart, reference.sourceStart) - analysis.sourceStart;
  const to = Math.min(clock.sourceEnd, reference.sourceStart + reference.duration) - analysis.sourceStart;
  if (to <= from) throw new Error("This event contains no audio from the analyzed range.");
  const firstBar = firstMapDownbeat(map, from, to);
  if (firstBar === null) throw new Error("This scope contains no downbeat to align. Choose a longer analyzed range.");
  const anchorSource = sourceMapTime(map, sourceMapState(map, from).barStart);
  const origin = reference.start - reference.sourceStart + analysis.sourceStart;
  const phase = origin + firstBar;
  const tempos = p.tempos.filter(event => event.origin !== "analysis" || event.analysisId !== clock.analysisId);
  const signatures = signatureDeclarations(p).filter(event => event.origin !== "analysis" || event.analysisId !== clock.analysisId);
  const affected = p.clips.filter(clip => clip.id === reference.id || (linked && reference.groupId && clip.groupId === reference.groupId));
  const firstState = sourceMapState(map, anchorSource);
  const whole = !tempos.length && !signatures.length && affected.length === p.clips.length
    ? { bpm: firstState.bpm, signature: { numerator: firstState.numerator, denominator: firstState.denominator } } : {};
  const base = editMapAtTimes(p, tempos, signatures, whole);
  const baseSignatures = signatureDeclarations(base);
  const minimum = Math.min(...affected.map(clip => clip.start));
  const position = positionAtQuarter(base, quarterAtTime(base, Math.max(0, phase)));
  const before = timeAtBar(base, Math.max(1, position.bar)), after = timeAtBar(base, position.bar + 1);
  let targetBar = Math.max(1, phase - before <= after - phase ? position.bar : position.bar + 1);
  let anchor = 0, delta = 0, initialTime = 0;
  for (let attempts = 0; attempts < 10000; attempts++, targetBar++) {
    anchor = timeAtBar(base, targetBar); delta = anchor - phase;
    initialTime = origin + anchorSource + delta;
    if (minimum + delta >= -EPS && initialTime >= -EPS) break;
    if (attempts === 9999) throw new Error("Move the song later to make room for its opening beats.");
  }
  initialTime = Math.max(0, initialTime);
  const projectOrigin = origin + delta, finalTime = projectOrigin + to;
  const additions = map.events.map((event, index) => ({ event, index }))
    .filter(({ event }) => event.time > anchorSource + EPS && event.time < to - EPS);
  const tempoAdditions = [{ time: initialTime, bpm: firstState.bpm, key: "initial" },
    ...additions.flatMap(({ event, index }) => event.bpm === undefined ? [] : [{ time: projectOrigin + event.time, bpm: event.bpm, key: String(index) }])];
  const signatureAdditions = [{ time: initialTime, numerator: firstState.numerator, denominator: firstState.denominator, key: "initial" },
    ...additions.flatMap(({ event, index }) => event.numerator === undefined ? [] : [{ time: projectOrigin + event.time,
      numerator: event.numerator, denominator: event.denominator!, key: String(index) }])];
  for (const event of base.tempos) {
    const time = timeAtQuarter(base, event.quarter);
    if (time >= initialTime - EPS && time < finalTime - EPS
        && Math.abs(event.bpm - sourceMapState(map, time - projectOrigin).bpm) > EPS)
      throw new Error(`The tempo point at ${musicalTime(p, time)} conflicts with this analysis. Move or remove it before applying.`);
  }
  for (const event of baseSignatures) {
    const time = timeAtQuarter(base, event.quarter ?? quarterAtBar(base, event.bar));
    if (time < initialTime - EPS || time >= finalTime - EPS) continue;
    const state = sourceMapState(map, time - projectOrigin);
    if (event.numerator !== state.numerator || event.denominator !== state.denominator || !isMapDownbeat(map, time - projectOrigin))
      throw new Error(`The signature point at ${musicalTime(p, time)} conflicts with this analysis. Move or remove it before applying.`);
  }
  const newTempos = [...base.tempos, ...tempoAdditions.flatMap(event =>
    base.tempos.some(point => Math.abs(timeAtQuarter(base, point.quarter) - event.time) < EPS) ? [] : [{
      id: `${clock.analysisId}:tempo:${event.key}`, quarter: quarterAtTime(base, event.time), bpm: event.bpm,
      origin: "analysis" as const, analysisId: clock.analysisId }])];
  const newSignatures = [...baseSignatures, ...signatureAdditions.flatMap(event =>
    baseSignatures.some(point => Math.abs(timeAtQuarter(base, point.quarter ?? quarterAtBar(base, point.bar)) - event.time) < EPS) ? [] : [{
      id: `${clock.analysisId}:signature:${event.key}`, quarter: quarterAtTime(base, event.time),
      bar: positionAtQuarter(base, quarterAtTime(base, event.time)).bar,
      numerator: event.numerator, denominator: event.denominator, origin: "analysis" as const, analysisId: clock.analysisId }])];
  const mapped = editMapAtTimes(base, newTempos, newSignatures);
  const bar = positionAtQuarter(mapped, quarterAtTime(mapped, anchor)).bar;
  return { reference, affected, phase, phaseOffset: firstBar - from, bar, anchor, delta, mapped };
}
export function placeClockOnProject(p: Project, clock: Clock, linked = true) {
  const { affected, bar, anchor, delta, mapped } = clockPlacement(p, clock, linked);
  let next = editProjectMap(p, mapped.tempos, mapped.signatures, { bpm: mapped.bpm, signature: mapped.signature,
    initialTempoFollowsFirst: mapped.initialTempoFollowsFirst ?? false,
    initialSignatureFollowsFirst: mapped.initialSignatureFollowsFirst ?? false });
  // Explicit alignment moves this song and its linked stems together. Each
  // track keeps its chosen time base; other Musical events follow the map edit.
  const ids = new Set(affected.map((clip) => clip.id));
  next.clips = next.clips.map((clip) => ids.has(clip.id) ? { ...clip, start: Math.max(0, p.clips.find((c) => c.id === clip.id)!.start + delta) } : clip);
  next.clocks = next.clocks.map((saved) => {
    const clip = next.clips.find((c) => c.id === saved.clipId);
    return clip ? { ...saved, projectOrigin: clip.start - clip.sourceStart } : saved;
  });
  next.projectDuration = Math.max(next.projectDuration, ...next.clips.map((clip) => clip.start + clip.duration));
  return { project: refreshMusicalAnchors(next), delta, bar, anchor };
}
