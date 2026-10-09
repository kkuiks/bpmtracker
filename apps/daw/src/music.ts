import type { AudioClock, Clock, Project, Snap, SignatureEvent, TempoEvent } from "./model";
import { CLICK_GAIN_POLICY, upgradedClickGain } from "./click-level";

const id = () => crypto.randomUUID();
const EPS = 1e-8;
export const temposInOrder = (p: Project) => [...p.tempos].sort((a, b) => a.quarter - b.quarter);
export const signaturesInOrder = (p: Project) => [...p.signatures].sort((a, b) => a.bar - b.bar);

/** Calculation sections include the whole-project value; it is not a declared point. */
export function tempoSections(p: Project): { id: string | null; quarter: number; bpm: number }[] {
  const points = temposInOrder(p);
  return points[0]?.quarter === 0 ? points : [{ id: null, quarter: 0, bpm: p.bpm }, ...points];
}
export function signatureSections(p: Project) {
  const points: { id: string | null; bar: number; numerator: number; denominator: number }[] = signaturesInOrder(p);
  if (points[0]?.bar !== 1) points.unshift({ id: null, bar: 1, ...p.signature });
  let quarter = 0, previousBar = 1, previousLength = p.signature.numerator * 4 / p.signature.denominator;
  return points.map((event) => {
    quarter += (event.bar - previousBar) * previousLength;
    previousBar = event.bar;
    previousLength = event.numerator * 4 / event.denominator;
    return { ...event, quarter, barLength: previousLength };
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
  return timeAtQuarter(p, quarter + (beat - 1) * 4 / signature.denominator + remainder);
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
export function editProjectMap(p: Project, tempos = p.tempos, signatures = p.signatures,
  whole: Partial<Pick<Project, "bpm" | "signature">> = {}): Project {
  const next = { ...p, ...whole, tempos: [...tempos].sort((a, b) => a.quarter - b.quarter), signatures: [...signatures].sort((a, b) => a.bar - b.bar) };
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
export function setTrackTimeBase(p: Project, trackId: string, timeBase: "linear" | "musical"): Project {
  return refreshMusicalAnchors({ ...p, tracks: p.tracks.map((track) => track.id === trackId ? { ...track, timeBase } : track) });
}
export function putTempo(p: Project, event: TempoEvent): Project {
  const quarter = Math.max(0, event.quarter);
  const collision = p.tempos.find((t) => Math.abs(t.quarter - quarter) < EPS);
  const tempos = [...p.tempos.filter((t) => t.id !== event.id && t.id !== collision?.id), { ...event, id: collision?.id ?? event.id, quarter }];
  return editProjectMap({ ...p, timingPolicy: "persistent" }, tempos);
}
export function putSignature(p: Project, event: SignatureEvent): Project {
  const bar = Math.max(1, Math.round(event.bar)), collision = p.signatures.find((s) => s.bar === bar);
  const signatures = [...p.signatures.filter((s) => s.id !== event.id && s.id !== collision?.id), { ...event, id: collision?.id ?? event.id, bar }];
  return editProjectMap({ ...p, timingPolicy: "persistent" }, undefined, signatures);
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
  const p: Project = { ...input, version: 2,
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
  let signatures = p.signatures;
  if (signatures.length) {
    signatures = signatures.filter((s) => s.bar !== bar);
    signatures.push({ id: p.signatures.find((s) => s.bar === bar)?.id ?? id(), bar,
      numerator: clock.values.numerator, denominator: clock.values.denominator, origin: "analysis", analysisId: clock.analysisId });
  }
  return { ...p, tempos, signatures, timingPolicy: "persistent" as const };
}
export function clockPlacement(p: Project, clock: Clock, linked = true) {
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
  const signatures = p.signatures.filter(event => event.origin !== "analysis" || event.analysisId !== clock.analysisId);
  const base: Project = { ...p, tempos, signatures,
    bpm: tempos.length ? p.bpm : clock.values.bpm,
    signature: signatures.length ? p.signature : { numerator: clock.values.numerator, denominator: clock.values.denominator } };
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
export function placeClockOnProject(p: Project, clock: Clock, linked = true) {
  const { affected, bar, anchor, delta, mapped } = clockPlacement(p, clock, linked);
  let next = editProjectMap(p, mapped.tempos, mapped.signatures, { bpm: mapped.bpm, signature: mapped.signature });
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
