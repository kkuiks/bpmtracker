import { musicalTime, projectClocks, snapToProject } from "./music";
import type { SampleReview, SampleLibrary, SampleReference } from "./samples";
import { DEFAULT_CLICK_GAIN, CLICK_GAIN_POLICY } from "./click-level";

export type Asset = {
  id: string;
  name: string;
  sourcePath: string;
  pcmPath: string;
  peaksPath: string;
  playbackPath?: string;
  playbackRate?: number;
  playbackFrames?: number;
  sampleRate: number;
  channels: number;
  frames: number;
  duration: number;
  peakBinFrames: number;
  peakBins: number;
  originalSize: number;
  originalModified: number;
};
export type Track = {
  id: string;
  name: string;
  color: string;
  gain: number;
  pan: number;
  mute: boolean;
  solo: boolean;
  timeBase: "linear" | "musical";
};
export type Clip = {
  id: string;
  trackId: string;
  assetId: string;
  name: string;
  start: number;
  sourceStart: number;
  duration: number;
  groupId: string | null;
  musicalStart?: number;
};
export type ClockValues = {
  bpm: number;
  numerator: number;
  denominator: number;
  offset: number;
};
export type Clock = {
  projectOrigin?: number;
  id: string;
  clipId: string;
  name: string;
  sourceStart: number;
  sourceEnd: number;
  values: ClockValues;
  original: ClockValues;
  analysisId: string;
};
export type Analysis = {
  id: string;
  clipId: string;
  assetId: string;
  sourceStart: number;
  sourceEnd: number;
  initialTap: number | null;
  createdAt: string;
  result: Record<string, any>;
  recordPath: string;
};
export type TempoEvent = {
  id: string;
  quarter: number;
  bpm: number;
  origin: "manual" | "analysis";
  analysisId?: string;
};
export type TimeSignature = { numerator: number; denominator: number };
export type SignatureEvent = {
  id: string;
  bar: number;
  numerator: number;
  denominator: number;
  origin: "manual" | "analysis";
  analysisId?: string;
};
export type MapSelection = { kind: "tempo" | "signature"; id: string };
export type ArrangementSelection = { clips: string[]; maps: MapSelection[] };
export type Project = {
  format: "joljak-project";
  version: 2;
  id: string;
  name: string;
  assets: Asset[];
  tracks: Track[];
  clips: Clip[];
  clocks: Clock[];
  analyses: Analysis[];
  masterGain: number;
  clickGain: number;
  clickGainPolicy?: typeof CLICK_GAIN_POLICY;
  sampleRate: number;
  notes: string;
  bpm: number;
  signature: TimeSignature;
  tempos: TempoEvent[];
  signatures: SignatureEvent[];
  projectDuration: number;
  rulerFormat: "bars" | "seconds";
  timingPolicy?: "persistent";
  sampleReview?: SampleReview;
};
export type TimeRange = { start: number; end: number; trackIds: string[] };
export type AudioClipboard = {
  kind: "events" | "range";
  origin: number;
  duration: number;
  clips: Clip[];
  clocks: Clock[];
  assets: Asset[];
  tracks: Track[];
  analyses: Analysis[];
};
export type Tool = "object" | "range" | "split" | "erase";
export type Snap =
  | "off"
  | "bar"
  | "beat"
  | "half"
  | "quarter"
  | "eighth"
  | "sixteenth"
  | "second";
