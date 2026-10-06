import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Minus, Plus, Maximize2, X } from "lucide-react";
import { Waveform } from "./Timeline";
import { clipEnd, formatTime, getAsset, trimPreview, type Clip, type Project, type Snap, type TimeRange } from "./model";
import { gridLines, musicalTime, snapToProject } from "./music";

type Props = {
  project: Project;
  clip: Clip;
  peaks?: Float32Array;
  range: TimeRange | null;
  position: number;
  snap: Snap;
  linked: boolean;
  onRange: (range: TimeRange | null) => void;
  onSeek: (time: number) => void;
  onTrim: (ids: string[], edge: "start" | "end", delta: number) => void;
  onSplit: (ids: string[], time: number) => void;
  onAnalyze: () => void;
  onClose: () => void;
};
type Gesture = { mode: "range" | "start" | "end"; x: number; time: number; moved: boolean; delta: number; previous?: TimeRange };

/** A source view that edits project events and ranges; the media is never rewritten. */
export default function AudioEditor(props: Props) {
  const { project, clip, range } = props;
  const asset = getAsset(project, clip), track = project.tracks.find((t) => t.id === clip.trackId)!;
  const node = useRef<HTMLDivElement>(null), latest = useRef(props); latest.current = props;
  const [mode, setMode] = useState<"range" | "trim" | "split">("range");
  const [height, setHeight] = useState(260);
  const [view, setView] = useState({ scale: Math.min(1200, 800 / (clip.duration + .4)), x: 0, width: 800 });
  const viewport = useRef(view), pending = useRef(false);
  const requestView = (next: typeof view) => { viewport.current = next; pending.current = true; setView(next); };
  const gestures = useRef<Gesture | null>(null), [gesture, setGesture] = useState<Gesture | null>(null);
  const changeGesture = (value: Gesture | null) => { gestures.current = value; setGesture(value); };
  const origin = clip.start - clip.sourceStart;
  const previousOrigin = useRef(origin);
  useLayoutEffect(() => {
    if (previousOrigin.current === origin) return;
    const old = viewport.current;
    requestView({ ...old, x: Math.max(0, old.x + (origin - previousOrigin.current) * old.scale) });
    previousOrigin.current = origin;
  }, [origin]);
  const sourceClip = { ...clip, start: Math.max(0, origin), sourceStart: Math.max(0, -origin),
    duration: Math.max(.001, asset.duration - Math.max(0, -origin)) };
  const totalWidth = Math.max(view.width, (clipEnd(sourceClip) + 1) * view.scale);
  const timeAt = (x: number) => Math.max(0, (x - node.current!.getBoundingClientRect().left + node.current!.scrollLeft) / viewport.current.scale);
  const fit = (start: number, end: number) => {
    const width = node.current?.clientWidth ?? viewport.current.width;
    const scale = Math.max(.2, Math.min(1200, (width - 32) / Math.max(.02, end - start)));
    requestView({ width, scale, x: Math.max(0, start * scale - 16) });
  };
  const zoom = (factor: number, pixel = viewport.current.width / 2) => {
    const old = viewport.current, scale = Math.max(.2, Math.min(1200, old.scale * factor));
    const time = (old.x + pixel) / old.scale;
    requestView({ ...old, scale, x: Math.max(0, time * scale - pixel) });
  };
  useLayoutEffect(() => {
    if (!pending.current || !node.current) return;
    node.current.scrollLeft = view.x;
    pending.current = false;
    if (node.current.scrollLeft !== view.x) {
      const value = { ...view, x: node.current.scrollLeft }; viewport.current = value; setView(value);
    }
  }, [view]);
  useLayoutEffect(() => {
    const element = node.current!;
    const resize = new ResizeObserver(() => {
      const old = viewport.current; requestView({ ...old, width: element.clientWidth });
    });
    resize.observe(element); fit(clip.start, clipEnd(clip));
    element.closest<HTMLElement>(".audio-editor")?.focus({ preventScroll: true });
    return () => resize.disconnect();
  }, []);
  const wheelRef = useRef(zoom); wheelRef.current = zoom;
  useEffect(() => {
    const element = node.current!;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        event.preventDefault();
        if (event.deltaY) wheelRef.current(Math.pow(1.15, -Math.sign(event.deltaY) * Math.min(1, Math.abs(event.deltaY) / 100)),
          event.clientX - element.getBoundingClientRect().left);
      } else if (event.shiftKey) { event.preventDefault(); element.scrollLeft += event.deltaY + event.deltaX; }
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, []);
  useEffect(() => {
    const move = (event: PointerEvent) => {
      const state = gestures.current; if (!state) return;
      const p = latest.current, time = snapToProject(p.project, timeAt(event.clientX), event.ctrlKey ? "off" : p.snap);
      const next = { ...state, moved: state.moved || Math.abs(event.clientX - state.x) > 3 };
      if (state.mode === "range") {
        const t = Math.max(p.clip.start, Math.min(clipEnd(p.clip), time));
        p.onRange({ start: Math.min(state.time, t, state.previous?.start ?? Infinity),
          end: Math.max(state.time, t, state.previous?.end ?? -Infinity), trackIds: [p.clip.trackId] });
      } else {
        const edge = state.mode === "start" ? p.clip.start : clipEnd(p.clip);
        next.delta = snapToProject(p.project, edge + timeAt(event.clientX) - state.time, event.ctrlKey ? "off" : p.snap) - edge;
      }
      changeGesture(next);
    };
    const up = (event: PointerEvent) => {
      if (!gestures.current) return;
      if (gestures.current.moved) move(event);
      const state = gestures.current!, p = latest.current;
      if (state.moved && state.mode !== "range") p.onTrim([p.clip.id], state.mode, state.delta);
      changeGesture(null);
    };
    const cancel = () => {
      const state = gestures.current;
      if (state?.mode === "range") latest.current.onRange(state.previous ?? null);
      changeGesture(null);
    };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") cancel(); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel); window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel); window.removeEventListener("keydown", key);
    };
  }, []);
  const down = (event: React.PointerEvent, edge?: "start" | "end") => {
    if (event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.closest<HTMLElement>(".audio-editor")?.focus({ preventScroll: true });
    const time = snapToProject(project, timeAt(event.clientX), event.ctrlKey ? "off" : props.snap);
    if (!edge && mode === "split") { props.onSplit([clip.id], time); return; }
    if (!edge && mode === "trim") { props.onSeek(time); return; }
    event.currentTarget.setPointerCapture(event.pointerId);
    if (edge) changeGesture({ mode: edge, x: event.clientX, time: timeAt(event.clientX), moved: false, delta: 0 });
    else {
      const at = Math.max(clip.start, Math.min(clipEnd(clip), time));
      const previous = event.shiftKey && range?.trackIds.includes(clip.trackId) ? range : undefined;
      props.onRange({ start: Math.min(at, previous?.start ?? Infinity), end: Math.max(at, previous?.end ?? -Infinity), trackIds: [clip.trackId] });
      props.onSeek(at);
      changeGesture({ mode: "range", x: event.clientX, time: at, moved: false, delta: 0, previous });
    }
  };
  const resized = gesture && gesture.mode !== "range" ? trimPreview(project, [clip.id], gesture.mode, gesture.delta, props.linked).find((c) => c.id === clip.id) ?? clip : clip;
  const visibleRange = range?.trackIds.includes(clip.trackId) ? range : null;
  const lines = gridLines(project, view.x / view.scale, (view.x + view.width) / view.scale, view.scale);
  return <section className="audio-editor" tabIndex={0} aria-label="Audio Editor" style={{ height, maxHeight: "55%" }}>
    <div className="editor-resize" title="Resize Audio Editor" onPointerDown={(event) => {
      if (event.button !== 0) return;
      event.preventDefault(); const top = event.clientY, original = height;
      const resize = (e: PointerEvent) => setHeight(Math.max(180, Math.min(450, original + top - e.clientY)));
      const end = () => { window.removeEventListener("pointermove", resize); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end); };
      window.addEventListener("pointermove", resize); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
    }}/>
    <div className="editor-heading">
      <strong>AUDIO EDITOR</strong><span className="editor-name" title={clip.name}>{clip.name}</span>
      <div className="editor-tools">{(["range", "trim", "split"] as const).map((name) => <button key={name} className={mode === name ? "active" : ""} onClick={() => setMode(name)}>{name === "range" ? "Range" : name === "trim" ? "Trim" : "Split"}</button>)}</div>
      <button className="icon-button small" title="Zoom out" onClick={() => zoom(1 / 1.5)}><Minus size={14}/></button>
      <button className="icon-button small" title="Zoom in" onClick={() => zoom(1.5)}><Plus size={14}/></button>
      <button className="icon-button small" title="Fit event" onClick={() => fit(clip.start, clipEnd(clip))}><Maximize2 size={14}/></button>
      <button className="secondary-button" disabled={!visibleRange || visibleRange.end <= visibleRange.start} onClick={() => { if (visibleRange) fit(visibleRange.start, visibleRange.end); }}>Fit Range</button>
      <button className="secondary-button" onClick={props.onAnalyze}>Analyze Audio…</button>
      <button className="icon-button small" title="Close Audio Editor" onClick={props.onClose}><X size={15}/></button>
    </div>
    <div className={`editor-scroll mode-${mode}`} ref={node} onScroll={() => {
      if (pending.current) return;
      const value = { ...viewport.current, x: node.current!.scrollLeft }; viewport.current = value; setView(value);
    }}>
      <div className="editor-source" style={{ width: totalWidth }} onPointerDown={(e) => down(e)} onDoubleClick={(e) => {
        if (mode !== "range") return; e.preventDefault(); props.onRange({ start: clip.start, end: clipEnd(clip), trackIds: [clip.trackId] });
      }}>
        {lines.map((line, i) => <div className={`editor-grid ${line.strong ? "bar" : ""}`} key={i} style={{ left: line.time * view.scale }}>
          {line.strong && <small>{project.rulerFormat === "bars" ? musicalTime(project, line.time) : formatTime(line.time)}</small>}
        </div>)}
        <div className="editor-audio" style={{ left: sourceClip.start * view.scale, width: sourceClip.duration * view.scale }}>
          <Waveform clip={sourceClip} asset={asset} samples={props.peaks} scale={view.scale} left={view.x} viewport={view.width} color={track.color} height={Math.max(80, height - 100)}/>
        </div>
        <div className="editor-event-boundary" style={{ left: resized.start * view.scale, width: resized.duration * view.scale }}/>
        {mode === "trim" && (["start", "end"] as const).map((edge) => <div key={edge} className="editor-trim"
          aria-label={`Trim event ${edge}`} title={`Trim ${edge}; Ctrl bypasses Snap`}
          style={{ left: (edge === "start" ? resized.start : clipEnd(resized)) * view.scale - 4 }} onPointerDown={(e) => down(e, edge)}/>)}
        {visibleRange && <div className="editor-range" style={{ left: visibleRange.start * view.scale, width: (visibleRange.end - visibleRange.start) * view.scale }}/>} 
        <div className="editor-cursor" style={{ left: props.position * view.scale }}/>
      </div>
    </div>
    <div className="editor-footer"><span>Source in {formatTime(resized.sourceStart)} · Length {formatTime(resized.duration)}</span>
      <span>{mode === "range" ? "Drag to select · Shift adds · Ctrl bypasses Snap" : mode === "trim" ? "Drag event edges to reveal or hide source audio" : "Click to split event"}</span></div>
  </section>;
}
