import { memo, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type RefObject } from "react";
import {
  Activity,
  GripVertical,
  Volume2,
  AudioLines,
  MoreHorizontal,
  Plus,
  Clock3,
  Music2,
} from "lucide-react";
import {
  clipEnd,
  formatTime,
  getAsset,
  movePreview,
  trimPreview,
  rangePreview,
  relatedClips,
  projectEnd,
  snapTime,
  type Asset,
  type Clip,
  type ImportDestination,
  type MapSelection,
  type Project,
  type Snap,
  type TimeRange,
  type Tool,
  type Track,
} from "./model";
import { gridLines, musicalTime, positionAtQuarter, quarterAtTime, signatureSections, snapToProject, temposInOrder, timeAtBar, timeAtQuarter } from "./music";

const ROW = 92;
const RULER = 36;
const TEMPO_ROW = 72;
const SIGNATURE_ROW = 40;
const HEADER = RULER + TEMPO_ROW + SIGNATURE_ROW;
export type TimelineViewportControl = {
  zoom: (factor: number, pointerPixel?: number) => void;
  setScale: (scale: number, left?: number) => void;
};
type Viewport = { x: number; y: number; width: number; height: number; scale: number; revision: number };
type Props = {
  project: Project;
  selection: string[];
  activeTrack: string | null;
  selectedTracks: string[];
  range: TimeRange | null;
  tool: Tool;
  snap: Snap;
  linked: boolean;
  position: number;
  viewportControl: RefObject<TimelineViewportControl | null>;
  follow: boolean;
  loop: { start: number; end: number; enabled: boolean };
  peaks: Map<string, Float32Array>;
  selectedMap: MapSelection | null;
  onSelect: (ids: string[], track: string) => void;
  onTrackSelect: (id: string, modifiers?: { ctrl: boolean; shift: boolean }, preserve?: boolean) => string[];
  onTrackMenu: (id: string | null, x: number, y: number) => void;
  onTrackReorder: (ids: string[], beforeTrackId: string | null) => void;
  onRange: (range: TimeRange | null) => void;
  onSeek: (time: number) => void;
  onLoop: (start: number, end: number) => void;
  onMove: (
    ids: string[],
    delta: number,
    targetTrack: string | undefined,
    copy: boolean,
  ) => void;
  onTrim: (ids: string[], edge: "start" | "end", delta: number) => void;
  onSplit: (ids: string[], time: number) => void;
  onDelete: (ids: string[]) => void;
  onFront: (ids: string[]) => void;
  onBack: (ids: string[]) => void;
  onAddTrack: () => void;
  onTrack: (id: string, fields: Partial<Track>) => void;
  onAnalyze: (clip: Clip) => void;
  onEdit: (clip: Clip) => void;
  onRangeMove: (range: TimeRange, delta: number, targetTrack: string | undefined, copy: boolean) => void;
  onMapSelect: (selection: MapSelection) => void;
  onMapAdd: (kind: "tempo" | "signature", time: number) => void;
  onMapMove: (selection: MapSelection, time: number, bpm?: number) => void;
  onMapDelete: (selection: MapSelection) => void;
  onTimeBase: (id: string) => void;
  onImport: (paths?: string[], destination?: ImportDestination) => void;
};
type Drag = {
  mode:
    | "move"
    | "start"
    | "end"
    | "range"
    | "range-move"
    | "range-start"
    | "range-end"
    | "marquee"
    | "locator-left"
    | "locator-right"
    | "locator-body"
    | "locator-create"
    | "tempo"
    | "signature"
    | "cursor"
    | "track";
  x: number;
  y: number;
  time: number;
  id?: string;
  ids?: string[];
  trackId?: string;
  copy?: boolean;
  ctrl?: boolean;
  axis?: "horizontal" | "vertical";
  additive?: boolean;
  initialSelection?: string[];
  contentY?: number;
  originalRange?: TimeRange;
  original?: { start: number; end: number };
  moved?: boolean;
  delta?: number;
  targetTrack?: string;
  currentX?: number;
  currentY?: number;
  mapId?: string;
  mapTime?: number;
  mapFixed?: boolean;
  originalBpm?: number;
  bpm?: number;
  bpmPerPixel?: number;
  horizontalMoved?: boolean;
  verticalMoved?: boolean;
  capture?: { element: HTMLElement; pointerId: number };
  cursorOffset?: number;
  insertionIndex?: number;
};
type FileDrop = { destination: ImportDestination; row: number; count: number };

export const Waveform = memo(function Waveform({
  asset,
  clip,
  scale,
  left,
  viewport,
  samples,
  color,
  height = 52,
}: {
  asset: Asset;
  clip: Clip;
  scale: number;
  left: number;
  viewport: number;
  samples?: Float32Array;
  color: string;
  height?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const visibleFrom = Math.max(0, left - clip.start * scale - 4);
  const width = Math.max(
    0,
    Math.min(clip.duration * scale - visibleFrom, viewport + 8),
  );
  useLayoutEffect(() => {
    const node = canvas.current;
    if (!node || !samples || width <= 0) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    node.width = Math.ceil(width * dpr);
    node.height = Math.ceil(height * dpr);
    const ctx = node.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.83;
    for (let x = 0; x < width; x++) {
      const sourceA = clip.sourceStart + (visibleFrom + x) / scale;
      const sourceB = clip.sourceStart + (visibleFrom + x + 1) / scale;
      const a = Math.max(
        0,
        Math.floor((sourceA * asset.sampleRate) / asset.peakBinFrames),
      );
      const b = Math.min(
        asset.peakBins,
        Math.max(
          a + 1,
          Math.ceil((sourceB * asset.sampleRate) / asset.peakBinFrames),
        ),
      );
      let minimum = 0,
        maximum = 0;
      for (let i = a; i < b; i++) {
        minimum = Math.min(minimum, samples[i * 2]);
        maximum = Math.max(maximum, samples[i * 2 + 1]);
      }
      ctx.fillRect(
        x,
        height / 2 - maximum * height * .44,
        1,
        Math.max(1, (maximum - minimum) * height * .44),
      );
    }
  }, [
    samples,
    clip.sourceStart,
    clip.duration,
    scale,
    visibleFrom,
    width,
    asset.id,
    color,
    height,
  ]);
  return (
    <canvas
      ref={canvas}
      className="clip-waveform"
      style={{ left: visibleFrom, width, height }}
    />
  );
});

function TrackName({
  name,
  onChange,
}: {
  name: string;
  onChange: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false),
    [text, setText] = useState(name);
  const cancelled = useRef(false);
  return editing ? (
    <input
      autoFocus
      value={text}
      aria-label="Track name"
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (!cancelled.current && text.trim() && text !== name)
          onChange(text.trim());
        setEditing(false);
      }}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          cancelled.current = true;
          setEditing(false);
        }
      }}
    />
  ) : (
    <span
      className="track-name"
      title="Double-click to rename"
      onDoubleClick={(e) => {
        e.stopPropagation();
        cancelled.current = false;
        setText(name);
        setEditing(true);
      }}
    >
      {name}
    </span>
  );
}