export type ImportOptions = {
  mode: "stems" | "tracks" | "sequence";
  copy: boolean;
  start: number;
  targetTrackId: string | null;
  beforeTrackId: string | null;
};
export type ImportDestination = {
  start: number;
  targetTrackId: string | null;
  beforeTrackId: string | null;
  source: "cursor" | "timeline" | "track-list";
};
export type JobEvent = {
  id: string;
  kind: string;
  stage: string;
  progress?: number;
  message?: string;
  result?: any;
  error?: string;
};
export type AudioClip = Clip & {
  sampleRate: number;
  channels: number;
  frames: number;
  gain: number;
  pan: number;
  audible: boolean;
};
export type AudioClock = ClockValues & {
  start: number;
  end: number;
  phase: number;
  id: string;
};
export interface DesktopApi {
  kind: "electron";
  chooseAudio(): Promise<string[]>;
  sampleLibrary(choose?: boolean): Promise<SampleLibrary>;
  sampleReference(id: string): Promise<SampleReference>;
  chooseCandidateReview():Promise<SampleLibrary|null>;
  candidateReference(filename:string,id:string):Promise<SampleReference>;
  saveSampleDraft(project: Project): Promise<string>;
  decode(paths: string[], copy: boolean, requestId: string): Promise<string>;
  finishImport(id: string, keep: boolean): Promise<void>;
  peaks(asset: Asset): Promise<ArrayBuffer>;
  chunk(assetId: string, index: number): Promise<ArrayBuffer>;
  registerAssets(assets: Asset[]): Promise<void>;
  save(
    project: Project,
    path: string | null,
    copy: boolean,
  ): Promise<{ path: string; project: Project } | null>;
  open(): Promise<{ path: string; project: Project; missing: string[] } | null>;
  autosave(project: Project): Promise<void>;
  closingProject(project: Project): boolean;
  recovery(): Promise<{ project: Project; savedAt: string } | null>;
  analyze(
    asset: Asset,
    start: number,
    end: number,
    tap: number | null,
    clipId: string,
  ): Promise<string>;
  cancel(id: string): Promise<void>;
  exportProject(
    project: Project,
    options: {
      start: number;
      end: number;
      mix: boolean;
      stems: boolean;
      click: boolean;
      maps: boolean;
    },
  ): Promise<string | null>;
  onJob(callback: (event: JobEvent) => void): () => void;
  onCommand(callback: (command: string) => void): () => void;
  pathForFile(file: File): string;
  reveal(path: string): Promise<void>;
  window(action: "minimize" | "maximize" | "close"): void;
}
declare global {
  interface Window {
    joljak?: DesktopApi;
  }
}

export const uid = () => crypto.randomUUID();
export const colors = [
  "#69baa9",
  "#7ea4db",
  "#a994d3",
  "#cfac77",
  "#c887a3",
  "#86af7a",
  "#7cb8cb",
  "#cc967b",
];
export const createProject = (): Project => ({
  format: "joljak-project",
  version: 2,
  id: uid(),
  name: "Untitled project",
  assets: [],
  tracks: [],
  clips: [],
  clocks: [],
  analyses: [],
  masterGain: 1,
  clickGain: DEFAULT_CLICK_GAIN,
  clickGainPolicy: CLICK_GAIN_POLICY,
  sampleRate: 48000,
  notes: "",
  bpm: 120,
  signature: { numerator: 4, denominator: 4 },
  tempos: [],
  signatures: [],
  projectDuration: 1800,
  rulerFormat: "bars",
  timingPolicy: "persistent",
});
export const projectEnd = (p: Project) =>
  Math.max(
    0,
    ...p.clips.map((c) => c.start + c.duration),
  );
export const clipEnd = (c: Clip) => c.start + c.duration;
export const getAsset = (p: Project, clip: Clip) =>
  p.assets.find((a) => a.id === clip.assetId)!;
export const clipSourceToProject = (clip: Clip, sourceTime: number) =>
  clip.start + sourceTime - clip.sourceStart;

/** The receipt retains its full source scope; an edited event exposes only its intersection. */
export function clockSourceScope(p: Project, clock: Clock) {
  const clip = p.clips.find((c) => c.id === clock.clipId);
  const start = Math.max(clock.sourceStart, clip?.sourceStart ?? clock.sourceStart);
  const end = Math.min(clock.sourceEnd, clip ? clip.sourceStart + clip.duration : clock.sourceEnd);
  return end > start ? { start, end } : null;
}
function inheritedClocks(clocks: Clock[], from: Clip, to: Clip): Clock[] {
  return clocks.filter((clock) => clock.clipId === from.id &&
    clock.sourceStart < to.sourceStart + to.duration && clock.sourceEnd > to.sourceStart)
    .map((clock) => ({ ...structuredClone(clock), id: uid(), clipId: to.id,
      projectOrigin: to.start - to.sourceStart }));
}
export function clockGeometry(p: Project, clock: Clock): AudioClock | null {
  const clip = p.clips.find((c) => c.id === clock.clipId);
  const origin = clip ? clip.start - clip.sourceStart : clock.projectOrigin;
  const scope = clockSourceScope(p, clock);
  if (origin === undefined || !scope) return null;
  const start = Math.max(0, origin + scope.start),
    end = origin + scope.end;
  if (end <= start) return null;
  return {
    ...clock.values,
    id: clock.id,
    start,
    end,
    phase: origin + clock.sourceStart + clock.values.offset,
  };
}
export const audibleClocks = (p: Project): AudioClock[] =>
  p.clocks.map((c) => clockGeometry(p, c)).filter((c): c is AudioClock => !!c);
export const clockAt = (p: Project, t: number) =>
  projectClocks(p, Math.max(p.projectDuration, t + 1)).find((c) => t >= c.start && t < c.end);
export function snapTime(
  p: Project,
  t: number,
  mode: Snap,
  origin = 0,
): number {
  return snapToProject(p, t, mode);
}
export function audioClips(p: Project): AudioClip[] {
  const hasSolo = p.tracks.some((t) => t.solo);
  return p.clips.flatMap((c) => {
    const asset = getAsset(p, c),
      track = p.tracks.find((t) => t.id === c.trackId);
    return asset && track
      ? [
          {
            ...c,
            sampleRate: asset.playbackRate ?? asset.sampleRate,
            channels: asset.channels,
            frames: asset.playbackFrames ?? asset.frames,
            gain: track.gain,
            pan: track.pan,
            audible: !track.mute && (!hasSolo || track.solo),
          },
        ]
      : [];
  });
}
export function relatedClips(
  p: Project,
  ids: string[],
  linked: boolean,
): Clip[] {
  const selected = p.clips.filter((c) => ids.includes(c.id));
  const groups = linked
    ? new Set(selected.map((c) => c.groupId).filter(Boolean))
    : new Set();
  return p.clips.filter(
    (c) => ids.includes(c.id) || (c.groupId !== null && groups.has(c.groupId)),
  );
}
export function importAssets(
  p: Project,
  assets: Asset[],
  options: ImportOptions,
): Project {
  if (!assets.length) return p;
  if (!Number.isFinite(options.start) || options.start < 0)
    throw new Error("Choose a valid import position.");
  const target = options.mode === "sequence" && options.targetTrackId
    ? p.tracks.find((track) => track.id === options.targetTrackId) : undefined;
  if (options.mode === "sequence" && options.targetTrackId && !target)
    throw new Error("The import target track was removed. Import again onto an existing or new track.");
  const insertion = options.beforeTrackId ? p.tracks.findIndex((track) => track.id === options.beforeTrackId) : p.tracks.length;
  if (!target && insertion < 0)
    throw new Error("The import insertion track was removed. Choose a new destination.");
  const next = structuredClone(p),
    groupId = options.mode === "stems" && assets.length > 1 ? uid() : null;
  const tracks: Track[] = [];
  let at = options.start;
  for (const [index, asset] of assets.entries()) {
    const track = options.mode === "sequence"
      ? target ?? tracks[0] ?? createAudioTrack(asset.name.replace(/\.[^.]+$/, ""), next.tracks.length)
      : createAudioTrack(asset.name.replace(/\.[^.]+$/, ""), next.tracks.length + index);
    if (!target && !tracks.some((item) => item.id === track.id)) tracks.push(track);
    next.assets.push(asset);
    next.clips.push({
      id: uid(),
      trackId: track.id,
      assetId: asset.id,
      name: asset.name.replace(/\.[^.]+$/, ""),
      start: options.mode === "sequence" ? at : options.start,
      sourceStart: 0,
      duration: asset.duration,
      groupId,
    });
    if (options.mode === "sequence") at += asset.duration;
  }
  next.tracks.splice(Math.max(0, insertion), 0, ...tracks);
  next.projectDuration = Math.max(next.projectDuration, ...next.clips.map(clipEnd));
  return next;
}

export function createAudioTrack(name: string, colorIndex: number): Track {
  return { id: uid(), name, color: colors[colorIndex % colors.length], gain: 1, pan: 0,
    mute: false, solo: false, timeBase: "linear" };
}