export default function Timeline(props: Props) {
  const { project, selection, tool, snap, linked, position, peaks } =
    props;
  const scroller = useRef<HTMLDivElement>(null),
    headerScroller = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState<Viewport>({ x: 0, y: 0, width: 900, height: 0, scale: 12, revision: 0 });
  const viewport = useRef(scroll), appliedRevision = useRef(0);
  const zoomHoldUntil = useRef(0);
  const viewportControls = useRef<TimelineViewportControl | null>(null);
  const scale = scroll.scale;
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [fileDrop, setFileDrop] = useState<FileDrop | null>(null);
  const seekFrame = useRef<number | null>(null), pendingSeek = useRef<number | null>(null);
  const seekCallback = useRef(props.onSeek);
  seekCallback.current = props.onSeek;
  const [menu, setMenu] = useState<{ x: number; y: number; clip: Clip; time: number } | null>(
    null,
  );
  const totalEnd = Math.max(project.projectDuration, projectEnd(project));
  const totalWidth = Math.max(scroll.width, totalEnd * scale);
  const contentHeight = Math.max(scroll.height, HEADER + (project.tracks.length + 1) * ROW, project.clips.length ? 0 : 560);
  const effectiveSelection = new Set(
    relatedClips(project, selection, linked).map((c) => c.id),
  );
  const startTime = scroll.x / scale,
    endTime = (scroll.x + scroll.width) / scale;
  const requestViewport = (next: Viewport) => {
    viewport.current = next;
    setScroll(next);
  };
  const syncViewport = () => {
    const node = scroller.current, current = viewport.current;
    // A native scroll from the old DOM must not overwrite a pending zoom.
    if (!node || current.revision !== appliedRevision.current) return;
    if (current.x === node.scrollLeft && current.y === node.scrollTop &&
      current.width === node.clientWidth && current.height === node.clientHeight) return;
    const next = { ...current, x: node.scrollLeft, y: node.scrollTop,
      width: node.clientWidth, height: node.clientHeight, revision: current.revision + 1 };
    appliedRevision.current = next.revision;
    requestViewport(next);
  };
  const changeScale = (value: number, left: number) => {
    const node = scroller.current;
    if (!node) return;
    const current = viewport.current, next = Math.max(.2, Math.min(1200, value));
    const maximum = Math.max(0, totalEnd * next - node.clientWidth);
    requestViewport({ ...current, scale: next, x: Math.max(0, Math.min(maximum, left)),
      y: current.revision === appliedRevision.current ? node.scrollTop : current.y,
      width: node.clientWidth, height: node.clientHeight, revision: current.revision + 1 });
    zoomHoldUntil.current = performance.now() + 250;
  };
  viewportControls.current = {
    zoom: (factor, pointerPixel) => {
      const node = scroller.current;
      if (!node) return;
      const current = viewport.current;
      const next = Math.max(.2, Math.min(1200, current.scale * factor));
      if (next === current.scale) return;
      const left = current.revision === appliedRevision.current ? node.scrollLeft : current.x;
      const pixel = Math.max(0, Math.min(node.clientWidth, pointerPixel ?? node.clientWidth / 2));
      const time = (left + pixel) / current.scale;
      changeScale(next, time * next - pixel);
    },
    setScale: (value, left) => {
      const node = scroller.current, current = viewport.current;
      const currentLeft = current.revision === appliedRevision.current ? node?.scrollLeft ?? 0 : current.x;
      changeScale(value, left ?? currentLeft);
    },
  };
  useImperativeHandle(props.viewportControl, (): TimelineViewportControl => ({
    zoom: (factor, pixel) => viewportControls.current?.zoom(factor, pixel),
    setScale: (value, left) => viewportControls.current?.setScale(value, left),
  }), []);
  useLayoutEffect(() => {
    const node = scroller.current;
    if (!node || scroll.revision !== viewport.current.revision || scroll.revision === appliedRevision.current) return;
    // Apply scale, visible range and native scroll before the same paint.
    node.scrollLeft = scroll.x;
    node.scrollTop = scroll.y;
    appliedRevision.current = scroll.revision;
    syncViewport();
  }, [scroll]);
  const setDragging = (value: Drag | null) => {
    dragRef.current = value;
    setDrag(value);
  };
  const timeAt = (clientX: number) =>
    Math.max(
      0,
      (clientX -
        scroller.current!.getBoundingClientRect().left +
        scroller.current!.scrollLeft) /
        scale,
    );
  const flushSeek = (time?: number) => {
    if (seekFrame.current !== null) cancelAnimationFrame(seekFrame.current);
    seekFrame.current = null;
    const target = time ?? pendingSeek.current;
    pendingSeek.current = null;
    if (target !== null) seekCallback.current(target);
  };
  const scheduleSeek = (time: number) => {
    pendingSeek.current = time;
    if (seekFrame.current === null) seekFrame.current = requestAnimationFrame(() => flushSeek());
  };
  const beginCursor = (event: React.PointerEvent, fromHead = false) => {
    if (event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const pointerTime = timeAt(event.clientX);
    const time = fromHead ? position : snapToProject(project, pointerTime, event.ctrlKey ? "off" : snap);
    setDragging({ mode: "cursor", x: event.clientX, y: event.clientY, time, delta: time, cursorOffset: fromHead ? position - pointerTime : 0 });
    if (!fromHead) flushSeek(time);
  };
  useEffect(() => () => {
    if (seekFrame.current !== null) cancelAnimationFrame(seekFrame.current);
  }, []);
  useLayoutEffect(() => {
    if (seekFrame.current !== null) cancelAnimationFrame(seekFrame.current);
    seekFrame.current = null; pendingSeek.current = null;
    setDragging(null);
    setFileDrop(null); setMenu(null);
    requestViewport({ ...viewport.current, x: 0, y: 0, revision: viewport.current.revision + 1 });
  }, [project.id]);
  const trackAt = (clientY: number) =>
    project.tracks[
      Math.floor(
        (clientY -
          scroller.current!.getBoundingClientRect().top +
          scroller.current!.scrollTop -
          HEADER) /
          ROW,
      )
    ];
  const boundedTrackAt = (clientY: number) => {
    const node = scroller.current!;
    const row = Math.floor((clientY - node.getBoundingClientRect().top + node.scrollTop - HEADER) / ROW);
    return project.tracks[Math.max(0, Math.min(project.tracks.length - 1, row))];
  };
  const insertionAt = (clientY: number) => {
    const node = scroller.current!;
    return Math.max(0, Math.min(project.tracks.length, Math.round((clientY - node.getBoundingClientRect().top + node.scrollTop - HEADER) / ROW)));
  };
  const beginTrack = (event: React.PointerEvent, id: string) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("input,select")) return;
    if (target.closest("button")) {
      props.onTrackSelect(id, { ctrl: false, shift: false }, true);
      return;
    }
    event.preventDefault(); setMenu(null);
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      props.onTrackSelect(id, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey }); return;
    }
    const ids = props.onTrackSelect(id, { ctrl: false, shift: false }, true);
    // Capture only after a drag begins, so the name receives its double-click.
    setDragging({ mode: "track", x: event.clientX, y: event.clientY, time: 0, trackId: id, ids,
      capture: { element: event.currentTarget, pointerId: event.pointerId } });
  };
  const fileDestination = (event: React.DragEvent, inTrackList: boolean): FileDrop | null => {
    const node = scroller.current!, bounds = node.getBoundingClientRect();
    const count = [...event.dataTransfer.items].filter((item) => item.kind === "file").length || 1;
    if (inTrackList) {
      const index = insertionAt(event.clientY);
      return { row: index, count, destination: { start: position, targetTrackId: null, beforeTrackId: project.tracks[index]?.id ?? null, source: "track-list" } };
    }
    const row = Math.floor((event.clientY - bounds.top + node.scrollTop - HEADER) / ROW);
    if (row < 0) return null;
    const index = Math.min(row, project.tracks.length), target = project.tracks[index];
    return { row: index, count, destination: {
      start: snapToProject(project, timeAt(event.clientX), event.ctrlKey ? "off" : snap),
      targetTrackId: target?.id ?? null,
      beforeTrackId: target ? project.tracks[index + 1]?.id ?? null : null,
      source: "timeline",
    } };
  };
  const filesOver = (event: React.DragEvent, inTrackList: boolean) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault(); event.stopPropagation();
    const node = scroller.current!, bounds = node.getBoundingClientRect();
    if (event.clientY < bounds.top + RULER + 20) node.scrollTop = Math.max(0, node.scrollTop - 14);
    else if (event.clientY > bounds.bottom - 25) node.scrollTop += 14;
    if (!inTrackList) {
      if (event.clientX < bounds.left + 25) node.scrollLeft = Math.max(0, node.scrollLeft - 14);
      else if (event.clientX > bounds.right - 25) node.scrollLeft += 14;
    }
    const next = fileDestination(event, inTrackList);
    event.dataTransfer.dropEffect = next ? "copy" : "none";
    setFileDrop(next);
  };
  const filesLeave = (event: React.DragEvent) => {
    const next = event.relatedTarget as Node | null;
    if (next && event.currentTarget.contains(next)) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.clientX >= bounds.left && event.clientX < bounds.right && event.clientY >= bounds.top && event.clientY < bounds.bottom) return;
    setFileDrop(null);
  };
  const filesDrop = (event: React.DragEvent, inTrackList: boolean) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault(); event.stopPropagation();
    const placement = fileDestination(event, inTrackList);
    setFileDrop(null);
    if (!placement) return;
    const paths = [...event.dataTransfer.files].map((file) => window.joljak?.pathForFile(file)).filter((path): path is string => !!path);
    if (paths.length) props.onImport(paths, placement.destination);
  };
  useEffect(() => {
    const clear = () => setFileDrop(null);
    window.addEventListener("dragend", clear); window.addEventListener("drop", clear);
    return () => { window.removeEventListener("dragend", clear); window.removeEventListener("drop", clear); };
  }, []);

  useEffect(() => {
    const node = scroller.current!;
    const observer = new ResizeObserver(syncViewport);
    observer.observe(node);
    syncViewport();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!props.follow || !scroller.current || dragRef.current || fileDrop ||
      viewport.current.revision !== appliedRevision.current || performance.now() < zoomHoldUntil.current) return;
    const x = position * scale;
    const node = scroller.current;
    if (x < node.scrollLeft || x > node.scrollLeft + node.clientWidth - 65)
      node.scrollLeft = Math.max(0, x - node.clientWidth * 0.22);
  }, [position, scale, props.follow, fileDrop]);

  useEffect(() => {
    const node = scroller.current!;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        event.preventDefault();
        if (!event.deltaY) return;
        const amount = event.deltaMode === 0 ? Math.min(1, Math.abs(event.deltaY) / 100) : 1;
        viewportControls.current?.zoom(Math.pow(1.15, -Math.sign(event.deltaY) * amount),
          event.clientX - node.getBoundingClientRect().left);
      } else if (event.shiftKey) {
        event.preventDefault();
        node.scrollLeft += event.deltaY + event.deltaX;
      }
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, []);

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const state = dragRef.current;
      if (!state || !scroller.current) return;
      const bounds = scroller.current.getBoundingClientRect();
      if (state.mode === "track") {
        const moved = state.moved || Math.hypot(event.clientX - state.x, event.clientY - state.y) > 4;
        if (moved && !state.moved && state.capture?.element.isConnected)
          state.capture.element.setPointerCapture(state.capture.pointerId);
        if (event.clientY < bounds.top + RULER + 20) scroller.current.scrollTop = Math.max(0, scroller.current.scrollTop - 14);
        else if (event.clientY > bounds.bottom - 25) scroller.current.scrollTop += 14;
        setDragging({ ...state, moved, insertionIndex: insertionAt(event.clientY), currentY: event.clientY });
        return;
      }
      const mapGesture = state.mode === "tempo" || state.mode === "signature";
      if (["move", "marquee", "range", "range-move"].includes(state.mode)) {
        if (event.clientY < bounds.top + HEADER + 12) scroller.current.scrollTop = Math.max(0, scroller.current.scrollTop - 10);
        else if (event.clientY > bounds.bottom - 20) scroller.current.scrollTop += 10;
      }
      const edgeScroll = !mapGesture || (!state.mapFixed && (state.horizontalMoved || Math.abs(event.clientX - state.x) > 4));
      if (edgeScroll && event.clientX < bounds.left + 25)
        scroller.current.scrollLeft = Math.max(
          0,
          scroller.current.scrollLeft - 12,
        );
      if (edgeScroll && event.clientX > bounds.right - 25) scroller.current.scrollLeft += 12;
      const currentTime = timeAt(event.clientX);
      const distance = Math.hypot(
        event.clientX - state.x,
        event.clientY - state.y,
      );
      const next = {
        ...state,
        moved: state.moved || distance > 4,
        currentX: event.clientX,
        currentY: event.clientY,
      };
      const mode = event.ctrlKey ? "off" : snap;
      if (state.mode === "cursor") {
        next.delta = snapToProject(project, currentTime + (state.cursorOffset ?? 0), mode);
        scheduleSeek(next.delta);
      } else if (state.mode === "move") {
        const clip = project.clips.find((c) => c.id === state.id);
        if (!clip) { setDragging(null); return; }
        let delta =
          snapTime(
            project,
            clip.start + currentTime - state.time,
            snap,
            clip.start,
          ) - clip.start;
        let target = boundedTrackAt(event.clientY)?.id;
        next.axis = event.ctrlKey && next.moved ? state.axis ?? (Math.abs(event.clientX - state.x) >= Math.abs(event.clientY - state.y) ? "horizontal" : "vertical") : undefined;
        if (next.axis === "horizontal") target = clip.trackId;
        if (next.axis === "vertical") delta = 0;
        next.copy = event.altKey;
        next.delta = delta;
        next.targetTrack = target;
      } else if (state.mode === "start" || state.mode === "end") {
        const clip = project.clips.find((c) => c.id === state.id);
        if (!clip) { setDragging(null); return; }
        const original = state.mode === "start" ? clip.start : clipEnd(clip);
        next.delta =
          snapTime(
            project,
            original + currentTime - state.time,
            mode,
            original,
          ) - original;
      } else if (state.mode === "range-move") {
        const original = state.originalRange!;
        next.delta = snapToProject(project, original.start + currentTime - state.time, mode) - original.start;
        const clickedRow = project.tracks.findIndex((t) => t.id === state.trackId);
        const row = project.tracks.findIndex((t) => t.id === boundedTrackAt(event.clientY)?.id);
        const firstRow = project.tracks.findIndex((t) => t.id === original.trackIds[0]);
        next.targetTrack = project.tracks[Math.max(0, Math.min(project.tracks.length - 1, firstRow + row - clickedRow))]?.id;
        next.copy = event.altKey;
      } else if (state.mode === "range-start" || state.mode === "range-end") {
        const original = state.originalRange!;
        const edge = state.mode === "range-start" ? original.start : original.end;
        const time = snapToProject(project, edge + currentTime - state.time, mode);
        props.onRange(state.mode === "range-start" ? { ...original, start: Math.min(time, original.end - .001) }
          : { ...original, end: Math.max(time, original.start + .001) });
      } else if (state.mode === "range") {
        const time = snapTime(project, currentTime, mode, state.time);
        const firstTrack = project.tracks.findIndex(
          (t) => t.id === state.trackId,
        );
        const lastTrack = project.tracks.findIndex(
          (t) => t.id === boundedTrackAt(event.clientY)?.id,
        );
        const indexes = [
          firstTrack,
          lastTrack < 0 ? firstTrack : lastTrack,
          ...(state.originalRange?.trackIds ?? []).map((id) => project.tracks.findIndex((t) => t.id === id)),
        ].sort((a, b) => a - b);
        props.onRange({
          start: Math.min(state.time, time, state.originalRange?.start ?? Infinity),
          end: Math.max(state.time, time, state.originalRange?.end ?? -Infinity),
          trackIds: project.tracks
            .slice(indexes[0], indexes.at(-1)! + 1)
            .map((t) => t.id),
        });
      } else if (state.mode.startsWith("locator")) {
        const time = snapTime(project, currentTime, mode);
        if (state.mode === "locator-left")
          props.onLoop(
            Math.min(time, state.original!.end - 0.001),
            state.original!.end,
          );
        else if (state.mode === "locator-right")
          props.onLoop(
            state.original!.start,
            Math.max(time, state.original!.start + 0.001),
          );
        else if (state.mode === "locator-body") {
          const delta = Math.max(-state.original!.start, time - state.time);
          props.onLoop(
            state.original!.start + delta,
            state.original!.end + delta,
          );
        } else if (next.moved)
          props.onLoop(Math.min(state.time, time), Math.max(state.time, time));
      } else if (state.mode === "tempo" || state.mode === "signature") {
        next.horizontalMoved = state.horizontalMoved || Math.abs(event.clientX - state.x) > 4;
        next.verticalMoved = state.verticalMoved || Math.abs(event.clientY - state.y) > 4;
        const originalTime = state.mapTime ?? state.time;
        next.delta = state.mapFixed || !next.horizontalMoved ? originalTime
          : snapToProject(project, originalTime + currentTime - state.time, state.mode === "signature" ? "bar" : mode);
        if (state.mode === "tempo") {
          next.bpm = next.verticalMoved
            ? Math.max(1, Math.min(1000, Math.round((state.originalBpm! + (state.y - event.clientY) * state.bpmPerPixel!) * 4) / 4))
            : state.originalBpm;
        }
      }
      setDragging(next);
    };
    const onUp = (event: PointerEvent) => {
      let state = dragRef.current;
      if (!state) return;
      if (state.moved && ["move", "start", "end", "range-move", "range-start", "range-end"].includes(state.mode)) {
        onMove(event); state = dragRef.current!;
      }
      if (state.mode === "track") {
        if (state.moved) props.onTrackReorder(state.ids!, project.tracks[insertionAt(event.clientY)]?.id ?? null);
        else props.onTrackSelect(state.trackId!);
      } else if (state.mode === "cursor") {
        if (state.moved) flushSeek(snapToProject(project, timeAt(event.clientX) + (state.cursorOffset ?? 0), event.ctrlKey ? "off" : snap));
        else if (pendingSeek.current !== null) flushSeek();
      }
      else if (state.mode === "move" && state.moved)
        props.onMove(
          state.ids!,
          state.delta ?? 0,
          state.targetTrack,
          !!state.copy,
        );
      else if ((state.mode === "start" || state.mode === "end") && state.moved)
        props.onTrim(state.ids!, state.mode, state.delta ?? 0);
      else if ((state.mode === "tempo" || state.mode === "signature") && state.moved) {
        const originalTime = state.mapTime ?? state.time, time = state.delta ?? originalTime;
        if (Math.abs(time - originalTime) > 1e-8 || state.bpm !== state.originalBpm)
          props.onMapMove({ kind: state.mode, id: state.mapId! }, time, state.bpm);
      }
      else if (state.mode === "range-move" && state.moved)
        props.onRangeMove(state.originalRange!, state.delta ?? 0, state.targetTrack, event.altKey);
      else if (state.mode === "move" && !state.moved && event.altKey)
        props.onSplit(
          state.ids!,
          snapTime(project, timeAt(event.clientX), snap),
        );
      // Alt-click splits; Alt-drag copies.
      else if (state.mode === "marquee" && state.moved) {
        const first = Math.min(state.time, timeAt(event.clientX)),
          last = Math.max(state.time, timeAt(event.clientX));
        const a = project.tracks.find((t) => t.id === state.trackId) ?? boundedTrackAt(state.y);
        const lastY = event.clientY - scroller.current!.getBoundingClientRect().top + scroller.current!.scrollTop;
        const top = Math.min(state.contentY!, lastY), bottom = Math.max(state.contentY!, lastY);
        const selected = project.clips
          .filter(
            (c) => {
              const clipTop = HEADER + project.tracks.findIndex((t) => t.id === c.trackId) * ROW + 9;
              return c.start < last && clipEnd(c) > first && clipTop < bottom && clipTop + 72 > top;
            },
          )
          .map((c) => c.id);
        props.onSelect(state.additive ? [...new Set([...state.initialSelection!, ...selected])] : selected, a?.id ?? "");
      } else if (state.mode.startsWith("locator") && !state.moved)
        props.onSeek(state.time);
      setDragging(null);
    };
    const onCancel = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (seekFrame.current !== null) cancelAnimationFrame(seekFrame.current);
        seekFrame.current = null; pendingSeek.current = null;
        if (dragRef.current?.mode.startsWith("range")) props.onRange(dragRef.current.originalRange ?? null);
        setDragging(null);
        setFileDrop(null);
      } else if (["Control", "Alt"].includes(event.key)) {
        const state = dragRef.current;
        if (state && ["move", "start", "end", "range-move"].includes(state.mode))
          onMove(new PointerEvent("pointermove", { clientX: state.currentX ?? state.x, clientY: state.currentY ?? state.y,
            ctrlKey: event.ctrlKey, altKey: event.altKey, shiftKey: event.shiftKey }));
      }
    };
    const cancelPointer = () => { if (dragRef.current?.mode === "cursor") flushSeek(); setDragging(null); };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onCancel);
    window.addEventListener("keyup", onCancel);
    window.addEventListener("pointercancel", cancelPointer);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onCancel);
      window.removeEventListener("keyup", onCancel);
      window.removeEventListener("pointercancel", cancelPointer);
    };
  }, [project, snap, props]);

  const pointerDown = (
    event: React.PointerEvent,
    clip?: Clip,
    edge?: "start" | "end",
  ) => {
    if (event.button !== 0) return;
    event.preventDefault();
    setMenu(null);
    event.currentTarget.setPointerCapture(event.pointerId);
    const at = timeAt(event.clientX),
      track = clip
        ? project.tracks.find((t) => t.id === clip.trackId)
        : trackAt(event.clientY);
    if (event.altKey && event.shiftKey) {
      props.onSeek(snapTime(project, at, snap));
      return;
    }
    if (tool === "range") {
      if (!track) return;
      if (track) props.onSelect([], track.id);
      const time = snapTime(project, at, event.ctrlKey ? "off" : snap);
      const previous = event.shiftKey ? props.range : null;
      const rows = [...(previous?.trackIds ?? []), track.id].map((id) => project.tracks.findIndex((t) => t.id === id));
      props.onRange({
        start: Math.min(time, previous?.start ?? Infinity),
        end: Math.max(time, previous?.end ?? -Infinity),
        trackIds: project.tracks.slice(Math.min(...rows), Math.max(...rows) + 1).map((t) => t.id),
      });
      setDragging({
        mode: "range",
        x: event.clientX,
        y: event.clientY,
        time,
        trackId: track?.id,
        originalRange: previous ?? undefined,
      });
      return;
    }
    if (clip) {
      if (tool === "split") {
        props.onSplit(
          [clip.id],
          snapTime(project, at, event.ctrlKey ? "off" : snap),
        );
        return;
      }
      if (tool === "erase") {
        props.onDelete([clip.id]);
        return;
      }
      let ids = effectiveSelection.has(clip.id) ? selection : [clip.id];
      if (event.shiftKey) {
        const members = new Set(relatedClips(project, [clip.id], linked).map((c) => c.id));
        ids = effectiveSelection.has(clip.id) ? selection.filter((id) => !members.has(id)) : [...selection, clip.id];
      }
      if (!event.shiftKey)
        ids = [clip.id, ...ids.filter((id) => id !== clip.id)];
      props.onSelect(ids, clip.trackId);
      props.onRange(null);
      if (!ids.includes(clip.id)) return;
      setDragging({
        mode: edge ?? "move",
        x: event.clientX,
        y: event.clientY,
        time: at,
        id: clip.id,
        ids,
        copy: !edge && event.altKey,
        ctrl: !edge && event.ctrlKey,
      });
    } else {
      props.onRange(null);
      if (!event.shiftKey) props.onSelect([], track?.id ?? "");
      setDragging({
        mode: "marquee",
        x: event.clientX,
        y: event.clientY,
        time: at,
        additive: event.shiftKey,
        initialSelection: selection,
        trackId: boundedTrackAt(event.clientY)?.id,
        contentY: event.clientY - scroller.current!.getBoundingClientRect().top + scroller.current!.scrollTop,
      });
    }
  };

  let secondStep = 1;
  for (const step of [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300])
    if (step * scale >= 80) {
      secondStep = step;
      break;
    }
  const ticks: number[] = [];
  for (
    let t = Math.floor(startTime / secondStep) * secondStep;
    t <= endTime;
    t += secondStep
  )
    ticks.push(t);
  const lines = gridLines(project, startTime, endTime, scale);
  const tempos = temposInOrder(project), signatures = signatureSections(project);
  const minTempo = Math.min(80, ...tempos.map((t) => t.bpm)) - 15;
  const maxTempo = Math.max(160, ...tempos.map((t) => t.bpm)) + 15;
  const tempoY = (bpm: number) => 16 + (maxTempo - bpm) / (maxTempo - minTempo) * (TEMPO_ROW - 30);
  const mapPointer = (event: React.PointerEvent, selected: MapSelection, fixed: boolean) => {
    event.stopPropagation();
    if (event.button !== 0) return;
    if (tool === "erase") { if (!fixed) props.onMapDelete(selected); return; }
    props.onMapSelect(selected);
    if (fixed && selected.kind === "signature") return;
    const tempo = selected.kind === "tempo" ? project.tempos.find((point) => point.id === selected.id) : null;
    const signature = selected.kind === "signature" ? project.signatures.find((point) => point.id === selected.id) : null;
    if (!tempo && !signature) return;
    const mapTime = tempo ? timeAtQuarter(project, tempo.quarter) : timeAtBar(project, signature!.bar);
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging({ mode: selected.kind, x: event.clientX, y: event.clientY, time: timeAt(event.clientX), mapId: selected.id,
      mapTime, mapFixed: fixed, originalBpm: tempo?.bpm, bpm: tempo?.bpm,
      bpmPerPixel: (maxTempo - minTempo) / (TEMPO_ROW - 30) });
  };
  const eventPreview = !drag?.moved || !drag.ids ? [] : drag.mode === "move"
    ? movePreview(project, drag.ids, drag.delta ?? 0, linked, drag.targetTrack)
    : drag.mode === "start" || drag.mode === "end" ? trimPreview(project, drag.ids, drag.mode, drag.delta ?? 0, linked) : [];
  const previewById = new Map(eventPreview.map((c) => [c.id, c]));
  const displayedClips = drag?.copy ? project.clips : project.clips.map((c) => previewById.get(c.id) ?? c);
  const movingRange = drag?.mode === "range-move" && drag.moved
    ? rangePreview(project, drag.originalRange!, drag.delta ?? 0, drag.targetTrack, linked) : null;
  const displayedRange = movingRange?.range ?? props.range;
  const ghosts = drag?.copy && drag.mode === "move" && drag.moved ? eventPreview : movingRange?.clips ?? [];
  const eventDoubleClick = (event: React.MouseEvent, clip: Clip) => {
    event.stopPropagation();
    if (tool === "object") props.onEdit(clip);
    else if (tool === "range") {
      const previous = event.shiftKey ? props.range : null;
      const rows = [...(previous?.trackIds ?? []), clip.trackId].map((id) => project.tracks.findIndex((t) => t.id === id));
      props.onSelect([], clip.trackId);
      props.onRange({ start: Math.min(previous?.start ?? clip.start, clip.start),
        end: Math.max(previous?.end ?? clipEnd(clip), clipEnd(clip)),
        trackIds: project.tracks.slice(Math.min(...rows), Math.max(...rows) + 1).map((t) => t.id) });
    }
  };
  const rangePointer = (event: React.PointerEvent, mode: "range-move" | "range-start" | "range-end") => {
    if (event.button !== 0 || tool !== "range" || !props.range) return;
    event.stopPropagation(); event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setMenu(null);
    setDragging({ mode, x: event.clientX, y: event.clientY, time: timeAt(event.clientX),
      originalRange: structuredClone(props.range), trackId: boundedTrackAt(event.clientY)?.id, copy: event.altKey });
  };
  const cursorPosition = drag?.mode === "cursor" ? drag.delta ?? position : position;

  return (
    <div className="arrangement">
      <div className="track-list" ref={headerScroller} style={{ height: scroll.height || "100%" }}
        onDragOver={(event) => filesOver(event, true)} onDragLeave={filesLeave} onDrop={(event) => filesDrop(event, true)}
        onDoubleClick={(event) => { if (!(event.target as HTMLElement).closest(".track-head,.map-track-head,.track-list-ruler")) props.onAddTrack(); }}
        onContextMenu={(event) => { event.preventDefault(); if (!(event.target as HTMLElement).closest(".map-track-head,.track-list-ruler")) { setMenu(null); props.onTrackMenu(null, event.clientX, event.clientY); } }}>
        <div className="track-list-ruler">
          <span>TRACKS</span>
          <span className="track-count">{project.tracks.length + 2}</span>
          <button
            className="icon-button small"
            title="Add audio track (T)"
            onClick={props.onAddTrack}
          >
            <Plus size={14} />
          </button>
        </div>
        <div style={{ transform: `translateY(${-scroll.y}px)` }}>
          <div className={`map-track-head tempo-head ${props.selectedMap?.kind === "tempo" ? "active" : ""}`} style={{ height: TEMPO_ROW }}
            onClick={() => props.onMapSelect({ kind: "tempo", id: tempos.filter((t) => t.quarter <= quarterAtTime(project, position)).at(-1)!.id })}>
            <div><Activity size={15}/><strong>Tempo</strong><button className="icon-button small" title="Add tempo event at cursor" onClick={(e) => { e.stopPropagation(); props.onMapAdd("tempo", position); }}><Plus size={14}/></button></div>
            <small>PROJECT TEMPO · STEP</small>
          </div>
          <div className={`map-track-head signature-head ${props.selectedMap?.kind === "signature" ? "active" : ""}`} style={{ height: SIGNATURE_ROW }}
            onClick={() => props.onMapSelect({ kind: "signature", id: positionAtQuarter(project, quarterAtTime(project, position)).signature.id })}>
            <div><span className="signature-icon">♯</span><strong>Signature</strong><button className="icon-button small" title="Add signature event at cursor bar" onClick={(e) => { e.stopPropagation(); props.onMapAdd("signature", position); }}><Plus size={14}/></button></div>
          </div>
          {project.tracks.map((track, i) => (
            <div
              key={track.id}
              className={`track-head ${props.activeTrack === track.id ? "active" : ""} ${props.selectedTracks.includes(track.id) ? "selected" : ""} ${drag?.mode === "track" && drag.moved && drag.ids?.includes(track.id) ? "track-moving" : ""}`}
              style={{ "--track-color": track.color } as React.CSSProperties}
              onPointerDown={(event) => beginTrack(event, track.id)}
              onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setMenu(null); props.onTrackMenu(track.id, event.clientX, event.clientY); }}
            >
              <div className="track-heading">
                <span className="track-index">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <AudioLines size={15} />
                <TrackName
                  name={track.name}
                  onChange={(name) => props.onTrack(track.id, { name })}
                />
                <button
                  className="icon-button small"
                  title="Track actions"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenu(null);
                    const bounds = e.currentTarget.getBoundingClientRect();
                    props.onTrackMenu(track.id, bounds.left, bounds.bottom + 4);
                  }}
                >
                  <MoreHorizontal size={15} />
                </button>
              </div>
              <div className="track-controls">
                <button className="time-base-button" aria-label={`${track.name} time base`} title={`${track.timeBase === "musical" ? "Musical: events follow tempo" : "Linear: events keep their time"}. Click to switch.`}
                  onClick={(e) => { e.stopPropagation(); props.onTimeBase(track.id); }}>
                  {track.timeBase === "musical" ? <Music2 size={13}/> : <Clock3 size={13}/>}
                </button>
                <button
                  className={`track-switch mute ${track.mute ? "on" : ""}`}
                  title="Mute (M)"
                  onClick={(e) => {
                    e.stopPropagation();
                    props.onTrack(track.id, { mute: !track.mute });
                  }}
                >
                  M
                </button>
                <button
                  className={`track-switch solo ${track.solo ? "on" : ""}`}
                  title="Solo (S)"
                  onClick={(e) => {
                    e.stopPropagation();
                    props.onTrack(track.id, { solo: !track.solo });
                  }}
                >
                  S
                </button>
                <span className="track-level">
                  {track.gain > 0
                    ? (20 * Math.log10(track.gain)).toFixed(1)
                    : "−∞"}{" "}
                  dB
                </span>
                <Volume2 size={12} />
                <span className="track-pan">
                  {track.pan === 0
                    ? "C"
                    : `${track.pan < 0 ? "L" : "R"}${Math.round(Math.abs(track.pan) * 100)}`}
                </span>
              </div>
            </div>
          ))}
        </div>
        {drag?.mode === "track" && drag.moved && <div className="track-insertion-line" style={{ top: HEADER + (drag.insertionIndex ?? 0) * ROW - scroll.y }}><span>Move {drag.ids?.length} track{drag.ids?.length === 1 ? "" : "s"}</span></div>}
        {fileDrop?.destination.source === "track-list" && <div className="track-insertion-line file-insertion" style={{ top: HEADER + fileDrop.row * ROW - scroll.y }}><span>New audio · {musicalTime(project, fileDrop.destination.start)}</span></div>}
        {!project.tracks.length && (
          <div className="track-list-empty">
            <AudioLines size={22} />
            <span>No tracks yet</span>
          </div>
        )}
      </div>
      <div
        className={`timeline-scroll tool-${tool}`}
        ref={scroller}
        onScroll={syncViewport}
        onDragOver={(event) => filesOver(event, false)}
        onDragLeave={filesLeave}
        onDrop={(event) => filesDrop(event, false)}
      >
        <div
          className="timeline-content"
          onPointerDown={(e) => { if (e.target === e.currentTarget) pointerDown(e); }}
          onDoubleClick={(e) => {
            if (tool !== "range") return;
            const track = trackAt(e.clientY), time = timeAt(e.clientX);
            const clip = [...project.clips].reverse().find((c) => c.trackId === track?.id && c.start <= time && clipEnd(c) > time);
            if (clip) eventDoubleClick(e, clip);
          }}
          style={{
            width: totalWidth,
            height: contentHeight,
          }}
        >
          <div className="timeline-ruler" style={{ width: totalWidth }}
            onContextMenu={(e) => e.preventDefault()}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              if (e.clientY - e.currentTarget.getBoundingClientRect().top > 15) { beginCursor(e); return; }
              const time = snapToProject(project, timeAt(e.clientX), snap);
              if (e.ctrlKey && e.altKey) { props.onLoop(time, time); return; }
              if (e.ctrlKey) { props.onLoop(time, Math.max(time + .001, props.loop.end)); return; }
              if (e.altKey) { props.onLoop(Math.min(time, props.loop.start), time); return; }
              e.preventDefault();
              e.currentTarget.setPointerCapture(e.pointerId);
              setDragging({ mode: "locator-create", x: e.clientX, y: e.clientY, time });
            }}>
            {props.loop.end > props.loop.start && <div className={`locator-range ${props.loop.enabled ? "enabled" : ""}`}
              style={{ left: props.loop.start * scale, width: (props.loop.end - props.loop.start) * scale }}
              onPointerDown={(e) => {
                e.stopPropagation();
                e.currentTarget.setPointerCapture(e.pointerId);
                setDragging({ mode: "locator-body", x: e.clientX, y: e.clientY, time: timeAt(e.clientX), original: props.loop });
              }}>
              <span className="locator-handle left" title="Left locator" onPointerDown={(e) => {
                e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId);
                setDragging({ mode: "locator-left", x: e.clientX, y: e.clientY, time: props.loop.start, original: props.loop });
              }}>L</span>
              <span className="locator-handle right" title="Right locator" onPointerDown={(e) => {
                e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId);
                setDragging({ mode: "locator-right", x: e.clientX, y: e.clientY, time: props.loop.end, original: props.loop });
              }}>R</span>
            </div>}
            {(project.rulerFormat === "bars" ? lines.filter((line) => line.strong) : ticks.map((time) => ({ time, strong: true, bar: 0, beat: 0 }))).map((tick) =>
              <div className="ruler-tick" key={tick.time} style={{ left: tick.time * scale }}><span>{project.rulerFormat === "bars" ? tick.bar : formatTime(tick.time).slice(0, 5) + (secondStep < 1 ? "." + formatTime(tick.time).slice(-3) : "")}</span></div>)}
            <div className="ruler-playhead" title="Drag project cursor" onPointerDown={(e) => beginCursor(e, true)} style={{ left: cursorPosition * scale }}/>
          </div>
          <div className="tempo-track-lane" style={{ top: RULER, height: TEMPO_ROW }}
            onDoubleClick={(e) => props.onMapAdd("tempo", snapToProject(project, timeAt(e.clientX), snap))}>
            {tempos.map((tempo, index) => {
              const start = timeAtQuarter(project, tempo.quarter), end = index + 1 < tempos.length ? timeAtQuarter(project, tempos[index + 1].quarter) : totalEnd;
              if (end < startTime || start > endTime) return null;
              const from = Math.max(start, startTime), to = Math.min(end, endTime);
              const moving = drag?.mode === "tempo" && drag.mapId === tempo.id && drag.moved;
              const x = moving ? drag.delta ?? start : start;
              const bpm = moving ? drag.bpm ?? tempo.bpm : tempo.bpm;
              return <div key={tempo.id}>
                <i className="tempo-step" style={{ left: (moving ? Math.max(x, startTime) : from) * scale, width: Math.max(0, to - (moving ? Math.max(x, startTime) : from)) * scale, top: tempoY(bpm) }}/>
                {start >= startTime - 5 && <button className={`tempo-point ${props.selectedMap?.id === tempo.id ? "selected" : ""}`} style={{ left: x * scale, top: tempoY(bpm) }}
                  title={musicalTime(project, x) + " · " + bpm + " BPM"}
                  onDoubleClick={(e) => e.stopPropagation()} onPointerDown={(e) => mapPointer(e, { kind: "tempo", id: tempo.id }, tempo.quarter === 0)}>
                  <i/><span>{Number(bpm.toFixed(3))}</span>
                </button>}
              </div>;
            })}
          </div>
          <div className="signature-track-lane" style={{ top: RULER + TEMPO_ROW, height: SIGNATURE_ROW }}
            onDoubleClick={(e) => props.onMapAdd("signature", snapToProject(project, timeAt(e.clientX), "bar"))}>
            {signatures.filter((signature) => timeAtBar(project, signature.bar) <= endTime && timeAtBar(project, signature.bar) >= startTime - 5).map((signature) => {
              const time = timeAtBar(project, signature.bar), x = drag?.mode === "signature" && drag.mapId === signature.id && drag.moved ? drag.delta ?? time : time;
              return <button key={signature.id} className={`signature-point ${props.selectedMap?.id === signature.id ? "selected" : ""}`} style={{ left: x * scale }}
                title={`Bar ${signature.bar}`} onDoubleClick={(e) => e.stopPropagation()}
                onPointerDown={(e) => mapPointer(e, { kind: "signature", id: signature.id }, signature.bar === 1)}>
                {signature.numerator}/{signature.denominator}
              </button>;
            })}
          </div>
          <div
            className="grid-lines"
            style={{
              top: RULER,
              bottom: 0,
            }}
          >
            {(project.rulerFormat === "seconds" ? ticks : []).map((time) => (
              <i
                className="second-line"
                key={`s${time}`}
                style={{ left: time * scale }}
              />
            ))}
            {lines.map(({ time, strong }, i) => (
              <i
                className={strong ? "bar-line" : "beat-line"}
                key={i}
                style={{ left: time * scale }}
              />
            ))}
          </div>
          {props.loop.end > props.loop.start && <div className={`cycle-shading ${props.loop.enabled ? "enabled" : ""}`} style={{ left: props.loop.start * scale, width: (props.loop.end - props.loop.start) * scale, top: RULER, bottom: 0 }}/>} 
          <div className="project-end-line" style={{ left: project.projectDuration * scale, top: RULER, bottom: 0 }} title="Project end"/>
          {project.tracks.map((track, i) => (
            <div
              key={track.id}
              className={`track-lane ${track.mute ? "muted" : ""}`}
              style={{ top: HEADER + i * ROW, height: ROW }}
              onPointerDown={(e) => pointerDown(e)}
            >
              {displayedClips
                .filter((c) => c.trackId === track.id)
                .map((clip) => {
                  const original = project.clips.find((c) => c.id === clip.id)!;
                  const asset = getAsset(project, clip);
                  if (
                    !asset ||
                    clipEnd(clip) < startTime - 2 ||
                    clip.start > endTime + 2
                  )
                    return null;
                  const selected = effectiveSelection.has(clip.id);
                  return (
                    <div
                      key={clip.id}
                      className={`audio-clip ${selected ? "selected" : ""}`}
                      style={
                        {
                          left: clip.start * scale,
                          width: Math.max(3, clip.duration * scale),
                          "--clip-color": track.color,
                        } as React.CSSProperties
                      }
                      onPointerDown={(e) => {
                        e.stopPropagation();
                        pointerDown(e, original);
                      }}
                      onDoubleClick={(e) => eventDoubleClick(e, original)}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        props.onSelect(effectiveSelection.has(original.id) ? [original.id, ...selection.filter((id) => id !== original.id)] : [original.id], track.id);
                        setMenu({ x: e.clientX, y: e.clientY, clip: original, time: timeAt(e.clientX) });
                      }}
                    >
                      <div className="clip-label">
                        <AudioLines size={12} />
                        <span>{clip.name}</span>
                        {clip.groupId && <GripVertical size={12} />}
                      </div>
                      <Waveform
                        asset={asset}
                        clip={clip}
                        scale={scale}
                        left={scroll.x}
                        viewport={scroll.width}
                        samples={peaks.get(asset.id)}
                        color={track.color}
                      />
                      {tool === "object" && <><div
                        className="trim-handle left"
                        title="Normal sizing: reveal or hide audio"
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          pointerDown(e, original, "start");
                        }}
                      />
                      <div
                        className="trim-handle right"
                        title="Normal sizing: reveal or hide audio"
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          pointerDown(e, original, "end");
                        }}
                      /></>}
                    </div>
                  );
                })}
            </div>
          ))}
          {fileDrop?.destination.source === "timeline" && <div className="audio-import-preview" style={{ left: fileDrop.destination.start * scale, top: HEADER + fileDrop.row * ROW + 9 }}>
            <strong>{fileDrop.destination.targetTrackId ? project.tracks.find((track) => track.id === fileDrop.destination.targetTrackId)?.name : "New audio track"}</strong>
            <span>{fileDrop.count} file{fileDrop.count === 1 ? "" : "s"} · {project.rulerFormat === "bars" ? musicalTime(project, fileDrop.destination.start) : formatTime(fileDrop.destination.start)}</span>
          </div>}
          {displayedRange && displayedRange.end > displayedRange.start && (
            <div className={`range-overlay ${tool === "range" ? "editable" : ""} ${movingRange && !drag?.copy ? "moving" : ""}`}
              style={{ left: displayedRange.start * scale, width: Math.max(1, (displayedRange.end - displayedRange.start) * scale),
                top: HEADER + Math.max(0, project.tracks.findIndex((t) => t.id === displayedRange.trackIds[0])) * ROW,
                height: Math.max(1, displayedRange.trackIds.length) * ROW }}
              onPointerDown={(e) => rangePointer(e, "range-move")}
              onDoubleClick={(e) => {
                const track = boundedTrackAt(e.clientY), time = timeAt(e.clientX);
                const clip = [...project.clips].reverse().find((c) => c.trackId === track?.id && c.start <= time && clipEnd(c) > time);
                if (clip) eventDoubleClick(e, clip);
              }}>
              <span>{formatTime(displayedRange.end - displayedRange.start)} · Drag to move · Alt to copy</span>
              {tool === "range" && <>
                <div className="range-handle left" title="Resize range start" onPointerDown={(e) => rangePointer(e, "range-start")}/>
                <div className="range-handle right" title="Resize range end" onPointerDown={(e) => rangePointer(e, "range-end")}/>
              </>}
            </div>
          )}
          {drag?.mode === "marquee" && drag.moved && (
            <div
              className="selection-rectangle"
              style={{
                left: Math.min(
                  drag.time * scale,
                  timeAt(drag.currentX!) * scale,
                ),
                width: Math.abs(drag.time - timeAt(drag.currentX!)) * scale,
                top:
                  Math.min(drag.contentY!, drag.currentY! - scroller.current!.getBoundingClientRect().top + scroll.y),
                height: Math.abs(drag.contentY! - (drag.currentY! - scroller.current!.getBoundingClientRect().top + scroll.y)),
              }}
            />
          )}
          {ghosts.map((clip) => <div key={clip.id} className="copy-ghost"
            style={{ left: clip.start * scale, width: Math.max(3, clip.duration * scale),
              top: HEADER + project.tracks.findIndex((t) => t.id === clip.trackId) * ROW + 9 }}>
            <span>{clip.name}</span>
            <Waveform asset={getAsset(project, clip)} clip={clip} scale={scale} left={scroll.x} viewport={scroll.width}
              samples={peaks.get(clip.assetId)} color={project.tracks.find((t) => t.id === clip.trackId)!.color}/>
          </div>)}
          <div
            className="playhead"
            style={{
              transform: `translateX(${cursorPosition * scale}px)`,
              height: "100%",
            }}
          >
            <span />
          </div>
          {!project.clips.length && (
            <div
              className="timeline-empty"
              style={{ left: scroll.x, width: scroll.width }}
            >
              <div className="empty-wave">
                <AudioLines size={44} strokeWidth={1.2} />
              </div>
              <h2>A place for your next set.</h2>
              <p>
                Bring in a song or aligned stems.
                <br />
                Arrange on the project grid. Analyze its tempo and signature.
              </p>
              <button
                className="primary-button"
                onClick={() => props.onImport()}
              >
                Import Audio <span>WAV · MP3 · FLAC</span>
              </button>
              <small>WAV, MP3 & FLAC · Original audio stays unchanged</small>
            </div>
          )}
        </div>
      </div>
      {menu && (
        <>
          <div className="menu-dismiss" onPointerDown={() => setMenu(null)} />
          <div
            className="context-menu"
            style={{
              left: Math.min(menu.x, innerWidth - 230),
              top: Math.max(40, Math.min(menu.y, innerHeight - 420)),
            }}
          >
            <button onClick={() => { props.onEdit(menu.clip); setMenu(null); }}>Open Audio Editor <kbd>Ctrl E</kbd></button>
            <button
              onClick={() => {
                props.onAnalyze(menu.clip);
                setMenu(null);
              }}
            >
              Analyze Audio…
            </button>
            <button
              onClick={() => {
                props.onLoop(menu.clip.start, clipEnd(menu.clip));
                setMenu(null);
              }}
            >
              Locators to Selection <kbd>P</kbd>
            </button>
            <button
              onClick={() => {
                props.onSplit(selection, position);
                setMenu(null);
              }}
            >
              Split at Cursor <kbd>Alt X</kbd>
            </button>
            <button
              onClick={() => {
                props.onMove(
                  selection,
                  Math.max(...relatedClips(project, selection, linked).map(clipEnd)) - Math.min(...relatedClips(project, selection, linked).map((c) => c.start)),
                  undefined,
                  true,
                );
                setMenu(null);
              }}
            >
              Duplicate <kbd>Ctrl D</kbd>
            </button>
            <button
              onClick={() => {
                props.onFront(selection);
                setMenu(null);
              }}
            >
              Move to Front <kbd>U</kbd>
            </button>
            <button onClick={() => { props.onBack(selection); setMenu(null); }}>Move to Back <kbd>Shift U</kbd></button>
            {project.clips.filter((c) => c.trackId === menu.clip.trackId && c.start <= menu.time && clipEnd(c) > menu.time).length > 1 && <>
              <hr/><small>Overlapping events at pointer</small>
              <div className="overlap-choices">
                {[...project.clips].reverse().filter((c) => c.trackId === menu.clip.trackId && c.start <= menu.time && clipEnd(c) > menu.time).map((clip, i) =>
                  <button key={clip.id} className={clip.id === menu.clip.id ? "active" : ""}
                    onClick={() => { props.onSelect([clip.id], clip.trackId); setMenu({ ...menu, clip }); }}>
                    <span>{clip.name}</span><small>{i === 0 ? "Front" : "Behind"} · {formatTime(clip.start)}</small>
                  </button>)}
              </div>
            </>}
            <hr />
            <button
              onClick={() => {
                props.onDelete(selection);
                setMenu(null);
              }}
            >
              Delete <kbd>Del</kbd>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