export function addAudioTracks(p: Project, count: number, name: string, beforeTrackId: string | null): Project {
  if (!Number.isInteger(count) || count < 1 || count > 32) throw new Error("Add between 1 and 32 audio tracks.");
  const index = beforeTrackId ? p.tracks.findIndex((track) => track.id === beforeTrackId) : p.tracks.length;
  if (index < 0) throw new Error("The insertion track was removed. Open Add Audio Track again.");
  const existing = new Set(p.tracks.map((track) => track.name));
  let number = 1;
  const added = Array.from({ length: count }, (_, i) => {
    while (existing.has(`Audio ${number}`)) number++;
    const label = name.trim() ? name.trim() + (count > 1 ? ` ${String(i + 1).padStart(2, "0")}` : "") : `Audio ${number++}`;
    existing.add(label);
    return createAudioTrack(label, p.tracks.length + i);
  });
  const tracks = [...p.tracks]; tracks.splice(index, 0, ...added);
  return { ...p, tracks };
}

export function reorderTracks(p: Project, ids: string[], beforeTrackId: string | null): Project {
  const selected = new Set(ids), moving = p.tracks.filter((track) => selected.has(track.id));
  if (!moving.length || (beforeTrackId && selected.has(beforeTrackId))) return p;
  const tracks = p.tracks.filter((track) => !selected.has(track.id));
  const index = beforeTrackId ? tracks.findIndex((track) => track.id === beforeTrackId) : tracks.length;
  if (index < 0) return p;
  tracks.splice(index, 0, ...moving);
  return tracks.every((track, i) => track.id === p.tracks[i].id) ? p : { ...p, tracks };
}

export function removeTracks(p: Project, ids: string[]): Project {
  const selected = new Set(ids);
  if (!p.tracks.some((track) => selected.has(track.id))) return p;
  // Track removal is scoped to the selected tracks even when their events are
  // linked to stems elsewhere. Keep source media, raw predictions and map events.
  const clips = p.clips.filter((clip) => selected.has(clip.trackId)).map((clip) => clip.id);
  return { ...removeClips(p, clips, false), tracks: p.tracks.filter((track) => !selected.has(track.id)) };
}

export function duplicateTracks(p: Project, ids: string[]): Project {
  const selected = new Set(ids), trackIds = new Map<string, string>(), clipIds = new Map<string, string>(), groups = new Map<string, string>();
  const names = new Set(p.tracks.map((track) => track.name));
  const tracks = p.tracks.flatMap((track) => {
    if (!selected.has(track.id)) return [track];
    let name = `${track.name} (D)`, number = 2;
    while (names.has(name)) name = `${track.name} (D${number++})`;
    names.add(name);
    const copy = { ...track, id: uid(), name }; trackIds.set(track.id, copy.id);
    return [track, copy];
  });
  if (!trackIds.size) return p;
  const copies = p.clips.filter((clip) => trackIds.has(clip.trackId)).map((clip) => {
    const id = uid(); clipIds.set(clip.id, id);
    if (clip.groupId && !groups.has(clip.groupId)) groups.set(clip.groupId, uid());
    return { ...clip, id, trackId: trackIds.get(clip.trackId)!, groupId: clip.groupId ? groups.get(clip.groupId)! : null };
  });
  return { ...p, tracks, clips: [...p.clips, ...copies], clocks: [...p.clocks,
    ...copies.flatMap((copy) => inheritedClocks(p.clocks, p.clips.find((clip) => clipIds.get(clip.id) === copy.id)!, copy))] };
}
/** Shared, side-effect-free geometry for both pointer previews and committed edits. */
export function movePreview(p: Project, ids: string[], delta: number, linked: boolean, targetTrack?: string): Clip[] {
  const clips = relatedClips(p, ids, linked);
  if (!clips.length) return [];
  delta = Math.max(delta, -Math.min(...clips.map((c) => c.start)));
  const primary = p.clips.find((c) => c.id === ids[0]) ?? clips[0];
  const indexes = clips.map((c) => p.tracks.findIndex((t) => t.id === c.trackId));
  const targetIndex = p.tracks.findIndex((t) => t.id === targetTrack);
  const trackDelta = Math.max(-Math.min(...indexes), Math.min(
    targetIndex < 0 ? 0 : targetIndex - p.tracks.findIndex((t) => t.id === primary.trackId),
    p.tracks.length - 1 - Math.max(...indexes)));
  return clips.map((c, i) => ({ ...c, start: c.start + delta, trackId: p.tracks[indexes[i] + trackDelta].id }));
}
export function trimPreview(p: Project, ids: string[], edge: "start" | "end", delta: number, linked: boolean): Clip[] {
  const clips = relatedClips(p, ids, linked);
  if (!clips.length) return [];
  if (edge === "start") {
    delta = Math.max(delta, ...clips.map((c) => Math.max(-c.start, -c.sourceStart)));
    delta = Math.min(delta, ...clips.map((c) => c.duration - Math.min(.001, c.duration)));
  } else {
    delta = Math.max(delta, ...clips.map((c) => Math.min(.001, c.duration) - c.duration));
    delta = Math.min(delta, ...clips.map((c) => getAsset(p, c).duration - c.sourceStart - c.duration));
  }
  return clips.map((c) => edge === "start"
    ? { ...c, start: c.start + delta, sourceStart: c.sourceStart + delta, duration: c.duration - delta }
    : { ...c, duration: c.duration + delta });
}
export function moveClips(p: Project, ids: string[], delta: number, linked: boolean, targetTrack?: string, copy = false): Project {
  const moved = movePreview(p, ids, delta, linked, targetTrack);
  if (!moved.length || (!copy && moved.every((c) => {
    const before = p.clips.find((x) => x.id === c.id)!;
    return c.start === before.start && c.trackId === before.trackId;
  }))) return p;
  const groups = new Map<string, string>();
  if (copy) {
    const copies = moved.map((c) => {
      if (c.groupId && !groups.has(c.groupId)) groups.set(c.groupId, uid());
      return { ...c, id: uid(), groupId: c.groupId ? groups.get(c.groupId)! : null };
    });
    return { ...p, clips: [...p.clips, ...copies], clocks: [...p.clocks,
      ...copies.flatMap((c, i) => inheritedClocks(p.clocks, moved[i], c))] };
  }
  const byId = new Map(moved.map((c) => [c.id, c]));
  return { ...p, clips: p.clips.map((c) => byId.get(c.id) ?? c), clocks: p.clocks.map((clock) => {
    const clip = byId.get(clock.clipId);
    return clip ? { ...clock, projectOrigin: clip.start - clip.sourceStart } : clock;
  }) };
}
export function trimClips(p: Project, ids: string[], edge: "start" | "end", delta: number, linked: boolean): Project {
  const trimmed = trimPreview(p, ids, edge, delta, linked);
  if (!trimmed.length || trimmed.every((c) => {
    const before = p.clips.find((x) => x.id === c.id)!;
    return before.start === c.start && before.sourceStart === c.sourceStart && before.duration === c.duration;
  })) return p;
  const byId = new Map(trimmed.map((c) => [c.id, c]));
  return { ...p, clips: p.clips.map((c) => byId.get(c.id) ?? c) };
}
export function splitClips(p: Project, ids: string[], time: number, linked: boolean): Project {
  const splitting = relatedClips(p, ids, linked).filter((c) => time > c.start + .001 && time < clipEnd(c) - .001);
  if (!splitting.length) return p;
  const next = { ...p, clips: [...p.clips], clocks: [...p.clocks] }, groups = new Map<string, string>();
  for (const c of splitting) {
    const split = time - c.start;
    const right = { ...c, id: uid(), start: time, sourceStart: c.sourceStart + split, duration: c.duration - split };
    if (c.groupId) {
      if (!groups.has(c.groupId)) groups.set(c.groupId, uid());
      right.groupId = groups.get(c.groupId)!;
    }
    next.clips[next.clips.findIndex((x) => x.id === c.id)] = { ...c, duration: split };
    next.clips.push(right);
    next.clocks.push(...inheritedClocks(p.clocks, c, right));
  }
  return next;
}
export function removeClips(p: Project, ids: string[], linked: boolean): Project {
  const deleting = new Set(relatedClips(p, ids, linked).map((c) => c.id));
  if (!deleting.size) return p;
  return { ...p, clips: p.clips.filter((c) => !deleting.has(c.id)), clocks: p.clocks.map((clock) => {
    const clip = p.clips.find((c) => c.id === clock.clipId);
    return clip && deleting.has(clip.id) ? { ...clock, projectOrigin: clip.start - clip.sourceStart } : clock;
  }) };
}
/** Playback and drawing both use the last event as the front event on a track. */
export function orderClips(p: Project, ids: string[], front: boolean, linked: boolean): Project {
  const selected = new Set(relatedClips(p, ids, linked).map((c) => c.id));
  const chosen = p.clips.filter((c) => selected.has(c.id)), other = p.clips.filter((c) => !selected.has(c.id));
  const clips = front ? [...other, ...chosen] : [...chosen, ...other];
  return clips.every((c, i) => c.id === p.clips[i].id) ? p : { ...p, clips };
}
export function applyAnalysis(p: Project, analysis: Analysis): Project {
  const result = analysis.result;
  if (!result.period_seconds || !result.time_signature)
    return { ...p, analyses: [...p.analyses, analysis] };
  const values = {
    bpm: result.quarter_bpm,
    numerator: result.time_signature.numerator,
    denominator: result.time_signature.denominator,
    offset: result.offset_seconds,
  };
  // Saved analysis scopes are evidence/drafts, independent of the project tempo map.
  // Keep distinct source scopes and original predictions even when songs overlap.
  const reference = p.clips.find((c) => c.id === analysis.clipId);
  if (!reference) return p;
  const clocks = p.clocks.filter((clock) => clock.analysisId !== analysis.id);
  clocks.push({
    id: uid(),
    clipId: analysis.clipId,
    name: "Fixed clock",
    sourceStart: analysis.sourceStart,
    sourceEnd: analysis.sourceEnd,
    projectOrigin: reference.start - reference.sourceStart,
    values,
    original: { ...values },
    analysisId: analysis.id,
  });
  return {
    ...p,
    analyses: p.analyses.some((a) => a.id === analysis.id)
      ? p.analyses
      : [...p.analyses, analysis],
    clocks,
  };
}
export function rangeClips(
  p: Project,
  range: TimeRange,
  linked: boolean,
): Clip[] {
  const hits = p.clips.filter(
    (c) =>
      range.trackIds.includes(c.trackId) &&
      c.start < range.end &&
      clipEnd(c) > range.start,
  );
  return relatedClips(
    p,
    hits.map((c) => c.id),
    linked,
  ).flatMap((c) => {
    const start = Math.max(c.start, range.start),
      end = Math.min(clipEnd(c), range.end);
    return end > start
      ? [
          {
            ...c,
            start,
            sourceStart: c.sourceStart + start - c.start,
            duration: end - start,
          },
        ]
      : [];
  });
}
export function removeRange(
  p: Project,
  range: TimeRange,
  linked: boolean,
): Project {
  const tracks = new Set(rangeClips(p, range, linked).map((c) => c.trackId));
  const first = splitClips(
    p,
    p.clips
      .filter(
        (c) =>
          tracks.has(c.trackId) &&
          c.start < range.end &&
          clipEnd(c) > range.start,
      )
      .map((c) => c.id),
    range.start,
    false,
  );
  const second = splitClips(
    first,
    first.clips
      .filter(
        (c) =>
          tracks.has(c.trackId) &&
          c.start < range.end &&
          clipEnd(c) > range.start,
      )
      .map((c) => c.id),
    range.end,
    false,
  );
  return removeClips(
    second,
    second.clips
      .filter(
        (c) =>
          tracks.has(c.trackId) &&
          c.start >= range.start - 1e-9 &&
          clipEnd(c) <= range.end + 1e-9,
      )
      .map((c) => c.id),
    false,
  );
}

export function copyAudio(p: Project, ids: string[], range: TimeRange | null, linked: boolean): AudioClipboard | null {
  const usingRange = range && range.end > range.start && range.trackIds.length > 0;
  const clips = usingRange ? rangeClips(p, range, linked) : relatedClips(p, ids, linked);
  if (!usingRange && !clips.length) return null;
  const origin = usingRange ? range.start : Math.min(...clips.map((c) => c.start));
  const end = usingRange ? range.end : Math.max(...clips.map(clipEnd));
  const selectedTracks = new Set([...(usingRange ? range.trackIds : []), ...clips.map((c) => c.trackId)]);
  const rows = p.tracks.flatMap((t, i) => selectedTracks.has(t.id) ? [i] : []);
  if (!rows.length) return null;
  // Keep empty rows between selected tracks and silence at either range boundary.
  const tracks = p.tracks.slice(Math.min(...rows), Math.max(...rows) + 1);
  const clocks = p.clocks.filter((clock) => clips.some((c) => c.id === clock.clipId &&
    clock.sourceStart < c.sourceStart + c.duration && clock.sourceEnd > c.sourceStart));
  return structuredClone({ kind: usingRange ? "range" : "events", origin, duration: end - origin,
    clips, clocks, tracks, assets: p.assets.filter((a) => clips.some((c) => c.assetId === a.id)),
    analyses: p.analyses.filter((a) => clocks.some((clock) => clock.analysisId === a.id)) });
}

export function pasteAudio(p: Project, data: AudioClipboard, at: number, targetTrack?: string | null) {
  const tracks = [...p.tracks], mapping = new Map<string, string>();
  let firstRow = tracks.findIndex((t) => t.id === (targetTrack ?? data.tracks[0]?.id));
  if (firstRow < 0) firstRow = tracks.length;
  for (let i = 0; i < data.tracks.length; i++) {
    if (!tracks[firstRow + i]) tracks.push({ ...data.tracks[i], id: uid() });
    mapping.set(data.tracks[i].id, tracks[firstRow + i].id);
  }
  const groups = new Map<string, string>();
  const start = Math.max(0, at);
  const copies = data.clips.map((c) => {
    if (c.groupId && !groups.has(c.groupId)) groups.set(c.groupId, uid());
    return { ...c, id: uid(), start: start + c.start - data.origin, trackId: mapping.get(c.trackId)!,
      groupId: c.groupId ? groups.get(c.groupId)! : null };
  });
  const next = copies.length || tracks.length !== p.tracks.length ? { ...p, tracks,
    clips: [...p.clips, ...copies], clocks: [...p.clocks, ...copies.flatMap((c, i) => inheritedClocks(data.clocks, data.clips[i], c))],
    assets: [...p.assets, ...data.assets.filter((a) => !p.assets.some((x) => x.id === a.id))],
    analyses: [...p.analyses, ...data.analyses.filter((a) => !p.analyses.some((x) => x.id === a.id))] } : p;
  return { project: next, ids: copies.map((c) => c.id), range: data.kind === "range"
    ? { start, end: start + data.duration, trackIds: data.tracks.map((t) => mapping.get(t.id)!) } : null };
}

export function rangePreview(p: Project, range: TimeRange, delta: number, targetTrack?: string, linked = true) {
  const data = copyAudio(p, [], range, linked);
  if (!data) return { range, clips: [] as Clip[] };
  const firstRow = p.tracks.findIndex((t) => t.id === data.tracks[0].id);
  const clickedRow = p.tracks.findIndex((t) => t.id === range.trackIds[0]);
  const targetRow = p.tracks.findIndex((t) => t.id === targetTrack);
  const trackDelta = Math.max(-firstRow, Math.min(targetRow < 0 ? 0 : targetRow - clickedRow,
    p.tracks.length - firstRow - data.tracks.length));
  delta = Math.max(-range.start, delta);
  const trackIds = data.tracks.map((t) => p.tracks[p.tracks.findIndex((row) => row.id === t.id) + trackDelta].id);
  return { range: { start: range.start + delta, end: range.end + delta, trackIds },
    clips: data.clips.map((c) => ({ ...c, start: c.start + delta,
      trackId: p.tracks[p.tracks.findIndex((t) => t.id === c.trackId) + trackDelta].id })) };
}

export function moveRange(p: Project, range: TimeRange, delta: number, linked: boolean, targetTrack?: string, copy = false) {
  const data = copyAudio(p, [], range, linked);
  if (!data) return { project: p, range, ids: [] as string[] };
  const preview = rangePreview(p, range, delta, targetTrack, linked);
  if (!copy && preview.range.start === range.start && preview.range.trackIds.join() === data.tracks.map((t) => t.id).join())
    return { project: p, range: preview.range, ids: [] as string[] };
  return pasteAudio(copy ? p : removeRange(p, range, linked), data, preview.range.start, preview.range.trackIds[0]);
}
export function formatTime(t: number): string {
  const ms = Math.floor(Math.max(0, t) * 1000);
  return `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}.${(ms % 1000).toString().padStart(3, "0")}`;
}
export function musicalPosition(p: Project, t: number): string {
  return musicalTime(p, t);
}
