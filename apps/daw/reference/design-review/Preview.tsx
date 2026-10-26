/** Isolated U2 review surface. No IPC, audio engine, persistence or inference. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { AudioLines, ArrowRightToLine, Check, ChevronRight,
  Clock3, Download, Ellipsis, FileAudio, FolderOpen, Layers, Link2, Magnet, Maximize2, Metronome,
  Minus, MousePointer2, Music2, PanelLeft, Play, Plus, Redo2, Repeat2, Scissors,
  SkipBack, Square, StretchHorizontal, Trash2, Undo2, Volume2, Waves, X } from "lucide-react";
import ValueField from "../../src/ValueField";
import VolumeFader, { GainField } from "../../src/VolumeFader";
import { PanFader } from "../../src/controls";
import { TimeField } from "../../src/Transport";
import { AddAudioTrackDialog, RemoveTracksDialog } from "../../src/TrackDialogs";
import { ProjectHistory } from "../../src/history";
import { createProject, relatedClips, moveClips, trimClips, splitClips, removeClips,
  copyAudio, pasteAudio, duplicateTracks, importAssets, addAudioTracks, removeTracks, snapTime, type Project, type AudioClipboard, type TimeRange } from "../../src/model";
import { putTempo, putSignature, quarterAtTime, timeAtQuarter, timeAtBar,
  positionAtQuarter, tempoAtQuarter, setTrackTimeBase } from "../../src/music";
import "../../src/styles.css";
import "./review.css";

declare const BPMTRACKER_DESIGN_ASSETS: string;
const ASSETS = BPMTRACKER_DESIGN_ASSETS;
const colors = ["#80b6ac", "#8da9ce", "#b29ccd", "#c0b17d"];
const names = ["Drums", "Bass", "Guitars", "Vocals"];
const query = new URLSearchParams(location.search);
const bare = query.has("bare");
type Scene = "linked" | "single" | "range" | "tempo" | "signature" | "none" | "empty";
type WaveData = { name: string; duration: number; peaks: number[][] };
type MenuItem = { label: string; key?: string; action?: () => void; disabled?: string; check?: boolean; separator?: boolean; danger?: boolean; child?: MenuItem[] };
type Menu = { x: number; y: number; title?: string; items: MenuItem[]; invoker?: HTMLElement; align?: "right" };

function fixture(): Project {
  const project = createProject();
  return { ...project, name: "Aligned stems", projectDuration: 90,
    tracks: names.map((name, i) => ({ id: `track-${i}`, name, color: colors[i], gain: 1, pan: 0, mute: false, solo: false, timeBase: "linear" })),
    assets: names.map((name, i) => ({ id: `asset-${i}`, name: `${name}.wav`, sourcePath: `${name}.wav`, pcmPath: "", peaksPath: "", sampleRate: 48000, channels: 1, frames: 1440000, duration: 30, peakBinFrames: 1200, peakBins: 1200, originalSize: 0, originalModified: 0 })),
    clips: names.map((name, i) => ({ id: `clip-${i}`, trackId: `track-${i}`, assetId: `asset-${i}`, name: `${name}.wav`, start: 0, sourceStart: 0, duration: 30, groupId: "linked-stems" })),
  };
}

function IconButton({ label, children, active, disabled = false, onClick, className = "" }: {
  label: string; children: ReactNode; active?: boolean; disabled?: boolean; onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void; className?: string;
}) { return <button type="button" className={`d-icon ${active ? "is-on" : ""} ${className}`} title={label} aria-label={label} aria-pressed={active} disabled={disabled} onClick={onClick}>{children}</button>; }

function Waveform({ data, offset = 0, duration = 30 }: { data?: WaveData; offset?: number; duration?: number }) {
  const path = useMemo(() => {
    if (!data) return "";
    const first = Math.floor(offset / data.duration * data.peaks.length);
    const last = Math.max(first + 1, Math.ceil((offset + duration) / data.duration * data.peaks.length));
    const values = data.peaks.slice(first, last);
    // Fixed 4x waveform display magnification; source amplitudes and mix stay intact.
    const y = (amplitude: number) => Math.max(3, Math.min(77, 40 - amplitude * 160));
    return values.map((p, i) => `${i ? "L" : "M"}${i / Math.max(1, values.length - 1) * 1200},${y(p[1])}`).join("")
      + [...values].reverse().map((p, i) => `L${(values.length - 1 - i) / Math.max(1, values.length - 1) * 1200},${y(p[0])}`).join("") + "Z";
  }, [data, offset, duration]);
  return <svg className="d-wave" viewBox="0 0 1200 80" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="40" x2="1200" y2="40"/><path d={path}/></svg>;
}

function ContextMenu({ menu, close }: { menu: Menu; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: menu.x, top: menu.y });
  const [child, setChild] = useState<number | null>(null);
  const [childPosition, setChildPosition] = useState({ left: 0, top: 0 });
  const [focus, setFocus] = useState(-1);
  const childRef = useRef<HTMLDivElement>(null);
  const buttons = () => [...ref.current!.querySelectorAll<HTMLButtonElement>(":scope > button")];
  useLayoutEffect(() => {
    const rect = ref.current!.getBoundingClientRect();
    const left = menu.align === "right" ? menu.x - rect.width : menu.x;
    setPosition({ left: Math.max(8, Math.min(left, window.innerWidth - rect.width - 8)), top: Math.max(8, Math.min(menu.y, window.innerHeight - rect.height - 8)) });
    ref.current?.focus();
  }, [menu, menu.items[focus]?.disabled]);
  useLayoutEffect(() => {
    if (child === null || !childRef.current) return;
    const row = ref.current!.querySelector<HTMLButtonElement>(`[data-item="${child}"]`)!.getBoundingClientRect();
    const rect = childRef.current.getBoundingClientRect();
    setChildPosition({ left: row.right + rect.width + 8 <= window.innerWidth ? row.right + 3 : row.left - rect.width - 3,
      top: Math.max(8, Math.min(row.top - 5, window.innerHeight - rect.height - 8)) });
  }, [child]);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if ((event.target as HTMLElement).closest(".d-context")) return;
      close(); if (event.button === 0) { event.preventDefault(); event.stopPropagation(); }
    };
    const blur = () => close();
    document.addEventListener("pointerdown", dismiss, true);
    window.addEventListener("blur", blur); window.addEventListener("resize", blur);
    return () => { document.removeEventListener("pointerdown", dismiss, true); window.removeEventListener("blur", blur); window.removeEventListener("resize", blur); };
  }, [close]);
  const invoke = (item: MenuItem) => { if (item.disabled) return; close(); item.action?.(); };
  return <><div ref={ref} className="d-context" role="menu" aria-label={menu.title || "Actions"} tabIndex={-1} style={position}
    onContextMenu={e => e.preventDefault()} onKeyDown={event => {
      const rows = buttons(); const current = rows.indexOf(document.activeElement as HTMLButtonElement);
      if (event.key === "Escape") { event.preventDefault(); if (child !== null) setChild(null); else { close(); menu.invoker?.focus(); } return; }
      if (event.key === "Tab") { close(); return; }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? rows.length - 1 : current < 0 ? event.key === "ArrowDown" ? 0 : rows.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length;
        rows[next]?.focus(); setFocus(Number(rows[next]?.dataset.item)); return;
      }
      if (event.key === "ArrowRight" && current >= 0) { event.preventDefault(); const index = Number(rows[current].dataset.item); if (menu.items[index].child) setChild(index); }
      if (event.key === "ArrowLeft") { event.preventDefault(); setChild(null); }
      if (event.key === " ") { event.preventDefault(); rows[current]?.click(); }
      event.stopPropagation();
    }}>
    {menu.title && <div className="d-context-caption">{menu.title}</div>}
    {menu.items.map((item, i) => item.separator ? <div className="d-menu-separator" role="separator" key={`sep-${i}`}/> : <button
      key={item.label} data-item={i} role={item.check !== undefined ? "menuitemcheckbox" : "menuitem"} aria-checked={item.check} aria-disabled={!!item.disabled}
      className={`${item.danger ? "danger" : ""} ${focus === i ? "focused" : ""}`} tabIndex={-1}
      onPointerEnter={() => { setFocus(i); setChild(item.child ? i : null); }} onFocus={() => setFocus(i)}
      onClick={() => item.child ? setChild(child === i ? null : i) : invoke(item)} title={item.disabled}>
      <span className="d-menu-check">{item.check && <Check size={13}/>}</span><span>{item.label}</span>{item.child ? <ChevronRight size={14}/> : <kbd>{item.key}</kbd>}
    </button>)}
    {menu.items[focus]?.disabled && <div className="d-menu-reason">{menu.items[focus].disabled}</div>}
  </div>{child !== null && <div ref={childRef} className="d-context d-submenu" role="menu" style={childPosition}>
    {menu.items[child].child?.map(item => <button key={item.label} role="menuitemradio" aria-checked={item.check} aria-disabled={!!item.disabled}
      onClick={() => invoke(item)} onKeyDown={event => {
        if(event.key === "Escape" || event.key === "ArrowLeft") {event.preventDefault();setChild(null);buttons().find(b => Number(b.dataset.item) === child)?.focus();}
        if(event.key === "ArrowDown" || event.key === "ArrowUp") {event.preventDefault();const rows=[...childRef.current!.querySelectorAll<HTMLButtonElement>("button")];const i=rows.indexOf(event.currentTarget);rows[(i+(event.key==="ArrowDown"?1:-1)+rows.length)%rows.length]?.focus();}
      }}>
      <span className="d-menu-check">{item.check && <Check size={13}/>}</span><span>{item.label}</span><kbd>{item.key}</kbd>
    </button>)}
  </div>}</>;
}

function DesignReview() {
  const history = useRef(new ProjectHistory(fixture()));
  const [project, setProject] = useState(history.current.current);
  const [ids, setIds] = useState<string[]>(project.clips.map(c => c.id));
  const [trackId, setTrackId] = useState("track-0");
  const [kind, setKind] = useState<"audio" | "range" | "tempo" | "signature" | "none">("audio");
  const [mapId, setMapId] = useState("");
  const [range, setRange] = useState<TimeRange | null>(null);
  const [tool, setTool] = useState("object");
  const [linked, setLinked] = useState(true);
  const [snap, setSnap] = useState("beat");
  const [follow, setFollow] = useState(false);
  const [inspector, setInspector] = useState(true);
  const [maps, setMaps] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [cycle, setCycle] = useState(false);
  const [click, setClick] = useState(false);
  const [locators, setLocators] = useState({ start: 0, end: 0 });
  const [zoom, setZoom] = useState(12);
  const [left, setLeft] = useState(0);
  const [canvasWidth, setCanvasWidth] = useState(980);
  const [waveforms, setWaveforms] = useState<WaveData[]>([]);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [clipboard, setClipboard] = useState<AudioClipboard | null>(null);
  const [dialog, setDialog] = useState<"import" | "analysis" | "export" | "rename" | "addtrack" | "removetrack" | null>(null);
  const [lower, setLower] = useState(false);
  const [rename, setRename] = useState("");
  const [importMode, setImportMode] = useState<"stems"|"tracks"|"sequence">("stems");
  const [importTarget, setImportTarget] = useState<{ at:number; track:string|null }>({at:0,track:null});
  const [view, setView] = useState("proposal");
  const [scene, setScene] = useState<Scene>((query.get("scene") as Scene) || "linked");
  const [size, setSize] = useState("window");
  const [notice, setNotice] = useState("");
  const ruler = useRef<HTMLDivElement>(null);
  const rulerDrag = useRef(0);
  const body = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; initial: Project; ids: string[]; mode: "move" | "start" | "end"; delta: number } | null>(null);
  const rangeDrag = useRef<{ time: number; index: number } | null>(null);
  const lead = project.clips.find(c => c.id === ids[0]);
  const selectedTrack = project.tracks.find(t => t.id === trackId);
  const effective = relatedClips(project, ids, linked);
  const tempoPoint = project.tempos.find(point => point.id === mapId);
  const signaturePoint = project.signatures.find(point => point.id === mapId);
  const cursorQuarter = quarterAtTime(project, cursor);
  const cursorPosition = positionAtQuarter(project, cursorQuarter);
  const bpm = tempoAtQuarter(project, cursorQuarter).bpm;
  const signature = cursorPosition.signature;
  const sep: MenuItem = { label: "", separator: true };
  const commit = (next: Project, label: string) => setProject(history.current.commit(next, label));
  const notify = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(""), 5000); };
  const showImport = (at=cursor, track:string|null=null) => {setImportTarget({at,track});setDialog("import");};
  const importPreview = () => {
    const base=history.current.current;
    const assets=fixture().assets.map(asset=>({...asset,id:crypto.randomUUID()}));
    const next=importAssets(base,assets,{mode:importMode,copy:false,start:importTarget.at,targetTrackId:importMode==="sequence"?importTarget.track:null,beforeTrackId:null});
    const added=next.clips.filter(clip=>!base.clips.some(old=>old.id===clip.id));
    commit(next,"Import audio");setIds(added.map(clip=>clip.id));setTrackId(added[0]?.trackId||trackId);setKind("audio");setRange(null);setDialog(null);
  };
  useEffect(()=>{
    if(dialog==="analysis"||dialog==="export"){
      setDialog(null);notify("분석·내보내기 상세 창은 기존 BPMTracker 화면에 연결합니다. 이번 검토에서는 메인 화면과 우클릭 구성을 확인할 수 있습니다.");
    }
  },[dialog]);
  const updateTrack = (patch: Partial<NonNullable<typeof selectedTrack>>, id = trackId, preview = false) => {
    const next = { ...(preview ? project : history.current.current), tracks: (preview ? project : history.current.current).tracks.map(t => t.id === id ? { ...t, ...patch } : t) };
    preview ? setProject(next) : commit(next, "Track controls");
  };
  const reset = (nextScene: Scene = "linked") => {
    let next = fixture();
    if (nextScene === "empty") next = { ...next, tracks: [], clips: [], assets: [], name: "Untitled project" };
    if (nextScene === "tempo") next = putTempo(next, { id: "review-tempo", quarter: 32, bpm: 128, origin: "manual" });
    if (nextScene === "signature") next = putSignature(next, { id: "review-signature", bar: 9, numerator: 3, denominator: 4, origin: "manual" });
    history.current.replace(next); setProject(next); setMenu(null); setDialog(null); setNotice("");
    setScene(nextScene); setTrackId("track-0"); setPlaying(false); setCursor(0); setLocators({ start: 0, end: 0 });
    setZoom(12); setLeft(0); setLinked(nextScene !== "single"); setMaps(true); setInspector(true); setLower(false); setClipboard(null);
    setIds(nextScene === "linked" ? next.clips.map(c => c.id) : nextScene === "single" ? ["clip-0"] : []);
    setKind(nextScene === "linked" || nextScene === "single" ? "audio" : nextScene === "empty" ? "none" : nextScene);
    setMapId(nextScene === "tempo" ? "review-tempo" : nextScene === "signature" ? "review-signature" : "");
    setTool(nextScene === "range" ? "range" : "object");
    setRange(nextScene === "range" ? { start: 8, end: 16, trackIds: next.tracks.map(t => t.id) } : null);
  };
  useEffect(() => { fetch(ASSETS + "waveforms.json").then(r => r.json()).then(setWaveforms); reset(scene); }, []);
  useEffect(() => {
    if (!ruler.current) return;
    const observer = new ResizeObserver(entries => setCanvasWidth(entries[0].contentRect.width));
    observer.observe(ruler.current); return () => observer.disconnect();
  }, [view, inspector, size]);
  useEffect(() => {
    if (!playing) return;
    const start = performance.now(); const initial = cursor;
    const timer = window.setInterval(() => setCursor(Math.max(0, initial + (performance.now() - start) / 1000)), 40);
    return () => window.clearInterval(timer);
  }, [playing]);
  useEffect(()=>{if(playing&&follow&&(cursor-left)*zoom>canvasWidth*.85)setLeft(Math.max(0,cursor-canvasWidth*.3/zoom));},[cursor,playing,follow,zoom,canvasWidth,left]);
  const snapped = (time: number) => snapTime(project, Math.max(0,time), snap as "off"|"beat"|"bar");
  const pointerTime = (x: number, offset=0) => Math.max(0, left + (x - ruler.current!.getBoundingClientRect().left) / zoom + offset);
  const fit = () => { setZoom((canvasWidth - 28) / Math.max(1, ...project.clips.map(c => c.start + c.duration))); setLeft(0); };
  const editGeometry = (value: number, mode: "start" | "end" | "length", preview = false) => {
    if (!lead) return;
    const base = history.current.current, original = base.clips.find(c => c.id === lead.id)!;
    const next = mode === "start" ? moveClips(base, ids, value - original.start, linked)
      : trimClips(base, ids, "end", value - (mode === "length" ? original.duration : original.start + original.duration), linked);
    preview ? setProject(next) : commit(next, mode === "start" ? "Move events" : "Trim events");
  };
  const paste = (at: number, target: string | null) => {
    if (!clipboard) return; const result = pasteAudio(history.current.current, clipboard, at, target);
    commit(result.project, "Paste audio"); setIds(result.ids); setRange(result.range); setKind(result.range ? "range" : "audio");
  };
  const clipboardCopy = (selected = ids, activeRange = kind === "range" ? range : null) => setClipboard(copyAudio(history.current.current, selected, activeRange, linked));
  const eventMenu = (x: number, y: number, clipId: string, invoker?: HTMLElement) => {
    const clip = project.clips.find(c => c.id === clipId)!;
    const selected = ids.includes(clipId) && kind === "audio" ? ids : [clipId];
    if (!ids.includes(clipId) || kind !== "audio") { setIds(selected); setKind("audio"); setRange(null); }
    setTrackId(clip.trackId);
    const selectedEvents = relatedClips(project, selected, linked);
    const at = snapped(pointerTime(x)); const heldCursor = cursor;
    const start = Math.min(...selectedEvents.map(c => c.start)); const end = Math.max(...selectedEvents.map(c => c.start + c.duration));
    const within = (time: number) => selectedEvents.some(c => time > c.start && time < c.start + c.duration);
    setMenu({ x, y, invoker, title: `${selectedEvents.length === 1 ? clip.name : `${selectedEvents.length} ${linked ? "linked " : ""}events`}`, items: [
      { label: "Cut", key: "Ctrl+X", action: () => { clipboardCopy(selected, null); commit(removeClips(history.current.current, selected, linked), "Cut events"); setIds([]); setKind("none"); } },
      { label: "Copy", key: "Ctrl+C", action: () => clipboardCopy(selected, null) },
      { label: "Paste", key: "Ctrl+V", disabled: !clipboard ? "No copied audio" : undefined, action: () => paste(heldCursor, clip.trackId) }, sep,
      { label: "Duplicate", key: "Ctrl+D", action: () => { const copied = copyAudio(history.current.current, selected, null, linked); if(copied) {const result = pasteAudio(history.current.current, copied, end, clip.trackId);commit(result.project,"Duplicate events");setIds(result.ids);} } },
      { label: "Split Here", disabled: !within(at) ? "Pointer is outside the selected events" : undefined, action: () => commit(splitClips(history.current.current, selected, at, linked), "Split events") },
      { label: "Split at Cursor", key: "Alt+X", disabled: !within(heldCursor) ? "Cursor is outside the selected events" : undefined, action: () => commit(splitClips(history.current.current, selected, heldCursor, linked), "Split events") }, sep,
      { label: "Analyze Audio…", action: () => setDialog("analysis") },
      { label: "Locators to Selection", key: "P", action: () => setLocators({ start, end }) },
      { label: "Open Audio Editor", key: "Ctrl+E", action: () => setLower(true) }, sep,
      { label: "Delete Events", key: "Delete", danger: true, action: () => {commit(removeClips(history.current.current, selected, linked), "Delete events");setIds([]);setKind("none");} },
    ] });
  };
  const trackMenu = (x: number, y: number, id: string, invoker?: HTMLElement) => {
    setTrackId(id); const track = project.tracks.find(t => t.id === id)!; const index = project.tracks.indexOf(track);
    const reorder = (delta: number) => {const next = [...history.current.current.tracks]; [next[index],next[index+delta]]=[next[index+delta],next[index]];commit({...history.current.current,tracks:next},"Move track");};
    setMenu({ x, y, invoker, title: track.name, items: [
      { label: "Select All Events", action: () => { setIds(project.clips.filter(c => c.trackId === id).map(c => c.id));setKind("audio");setRange(null); } },
      { label: "Duplicate Track", action: () => commit(duplicateTracks(history.current.current,[id]),"Duplicate track") },
      { label: "Rename…", action: () => {setRename(track.name);setDialog("rename");} }, sep,
      { label: "Move Up", disabled: index === 0 ? "Track is already first" : undefined, action: () => reorder(-1) },
      { label: "Move Down", disabled: index === project.tracks.length-1 ? "Track is already last" : undefined, action: () => reorder(1) },
      { label: "Time Base", child: [
        { label: "Linear", check: track.timeBase === "linear", action: () => commit(setTrackTimeBase(history.current.current,id,"linear"),"Track time base") },
        { label: "Musical", check: track.timeBase === "musical", action: () => commit(setTrackTimeBase(history.current.current,id,"musical"),"Track time base") },
      ] }, sep,
      { label: "Remove Track…", danger: true, action: () => setDialog("removetrack") },
    ] });
  };
  const laneMenu = (x: number, y: number, id: string) => {
    const at = snapped(pointerTime(x));
    if (range && range.trackIds.includes(id) && at >= range.start && at <= range.end) {
      const heldRange = structuredClone(range);setKind("range");setMenu({x,y,title:`Range · ${range.trackIds.length} tracks`,items:[
        {label:"Copy Range",key:"Ctrl+C",action:()=>clipboardCopy([],heldRange)},
        {label:"Paste",key:"Ctrl+V",disabled:!clipboard?"No copied audio":undefined,action:()=>paste(cursor,id)},sep,
        {label:"Split at Range Edges",key:"Shift+X",action:()=>{const selected=project.clips.filter(c=>heldRange.trackIds.includes(c.trackId)).map(c=>c.id);commit(splitClips(splitClips(history.current.current,selected,heldRange.start,linked),selected,heldRange.end,linked),"Split range edges");}},
        {label:"Analyze Range…",action:()=>setDialog("analysis")},
        {label:"Locators to Range",key:"P",action:()=>setLocators({start:heldRange.start,end:heldRange.end})},
      ]});return;
    }
    setMenu({x,y,title:`${project.tracks.find(t=>t.id===id)?.name} · ${at.toFixed(3)} s`,items:[
      {label:"Paste Here",disabled:!clipboard?"No copied audio":undefined,action:()=>paste(at,id)},
      {label:"Import Audio Here…",action:()=>showImport(at,id)},sep,
      {label:"Add Audio Track…",action:()=>setDialog("addtrack")},
      {label:"Show Tempo / Signature",check:maps,action:()=>setMaps(!maps)},
    ]});
  };
  const rulerMenu = (x: number,y: number) => {const at=snapped(pointerTime(x));setMenu({x,y,title:"Ruler",items:[
    {label:"Move Cursor Here",action:()=>setCursor(at)},sep,
    {label:"Set Left Locator Here",action:()=>setLocators({start:at,end:Math.max(at,locators.end)})},
    {label:"Set Right Locator Here",action:()=>setLocators({start:Math.min(at,locators.start),end:at})},
    {label:"Cycle",key:"Num /",check:cycle,action:()=>setCycle(!cycle)},sep,
    {label:"Show Tempo / Signature",check:maps,action:()=>setMaps(!maps)},
  ]});};
  const setFooterTempo = (value:number,heldCursor:number) => commit(putTempo(history.current.current,{id:crypto.randomUUID(),quarter:quarterAtTime(history.current.current,heldCursor),bpm:value,origin:"manual"}),"Tempo at cursor");
  const topMenu = (name:string,button:HTMLButtonElement) => {
    const rect=button.getBoundingClientRect();let items:MenuItem[]=[];
    if(name==="File")items=[{label:"New Project",key:"Ctrl+N",action:()=>reset("empty")},{label:"Open…",key:"Ctrl+O",action:()=>notify("프로젝트 열기는 현재 BPMTracker의 기존 파일 선택 창을 유지합니다.")},sep,{label:"Save",key:"Ctrl+S",action:()=>notify("이 시안의 편집은 임시 메모리에만 보관됩니다. 실제 프로젝트 저장은 기존 BPMTracker에 연결합니다.")},{label:"Save As…",key:"Ctrl+Shift+S",action:()=>notify("실제 프로젝트 저장은 기존 BPMTracker의 Save As 화면에 연결합니다.")},sep,{label:"Import Audio…",action:()=>showImport()},{label:"Export…",action:()=>setDialog("export")}];
    else if(name==="Edit")items=[{label:"Undo",key:"Ctrl+Z",disabled:!history.current.undoLabel?"Nothing to undo":undefined,action:()=>setProject(history.current.undo())},{label:"Redo",key:"Ctrl+Y",disabled:!history.current.redoLabel?"Nothing to redo":undefined,action:()=>setProject(history.current.redo())},sep,{label:"Copy",key:"Ctrl+C",disabled:!lead&&!range?"Select audio or a range":undefined,action:()=>clipboardCopy()},{label:"Paste",key:"Ctrl+V",disabled:!clipboard?"No copied audio":undefined,action:()=>paste(cursor,trackId)}];
    else if(name==="View")items=[{label:"Inspector",check:inspector,action:()=>setInspector(!inspector)},{label:"Tempo / Signature",check:maps,action:()=>setMaps(!maps)},{label:"Audio Editor",check:lower,action:()=>setLower(!lower)},sep,{label:"Zoom to Project",action:fit},{label:"Restore Layout",action:()=>{setInspector(true);setMaps(true);setLower(false);}}];
    else if(name==="Audio")items=[{label:"Import Audio…",action:()=>showImport()},{label:"Analyze Audio…",disabled:!lead&&!range?"Select an audio event or range":undefined,action:()=>setDialog("analysis")},{label:"Export…",action:()=>setDialog("export")}];
    else if(name==="Transport")items=[{label:playing?"Stop":"Start",key:"Space",action:()=>setPlaying(!playing)},{label:"Return to Start",action:()=>setCursor(0)},{label:"Cycle",check:cycle,action:()=>setCycle(!cycle)},{label:"Metronome",check:click,action:()=>setClick(!click)}];
    else items=[{label:name==="Samples"?"Open candidate review…":"Project Settings…",action:()=>notify("이 명령은 현재 BPMTracker의 기존 화면을 유지합니다. 이번 시안은 메인 작업 화면과 우클릭을 검토합니다.")}];
    setMenu({x:rect.left,y:rect.bottom,items,invoker:button});
  };
  useEffect(() => {
    const listener=(event:KeyboardEvent)=>{
      if(menu||dialog||(event.target as HTMLElement).closest("input,textarea,select,button,[role=slider]"))return;
      if(event.key==="Escape"){if(drag.current){setProject(drag.current.initial);drag.current=null;}else{setRange(null);setKind("none");setIds([]);}return;}
      if(event.key===" "){event.preventDefault();setPlaying(v=>!v);}
      if(event.key==="1")setTool("object");if(event.key==="2")setTool("range");if(event.key==="3")setTool("split");if(event.key==="5")setTool("erase");
      if(event.ctrlKey&&event.key.toLowerCase()==="z"){event.preventDefault();setProject(history.current.undo());}
      if(event.ctrlKey&&event.key.toLowerCase()==="y"){event.preventDefault();setProject(history.current.redo());}
      if(event.ctrlKey&&event.key.toLowerCase()==="c"){event.preventDefault();clipboardCopy();}
      if(event.ctrlKey&&event.key.toLowerCase()==="v"){event.preventDefault();paste(cursor,trackId);}
      if(event.key.toLowerCase()==="p"&&!event.ctrlKey){event.preventDefault();if(range&&kind==="range")setLocators({start:range.start,end:range.end});else if(effective.length)setLocators({start:Math.min(...effective.map(c=>c.start)),end:Math.max(...effective.map(c=>c.start+c.duration))});}
      if(event.ctrlKey&&event.key.toLowerCase()==="d"&&lead){event.preventDefault();const data=copyAudio(history.current.current,ids,null,linked);if(data){const result=pasteAudio(history.current.current,data,Math.max(...effective.map(c=>c.start+c.duration)),lead.trackId);commit(result.project,"Duplicate events");setIds(result.ids);}}
      if(event.altKey&&event.key.toLowerCase()==="x"&&lead){event.preventDefault();commit(splitClips(history.current.current,ids,cursor,linked),"Split events");}
      if(event.key==="Delete"&&lead){event.preventDefault();commit(removeClips(history.current.current,ids,linked),"Delete events");setIds([]);setKind("none");}
      if(event.shiftKey&&event.key==="F10"&&lead){event.preventDefault();const node=document.querySelector<HTMLElement>(`[data-clip="${lead.id}"]`);const rect=node?.getBoundingClientRect();if(rect)eventMenu(rect.left+20,rect.top+20,lead.id,node!);}
    };window.addEventListener("keydown",listener);return()=>window.removeEventListener("keydown",listener);
  });
  const areaContext=(event:React.MouseEvent<HTMLElement>)=>{
    const slider=(event.target as HTMLElement).closest<HTMLElement>("[role=slider]");
    if(slider){event.preventDefault();const label=slider.getAttribute("aria-label")||"Value";setMenu({x:event.clientX,y:event.clientY,title:label,invoker:slider,items:[
      {label:label.includes("pan")?"Reset to Center":"Reset to 0 dB",action:()=>label.includes("Output")?commit({...history.current.current,masterGain:1},"Output volume"):updateTrack(label.includes("pan")?{pan:0}:{gain:1})},
    ]});return;}
    const target=(event.target as HTMLElement).closest<HTMLInputElement>(".value-control > input");
    if(!target||!target.readOnly)return;
    event.preventDefault();event.stopPropagation();
    setMenu({x:event.clientX,y:event.clientY,title:target.getAttribute("aria-label")||"Value",invoker:target,items:[
      {label:"Edit Value…",action:()=>target.dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))},
      {label:"Copy Exact Value",action:()=>target.dispatchEvent(new KeyboardEvent("keydown",{key:"c",code:"KeyC",ctrlKey:true,bubbles:true}))},
      {label:"Paste Value",action:()=>{navigator.clipboard.readText().then(text=>{if(!target.isConnected)return;target.dispatchEvent(new MouseEvent("dblclick",{bubbles:true}));const data=new DataTransfer();data.setData("text/plain",text);target.dispatchEvent(new ClipboardEvent("paste",{clipboardData:data,bubbles:true}));});}},
    ]});
  };
  const mapMenu=(event:React.MouseEvent,id:string,type:"tempo"|"signature")=>{
    event.preventDefault();event.stopPropagation();setMapId(id);setKind(type);setIds([]);setRange(null);
    setMenu({x:event.clientX,y:event.clientY,title:type==="tempo"?"Tempo point":"Signature point",items:[
      {label:"Edit Properties",action:()=>document.querySelector<HTMLInputElement>(".d-info input")?.focus()},sep,
      {label:type==="tempo"?"Delete Tempo Point":"Delete Signature Point",key:"Delete",danger:true,action:()=>{commit({...history.current.current,[type==="tempo"?"tempos":"signatures"]:history.current.current[type==="tempo"?"tempos":"signatures"].filter(p=>p.id!==id)},"Delete map point");setKind("none");}},
    ]});
  };
  const barWidth=240/bpm*zoom;
  const labelStep=barWidth<40?2:1;
  const firstBar=positionAtQuarter(project,quarterAtTime(project,left)).bar;
  const bars:Array<{bar:number;x:number;beats:number;end:number}>=[];
  for(let bar=firstBar;bar<firstBar+180;bar++){
    const time=timeAtBar(project,bar),next=timeAtBar(project,bar+1);
    if(time>left+canvasWidth/zoom+4)break;
    bars.push({bar,x:(time-left)*zoom,beats:positionAtQuarter(project,quarterAtTime(project,time)).signature.numerator,end:(next-left)*zoom});
  }
  const grid=<div className="d-grid" aria-hidden="true">{bars.flatMap(bar=>[
    <i className="bar" key={`bar-${bar.bar}`} style={{left:bar.x}}/>,
    ...Array.from({length:(bar.end-bar.x)/bar.beats>=10?bar.beats-1:0},(_,i)=><i key={`beat-${bar.bar}-${i}`} style={{left:bar.x+(bar.end-bar.x)*(i+1)/bar.beats}}/>),
  ])}</div>;
  const tempoValues=[project.bpm,...project.tempos.map(point=>point.bpm)];
  const tempoMin=Math.min(...tempoValues),tempoMax=Math.max(...tempoValues);
  const tempoY=(value:number)=>tempoMin===tempoMax?34:34-(value-tempoMin)/(tempoMax-tempoMin)*22;
  let tempoCurve=`M0,${tempoY(tempoAtQuarter(project,quarterAtTime(project,left)).bpm)}`;
  let lastTempo=tempoAtQuarter(project,quarterAtTime(project,left)).bpm;
  for(const point of [...project.tempos].sort((a,b)=>a.quarter-b.quarter)){
    const x=(timeAtQuarter(project,point.quarter)-left)*zoom;
    if(x<0||x>canvasWidth)continue;
    tempoCurve+=`L${x},${tempoY(lastTempo)}L${x},${tempoY(point.bpm)}`;lastTempo=point.bpm;
  }
  tempoCurve+=`L${canvasWidth},${tempoY(lastTempo)}`;
  const timelineStyle={"--bar-px":`${barWidth}px`,"--beat-px":`${barWidth/4}px`,"--grid-offset":`${-left*zoom}px`} as CSSProperties;
  const info = kind === "audio" && lead ? <>
    <div className="d-info-name"><span>Event</span><div><AudioLines size={14}/><b title={lead.name}>{lead.name}</b>{effective.length>1&&<span className="d-selection-count" title={`${effective.length} ${linked&&lead.groupId?"linked ":""}events · relative edit`} aria-label={`${effective.length} selected events`}>{linked&&lead.groupId?<Link2 size={13}/>:<Layers size={13}/>}<span>{effective.length}</span></span>}</div></div>
    <TimeField project={project} label="Event start" caption="Start" value={lead.start} onChange={v=>editGeometry(v,"start")} onPreview={v=>editGeometry(v,"start",true)}/>
    <TimeField project={project} label="Event end" caption="End" value={lead.start+lead.duration} onChange={v=>editGeometry(v,"end")} onPreview={v=>editGeometry(v,"end",true)}/>
    <label className="d-scalar d-duration"><span>Length</span><ValueField label="Event length" value={lead.duration} min={.001} step={.001} format={v=>`${v.toFixed(3)} s`} onChange={v=>editGeometry(v,"length")} onPreview={v=>editGeometry(v,"length",true)}/></label>
    <div className="d-info-source"><span>Source In</span><div><b>{lead.sourceStart.toFixed(3)}</b><small>s</small></div></div>
  </> : kind === "range" && range ? <>
    <div className="d-info-name"><span>Range</span><div><StretchHorizontal size={14}/><b>{range.trackIds.length} tracks</b></div></div>
    <TimeField project={project} label="Range start" caption="Start" value={range.start} max={range.end-.001} onChange={v=>setRange({...range,start:v})}/>
    <TimeField project={project} label="Range end" caption="End" value={range.end} min={range.start+.001} onChange={v=>setRange({...range,end:v})}/>
    <label className="d-scalar d-duration"><span>Length</span><ValueField label="Range length" value={range.end-range.start} min={.001} step={.001} format={v=>`${v.toFixed(3)} s`} onChange={v=>setRange({...range,end:range.start+v})}/></label>
  </> : kind === "tempo" && tempoPoint ? <>
    <div className="d-info-name d-object-title"><div><AudioLines size={15}/><b>Tempo</b></div></div>
    <TimeField project={project} label="Tempo position" caption="Position" value={timeAtQuarter(project,tempoPoint.quarter)} onChange={v=>commit(putTempo(history.current.current,{...tempoPoint,quarter:quarterAtTime(project,v)}),"Move tempo point")}/>
    <label className="d-scalar"><span>BPM</span><ValueField label="Tempo point BPM" value={tempoPoint.bpm} format={v=>v.toFixed(3)} min={1} max={999} step={1} adjust={(v,n)=>Math.round(v)+n} onChange={v=>commit(putTempo(history.current.current,{...tempoPoint,bpm:v}),"Edit tempo point")}/></label>
  </> : kind === "signature" && signaturePoint ? <>
    <div className="d-info-name d-object-title"><div><Music2 size={15}/><b>Signature</b></div></div>
    <TimeField project={project} label="Signature position" caption="Position" value={timeAtBar(project,signaturePoint.bar)} barStartOnly onChange={v=>commit(putSignature(history.current.current,{...signaturePoint,bar:positionAtQuarter(project,quarterAtTime(project,v)).bar}),"Move signature")}/>
    <label className="d-scalar"><span>Signature</span><ValueField label="Signature point numerator" value={signaturePoint.numerator} min={1} max={32} step={1} onChange={v=>commit(putSignature(history.current.current,{...signaturePoint,numerator:Math.round(v)}),"Edit signature")}/><b className="d-signature-slash">/ {signaturePoint.denominator}</b></label>
  </> : <div className="d-info-empty">{project.tracks.length?"No selection":""}</div>;

  const app = <div className={`d-app ${!inspector?"without-inspector":""}`} onContextMenu={areaContext}>
    <header className="d-title"><Waves size={18}/><b>BPMTRACKER</b><span className="d-title-divider"/><span>{project.name}.bpmtracker{history.current.undoLabel?" *":""}</span><div className="d-window-controls" aria-hidden="true"><Minus size={13}/><Square size={10}/><X size={14}/></div></header>
    <nav className="d-menubar" aria-label="Menu bar">{["File","Edit","Project","Audio","Transport","View","Samples","Help"].map(name=><button key={name} onClick={e=>topMenu(name,e.currentTarget)}>{name}</button>)}</nav>
    <section className="d-toolbar" aria-label="Project toolbar">
      <div className="d-tool-group"><IconButton label="Undo (Ctrl+Z)" disabled={!history.current.undoLabel} onClick={()=>setProject(history.current.undo())}><Undo2/></IconButton><IconButton label="Redo (Ctrl+Y)" disabled={!history.current.redoLabel} onClick={()=>setProject(history.current.redo())}><Redo2/></IconButton></div>
      <span className="d-divider"/>
      <div className="d-tool-group d-tools">{[["object",MousePointer2,"Object Selection (1)"],["range",StretchHorizontal,"Range Selection (2)"],["split",Scissors,"Split (3)"],["erase",Trash2,"Erase (5)"]].map(([id,Icon,label])=><IconButton key={id as string} label={label as string} active={tool===id} onClick={()=>setTool(id as string)}>{typeof Icon!=="string"&&<Icon/>}</IconButton>)}</div>
      <span className="d-divider"/>
      <div className="d-tool-group"><IconButton label="Snap on/off" active={snap!=="off"} onClick={()=>setSnap(snap==="off"?"beat":"off")}><Magnet/></IconButton><select aria-label="Snap grid" value={snap} onChange={e=>setSnap(e.target.value)}><option value="off">Off</option><option value="beat">Beat</option><option value="bar">Bar</option></select></div>
      <span className="d-divider"/>
      <IconButton label="Linked edits" active={linked} onClick={()=>setLinked(!linked)}><Link2/></IconButton>
      <IconButton label="Follow playback cursor" active={follow} onClick={()=>setFollow(!follow)}><ArrowRightToLine/></IconButton>
      <div className="d-toolbar-space"/>
      <IconButton label="Import Audio" onClick={()=>showImport()}><FolderOpen/></IconButton>
      <button className="d-analyze" aria-label="Analyze Audio" disabled={!lead&&!range} onClick={()=>setDialog("analysis")}><AudioLines size={16}/>Analyze</button>
      <IconButton label="Export" onClick={()=>setDialog("export")}><Download/></IconButton>
      <span className="d-divider"/>
      <IconButton label="Show/Hide Inspector" active={inspector} onClick={()=>setInspector(!inspector)}><PanelLeft/></IconButton>
      <IconButton label="Show/Hide Tempo and Signature" active={maps} onClick={()=>setMaps(!maps)}><Music2/></IconButton>
    </section>
    <section className={`d-info ${effective.length>1&&kind==="audio"?"relative":""}`} aria-label="Info Line">{info}</section>
    <main className="d-workspace">
      {inspector&&<aside className="d-inspector" aria-label="Inspector"><div className="d-pane-heading"><b>Inspector</b><IconButton label="Close Inspector" onClick={()=>setInspector(false)}><PanelLeft size={13}/></IconButton></div>
        {selectedTrack?<>
          <div className="d-inspector-track" style={{"--track-color":selectedTrack.color} as CSSProperties}><AudioLines size={17}/><b title={selectedTrack.name}>{selectedTrack.name}</b><button title="Track actions" aria-label="Inspector track actions" onClick={e=>{const r=e.currentTarget.getBoundingClientRect();trackMenu(r.left,r.bottom,trackId,e.currentTarget);}}><Ellipsis size={16}/></button></div>
          <div className="d-channel">
            <div className="d-channel-state"><button className={selectedTrack.mute?"is-mute":""} aria-label="Mute focused track" aria-pressed={selectedTrack.mute} onClick={()=>updateTrack({mute:!selectedTrack.mute})}>M</button><button className={selectedTrack.solo?"is-solo":""} aria-label="Solo focused track" aria-pressed={selectedTrack.solo} onClick={()=>updateTrack({solo:!selectedTrack.solo})}>S</button><label className="d-timebase" title="Track time base">{selectedTrack.timeBase==="linear"?<Clock3 size={13}/>:<Music2 size={13}/>}<select aria-label="Focused track time base" value={selectedTrack.timeBase} onChange={e=>commit(setTrackTimeBase(history.current.current,trackId,e.target.value as "linear"|"musical"),"Track time base")}><option value="linear">Linear</option><option value="musical">Musical</option></select></label></div>
            <div className="d-mix-row"><span>Volume</span><VolumeFader key={`volume-${trackId}`} label="Focused track volume" gain={selectedTrack.gain} horizontal onPreview={v=>updateTrack({gain:v},trackId,true)} onCommit={v=>updateTrack({gain:v})}/><GainField gain={selectedTrack.gain} label="Focused track volume dB" onChange={v=>updateTrack({gain:v})}/></div>
            <div className="d-mix-row"><span>Pan</span><PanFader key={`pan-${trackId}`} label="Focused track pan" value={selectedTrack.pan} onPreview={v=>updateTrack({pan:v},trackId,true)} onCommit={v=>updateTrack({pan:v})}/><ValueField label="Focused track pan value" value={selectedTrack.pan} min={-100} max={100} step={1} format={v=>v===0?"C":v<0?`L${Math.abs(v)}`:`R${v}`} inputFormat={String} onChange={v=>updateTrack({pan:v})}/></div>
          </div>
          <details className="d-fold"><summary>Event</summary><div className="d-fold-body"><span>Event</span><b>{lead?.name||"No event selected"}</b>{lead&&<><span>Source</span><b>{project.assets.find(a=>a.id===lead.assetId)?.name}</b><span>In</span><b>{lead.sourceStart.toFixed(3)} s</b><span>Format</span><b>48 kHz · mono · PCM16</b></>}</div></details>
          <details className="d-fold"><summary>Analysis</summary><div className="d-fold-body"><span>Event</span><b>{lead?.name||"—"}</b><p>{lead?"No analysis":"No event selected"}</p></div></details>
          {(kind==="tempo"||kind==="signature")&&<div className="d-map-inspector"><b>{kind==="tempo"?"Tempo points":"Signature points"}</b>{(kind==="tempo"?project.tempos:project.signatures).map(point=><button key={point.id} className={point.id===mapId?"selected":""} onClick={()=>setMapId(point.id)}><span>{"quarter"in point?`${(point.quarter/4+1).toFixed(0)}.1.1.0`:`${point.bar}.1.1.0`}</span><b>{"bpm"in point?point.bpm.toFixed(3):`${point.numerator}/${point.denominator}`}</b></button>)}</div>}
        </>:<div className="d-inspector-empty"><FileAudio size={24}/><b>No track</b></div>}
      </aside>}
      <div className="d-pane-divider"/>
      <section className="d-arrangement" aria-label="Arrangement">
        <div className="d-arrangement-head"><div className="d-tracks-heading"><b>Tracks</b><span>{project.tracks.length}</span><IconButton label="Add Audio Track" onClick={()=>setDialog("addtrack")}><Plus size={15}/></IconButton></div>
          <div className="d-ruler" ref={ruler} style={timelineStyle} onContextMenu={e=>{e.preventDefault();rulerMenu(e.clientX,e.clientY);}}
            onPointerDown={e=>{if(e.button!==0)return;e.preventDefault();const raw=left+(e.clientX-e.currentTarget.getBoundingClientRect().left)/zoom;rulerDrag.current=(e.target as HTMLElement).closest(".d-ruler-cursor")?cursor-raw:0;setCursor(snapped(pointerTime(e.clientX,rulerDrag.current)));e.currentTarget.setPointerCapture(e.pointerId);}}
            onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))setCursor(snapped(pointerTime(e.clientX,rulerDrag.current)));}}
            onPointerUp={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}>
            {bars.filter(bar=>(bar.bar-1)%labelStep===0).map(bar=><span key={bar.bar} className="d-ruler-label" style={{left:bar.x}}>{bar.bar}</span>)}
            {locators.end>locators.start&&<div className={`d-cycle-region ${cycle?"on":""}`} style={{left:(locators.start-left)*zoom,width:(locators.end-locators.start)*zoom}}/>}
            <div className="d-ruler-cursor" style={{left:Math.round((cursor-left)*zoom)}}><i/></div>
          </div>
        </div>
        <div className="d-lanes" ref={body} style={timelineStyle}>
          {maps&&<>
            <div className="d-lane d-tempo-lane"><div className="d-map-header"><span className="d-map-index"/><AudioLines size={14}/><b>Tempo</b></div><div className="d-lane-canvas d-map-canvas" onContextMenu={e=>{e.preventDefault();const at=snapped(pointerTime(e.clientX));setMenu({x:e.clientX,y:e.clientY,title:"Tempo lane",items:[{label:"Add Tempo Here…",action:()=>{const id=crypto.randomUUID();commit(putTempo(history.current.current,{id,quarter:quarterAtTime(project,at),bpm,origin:"manual"}),"Add tempo");setKind("tempo");setMapId(id);setIds([]);}},sep,{label:"Hide Tempo / Signature",action:()=>setMaps(false)}]});}}>
              {grid}<svg className="d-tempo-curve" viewBox={`0 0 ${canvasWidth} 48`} preserveAspectRatio="none" aria-hidden="true"><path d={tempoCurve}/></svg>{!project.tempos.length&&<span className="d-map-base d-tempo-base">{project.bpm.toFixed(3)}</span>}
              {project.tempos.map(point=><button key={point.id} className={`d-tempo-point ${kind==="tempo"&&point.id===mapId?"selected":""}`} style={{left:(timeAtQuarter(project,point.quarter)-left)*zoom,top:Math.max(2,tempoY(point.bpm)-9)}} onClick={()=>{setKind("tempo");setMapId(point.id);setIds([]);}} onContextMenu={e=>mapMenu(e,point.id,"tempo")}><i/>{point.bpm.toFixed(3)}</button>)}
            </div></div>
            <div className="d-lane d-signature-lane"><div className="d-map-header"><span className="d-map-index"/><span className="d-sharp">♯</span><b>Signature</b></div><div className="d-lane-canvas d-map-canvas" onContextMenu={e=>{e.preventDefault();const at=pointerTime(e.clientX),bar=positionAtQuarter(project,quarterAtTime(project,at)).bar;setMenu({x:e.clientX,y:e.clientY,title:`Signature · bar ${bar}`,items:[{label:"Add Signature at Bar Start…",action:()=>{const id=crypto.randomUUID();commit(putSignature(history.current.current,{id,bar,...signature,origin:"manual"}),"Add signature");setKind("signature");setMapId(id);setIds([]);}}]});}}>{grid}<span className="d-map-base">{project.signature.numerator}/{project.signature.denominator}</span>{project.signatures.map(point=><button key={point.id} className={`d-signature-point ${kind==="signature"&&point.id===mapId?"selected":""}`} style={{left:(timeAtBar(project,point.bar)-left)*zoom}} onClick={()=>{setKind("signature");setMapId(point.id);setIds([]);}} onContextMenu={e=>mapMenu(e,point.id,"signature")}>{point.numerator}/{point.denominator}</button>)}</div></div>
          </>}
          {project.tracks.map((track,index)=><div className="d-lane d-audio-lane" key={track.id} style={{"--track-color":track.color} as CSSProperties}>
            <div className={`d-track-header ${trackId===track.id?"selected":""}`} tabIndex={0} aria-label={`${track.name} track`} onClick={()=>setTrackId(track.id)} onContextMenu={e=>{e.preventDefault();trackMenu(e.clientX,e.clientY,track.id,e.currentTarget);}}>
              <div className="d-track-name"><span>{String(index+1).padStart(2,"0")}</span><AudioLines size={15}/><b>{track.name}</b><button aria-label={`${track.name} track actions`} onClick={e=>{e.stopPropagation();const rect=e.currentTarget.getBoundingClientRect();trackMenu(rect.left,rect.bottom,track.id,e.currentTarget);}}><Ellipsis size={15}/></button></div>
              <div className="d-track-controls"><span className="d-track-base" title={track.timeBase==="linear"?"Linear: fixed time":"Musical: follows tempo"}>{track.timeBase==="linear"?<Clock3 size={14}/>:<Music2 size={14}/>}</span><button aria-label={`Mute ${track.name}`} aria-pressed={track.mute} className={track.mute?"is-mute":""} onClick={e=>{e.stopPropagation();updateTrack({mute:!track.mute},track.id);}}>M</button><button aria-label={`Solo ${track.name}`} aria-pressed={track.solo} className={track.solo?"is-solo":""} onClick={e=>{e.stopPropagation();updateTrack({solo:!track.solo},track.id);}}>S</button><span className="d-track-db">{track.gain>0?(20*Math.log10(track.gain)).toFixed(1):"−∞"}<small>dB</small></span><span className="d-track-pan">{track.pan===0?"C":track.pan<0?`L${-track.pan}`:`R${track.pan}`}</span></div>
            </div>
            <div className={`d-lane-canvas ${tool==="range"?"range-tool":""}`} onContextMenu={e=>{e.preventDefault();laneMenu(e.clientX,e.clientY,track.id);}}
              onPointerDown={e=>{if(e.button!==0)return;if(tool!=="range"){setKind("none");setIds([]);setRange(null);return;}e.preventDefault();rangeDrag.current={time:snapped(pointerTime(e.clientX)),index};setRange({start:rangeDrag.current.time,end:rangeDrag.current.time,trackIds:[track.id]});setKind("range");setIds([]);e.currentTarget.setPointerCapture(e.pointerId);}}
              onPointerMove={e=>{if(!rangeDrag.current||!e.currentTarget.hasPointerCapture(e.pointerId))return;const at=snapped(pointerTime(e.clientX));const rect=body.current!.getBoundingClientRect();const rowHeight=88;const row=Math.max(0,Math.min(project.tracks.length-1,Math.floor((e.clientY-rect.top+body.current!.scrollTop-(maps?76:0))/rowHeight)));setRange({start:Math.min(at,rangeDrag.current.time),end:Math.max(at,rangeDrag.current.time),trackIds:project.tracks.slice(Math.min(row,rangeDrag.current.index),Math.max(row,rangeDrag.current.index)+1).map(t=>t.id)});}}
              onPointerUp={e=>{rangeDrag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}>
              {grid}{project.clips.filter(c=>c.trackId===track.id).map(clip=><div key={clip.id} data-clip={clip.id} tabIndex={0} role="button" aria-label={`${clip.name} event`} className={`d-event ${kind==="audio"&&effective.some(c=>c.id===clip.id)?"selected":""}`} style={{left:(clip.start-left)*zoom,width:Math.max(4,clip.duration*zoom)}}
                onContextMenu={e=>{e.preventDefault();e.stopPropagation();if(kind==="range"&&range&&pointerTime(e.clientX)>=range.start&&pointerTime(e.clientX)<=range.end)laneMenu(e.clientX,e.clientY,track.id);else eventMenu(e.clientX,e.clientY,clip.id,e.currentTarget);}}
                onPointerDown={e=>{
                  if(e.button!==0||tool==="range")return;e.preventDefault();e.stopPropagation();setTrackId(track.id);
                  if(tool==="erase"){commit(removeClips(history.current.current,[clip.id],linked),"Erase event");return;}
                  if(tool==="split"){commit(splitClips(history.current.current,[clip.id],snapped(pointerTime(e.clientX)),linked),"Split event");return;}
                  const selected=e.shiftKey?ids.includes(clip.id)?ids.filter(id=>id!==clip.id):[...ids,clip.id]:ids.includes(clip.id)?[clip.id,...ids.filter(id=>id!==clip.id)]:[clip.id];
                  setIds(selected);setKind("audio");setRange(null);e.currentTarget.setPointerCapture(e.pointerId);
                  const mode=(e.target as HTMLElement).dataset.edge as "start"|"end"|undefined;
                  drag.current={x:e.clientX,initial:history.current.current,ids:selected,mode:mode||"move",delta:0};
                }} onPointerMove={e=>{const held=drag.current;if(!held||!e.currentTarget.hasPointerCapture(e.pointerId))return;const reference=held.initial.clips.find(clip=>clip.id===held.ids[0]);if(!reference)return;const anchor=held.mode==="end"?reference.start+reference.duration:reference.start;const delta=(e.clientX-held.x)/zoom;held.delta=snapTime(held.initial,Math.max(0,anchor+delta),snap as "off"|"beat"|"bar")-anchor;setProject(held.mode==="move"?moveClips(held.initial,held.ids,held.delta,linked):trimClips(held.initial,held.ids,held.mode,held.delta,linked));}}
                onPointerUp={e=>{const held=drag.current;if(!held)return;drag.current=null;if(held.delta!==0)commit(project,held.mode==="move"?"Move events":"Trim events");else setProject(held.initial);if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}
                onPointerCancel={()=>{if(drag.current)setProject(drag.current.initial);drag.current=null;}}>
                <div className="d-event-title"><span>{clip.name.replace(/\.wav$/,"")}</span>{clip.groupId&&<Link2 size={12}/>}</div>
                <Waveform data={waveforms.find(w=>w.name===project.assets.find(a=>a.id===clip.assetId)?.name.replace(/\.wav$/,""))} offset={clip.sourceStart} duration={clip.duration}/>
                <i data-edge="start" className="d-trim d-trim-left"/><i data-edge="end" className="d-trim d-trim-right"/>
              </div>)}
              {range&&range.trackIds.includes(track.id)&&<div className="d-range-overlay" style={{left:(range.start-left)*zoom,width:(range.end-range.start)*zoom}}><i/><i/></div>}
            </div>
          </div>)}
          <div className="d-lane d-rest-lane"><div className="d-track-list-empty" onContextMenu={e=>{e.preventDefault();setMenu({x:e.clientX,y:e.clientY,items:[{label:"Add Audio Track…",action:()=>setDialog("addtrack")},{label:"Import Audio…",action:()=>showImport()} ]});}}/><div className="d-lane-canvas">{grid}{!project.tracks.length&&<div className="d-empty-project"><FileAudio size={30}/><button onClick={()=>showImport()}><FolderOpen size={16}/>Import Audio…</button><small>WAV · MP3 · FLAC</small></div>}</div></div>
          <div className="d-cursor-layer" style={{left:`calc(var(--track-width) + ${Math.round((cursor-left)*zoom)}px)`,height:(maps?76:0)+project.tracks.length*88+70,display:cursor<left||(cursor-left)*zoom>canvasWidth?"none":undefined}}/>
        </div>
        <div className="d-timeline-foot"><div className="d-track-foot" aria-hidden="true"/><div className="d-scrollbar"><input aria-label="Timeline horizontal scroll" type="range" min={0} max={60} step={.1} value={left} onChange={e=>setLeft(Number(e.target.value))}/></div><div className="d-zoom"><IconButton label="Zoom out" onClick={()=>setZoom(Math.max(4,zoom/1.3))}><Minus size={13}/></IconButton><input aria-label="Timeline zoom" type="range" min={4} max={80} value={zoom} onChange={e=>setZoom(Number(e.target.value))}/><IconButton label="Zoom in" onClick={()=>setZoom(Math.min(80,zoom*1.3))}><Plus size={13}/></IconButton><IconButton label="Zoom to Project" onClick={fit}><Maximize2 size={13}/></IconButton></div></div>
        {lower&&lead&&<section className="d-lower"><header><b>Audio Editor</b><span>{lead.name}</span><IconButton label="Close Audio Editor" onClick={()=>setLower(false)}><X size={14}/></IconButton></header><Waveform data={waveforms.find(w=>w.name===lead.name.replace(/\.wav$/,""))} offset={lead.sourceStart} duration={lead.duration}/></section>}
      </section>
    </main>
    <section className="d-transport" aria-label="Transport">
      <div className="d-locators"><div><button title="Go to left locator" onClick={()=>setCursor(locators.start)}>L</button><TimeField project={project} label="Left locator" value={locators.start} onChange={v=>setLocators({start:v,end:Math.max(v,locators.end)})}/></div><div><button title="Go to right locator" onClick={()=>setCursor(locators.end)}>R</button><TimeField project={project} label="Right locator" value={locators.end} onChange={v=>setLocators({start:Math.min(v,locators.start),end:v})}/></div></div>
      <span className="d-transport-divider"/>
      <div className="d-transport-keys"><IconButton label="Return to Start" onClick={()=>setCursor(0)}><SkipBack size={17}/></IconButton><IconButton label="Cycle" active={cycle} className="d-cycle-button" onClick={()=>setCycle(!cycle)}><Repeat2 size={17}/></IconButton><IconButton label="Stop" active={!playing} className="d-stop-button" onClick={()=>setPlaying(false)}><Square size={15} fill="currentColor"/></IconButton><IconButton label="Play" active={playing} className="d-play-button" onClick={()=>setPlaying(true)}><Play size={19} fill="currentColor"/></IconButton></div>
      <div className="d-position"><TimeField project={project} label="Project cursor position" value={cursor} onChange={setCursor}/></div>
      <span className="d-transport-divider"/>
      <label className="d-tempo-footer"><ValueField label="Tempo" value={bpm} min={1} max={999} step={1} commitEqual format={v=>v.toFixed(3)} adjust={(v,n)=>Math.max(1,Math.min(999,Math.round(v)+n))} onChange={v=>setFooterTempo(v,cursor)}/><span>BPM</span></label>
      <div className="d-signature-footer" title="Time signature"><ValueField label="Transport signature numerator" value={signature.numerator} min={1} max={32} step={1} format={v=>String(v)} adjust={(v,n)=>Math.round(v)+n} onChange={v=>project.signatures.length?commit(putSignature(history.current.current,{id:crypto.randomUUID(),bar:cursorPosition.bar,numerator:Math.round(v),denominator:signature.denominator,origin:"manual"}),"Signature at bar"):commit({...history.current.current,signature:{numerator:Math.round(v),denominator:signature.denominator}},"Project signature")}/><span>/</span><select aria-label="Transport signature denominator" value={signature.denominator} onChange={e=>{const denominator=Number(e.target.value);project.signatures.length?commit(putSignature(history.current.current,{id:crypto.randomUUID(),bar:cursorPosition.bar,numerator:signature.numerator,denominator,origin:"manual"}),"Signature at bar"):commit({...history.current.current,signature:{...signature,denominator}},"Project signature");}}>{[1,2,4,8,16,32].map(v=><option key={v}>{v}</option>)}</select></div>
      <span className="d-transport-divider"/>
      <div className="d-click-footer"><IconButton label="Metronome" active={click} onClick={()=>setClick(!click)}><Metronome size={17}/></IconButton><GainField gain={project.clickGain} referenceGain={fixture().clickGain} maxDb={12} label="Click level dB" onChange={v=>commit({...history.current.current,clickGain:v},"Click level")}/></div>
      <div className="d-transport-space"/>
      <div className="d-output-footer"><Volume2 size={17} aria-label="Output"/><VolumeFader label="Output volume" gain={project.masterGain} horizontal onPreview={v=>setProject({...project,masterGain:v})} onCommit={v=>commit({...history.current.current,masterGain:v},"Output volume")}/><GainField gain={project.masterGain} label="Output level dB" onChange={v=>commit({...history.current.current,masterGain:v},"Output level")}/><div className="d-output-meter" aria-label="Output meters at rest"><i/><i/></div></div>
    </section>
    {dialog&&dialog!=="analysis"&&dialog!=="export"&&<div className="d-modal-shade" onClick={()=>setDialog(null)}><section className="d-dialog" role="dialog" aria-modal="true" aria-label={dialog} onClick={e=>e.stopPropagation()}><header><b>{dialog==="import"?"Import Audio":dialog==="addtrack"?"Add Audio Track":dialog==="removetrack"?"Remove Track":"Rename Track"}</b><IconButton label="Close dialog" onClick={()=>setDialog(null)}><X size={16}/></IconButton></header>
      {dialog==="addtrack"?<div className="d-retained-dialog"><AddAudioTrackDialog location="After the last audio track." onCancel={()=>setDialog(null)} onAdd={(name,count)=>{const next=addAudioTracks(history.current.current,count,name,null);commit(next,"Add audio tracks");setTrackId(next.tracks.at(-1)!.id);setDialog(null);}}/></div>:dialog==="removetrack"?<div className="d-retained-dialog"><RemoveTracksDialog tracks={selectedTrack?[selectedTrack]:[]} events={project.clips.filter(c=>c.trackId===trackId).length} onCancel={()=>setDialog(null)} onRemove={()=>{const next=removeTracks(history.current.current,[trackId]);commit(next,"Remove track");setTrackId(next.tracks[0]?.id||"");setIds([]);setKind("none");setDialog(null);}}/></div>:dialog==="import"?<><div className="d-dialog-body"><b>4 audio files</b><div className="d-import-files">{names.map(name=><span key={name}><FileAudio size={14}/>{name}.wav <small>30.000 s</small></span>)}</div><label>Placement<select value={importMode} onChange={e=>setImportMode(e.target.value as typeof importMode)}><option value="stems">Aligned stems · linked events</option><option value="tracks">Different tracks · same start</option><option value="sequence">One track · files in sequence</option></select></label><TimeField project={project} value={importTarget.at} label="Import position" onChange={at=>setImportTarget({...importTarget,at})}/><p>{importMode==="sequence"?"Files join end to end on one track.":importMode==="stems"?"All stems start together and stay linked for editing.":"Files start together and can be edited independently."}</p></div><footer><button onClick={()=>setDialog(null)}>Cancel</button><button className="primary" onClick={importPreview}>Import Audio</button></footer></>:<><div className="d-dialog-body"><label>Track name<input autoFocus value={rename} onChange={e=>setRename(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&rename.trim()){updateTrack({name:rename.trim()});setDialog(null);}}}/></label></div><footer><button onClick={()=>setDialog(null)}>Cancel</button><button className="primary" disabled={!rename.trim()} onClick={()=>{updateTrack({name:rename.trim()});setDialog(null);}}>Rename</button></footer></>}
    </section></div>}
  </div>;

  const references=<section className="review-references"><header><h1>배치의 근거</h1><p>실제 제품에서 확인한 구성을 BPMTracker의 핵심 작업에 맞춰 적용했습니다.</p></header><div className="review-reference-grid">
    <article><h2>1. Cubase · Inspector</h2><div className="reference-crop inspector-crop"><img src={ASSETS+"cubase-inspector.png"}/></div><p>트랙 이름 → 상태 버튼 → 슬라이더와 수치 → 접는 섹션. 같은 트랙의 조작과 결과를 가까이 둡니다.</p><a href="https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/project_window/project_window_inspector_r.html" target="_blank" rel="noreferrer">공식 Inspector 문서 ↗</a></article>
    <article><h2>2. Cubase · 도구와 Info Line</h2><div className="reference-crop toolbar-crop"><img src={ASSETS+"cubase-info-line.png"}/></div><p>도구는 아이콘 그룹, 선택 속성은 구분된 수치 열. 이벤트와 트랙의 편집 대상을 분명히 나눕니다.</p><a href="https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/project_window/project_window_toolbar_r.html" target="_blank" rel="noreferrer">공식 Toolbar 문서 ↗</a> · <a href="https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/project_window/project_window_info_line_c.html" target="_blank" rel="noreferrer">Info Line ↗</a></article>
    <article><h2>3. Cubase · Transport</h2><div className="reference-crop transport-crop"><img src={ASSETS+"cubase-inspector.png"}/></div><p>로케이터, 재생, 현재 위치, 템포를 인접한 고정 그룹으로 둡니다. 녹음·외부 동기화 등은 가져오지 않습니다.</p><a href="https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/project_window/project_window_transport_r.html" target="_blank" rel="noreferrer">공식 Transport 문서 ↗</a></article>
    <article><h2>4. Cubase · 우클릭</h2><div className="reference-crop menu-crop"><img src={ASSETS+"cubase-menu.png"}/></div><p>대상별 명령, 구분선, 오른쪽 단축키, 하위 메뉴와 체크 표시. BPMTracker에서는 필요한 명령만 표시합니다.</p><a href="https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/menus-and-context-menus" target="_blank" rel="noreferrer">Windows 메뉴 가이드 ↗</a></article>
    <article><h2>5. Ableton Live · Arrangement</h2><img className="review-product-image" src={ASSETS+"ableton-arrangement.png"}/><p>명확한 클립 경계, 이름 영역과 파형의 구분, 시간 선택 표시를 참고했습니다. Inspector와 Transport 배치는 Cubase를 따릅니다.</p><a href="https://www.ableton.com/en/manual/arrangement-view/" target="_blank" rel="noreferrer">공식 Arrangement 문서 ↗</a></article>
    <article className="review-decisions"><h2>BPMTracker에서 유지할 규칙</h2><ul><li>새 트랙은 Linear. 시간 기준 전환은 물리적 위치를 보존합니다.</li><li>하단 BPM 입력은 현재 커서에 선언합니다. 입력한 정밀도는 유지합니다.</li><li>연결된 이벤트 편집과 트랙별 믹싱의 범위를 구분합니다.</li><li>원본 분석, 편집한 분석값, 프로젝트 맵은 각각 보존합니다.</li><li>녹음·VST·MIDI 연주 편집·FX·자동화는 추가하지 않습니다.</li></ul><p>이 화면은 U2 검토용입니다. 이후 분석 검토 화면은 별도 단계에서 다듬습니다.</p></article>
  </div><p className="review-reference-note">Cubase 캡처는 2026-10-06의 사용자 설정 환경입니다. 공장 기본 배치·단축키를 주장하지 않습니다.</p></section>;

  return <div className={`review-shell ${bare?"bare":""}`}>
    {!bare&&<header className="review-bar"><b>BPMTracker <span>U2 / revised</span></b><div className="review-tabs"><button className={view==="proposal"?"active":""} onClick={()=>setView("proposal")}>새 구성</button><button className={view==="baseline"?"active":""} onClick={()=>{setView("baseline");reset("linked");}}>기존 화면</button><button className={view==="references"?"active":""} onClick={()=>setView("references")}>제품 참고</button></div><select aria-label="Review scene" value={scene} onChange={e=>{reset(e.target.value as Scene);setView("proposal");}}><option value="linked">연결된 4개 이벤트</option><option value="single">이벤트 하나</option><option value="range">범위 선택</option><option value="tempo">템포 포인트</option><option value="signature">박자표 포인트</option><option value="none">선택 없음</option><option value="empty">빈 프로젝트</option></select><select aria-label="Review size" value={size} onChange={e=>setSize(e.target.value)}><option value="window">현재 창 크기</option><option value="wide">1440 × 940</option><option value="compact">1024 × 720</option></select><button className="review-reset" onClick={()=>{reset();setView("proposal");}}>초기화</button><span className="review-scope">조작 검토용 · 실제 재생/저장/분석 없음</span></header>}
    <div className={`review-stage ${view==="references"?"references":""} ${size!=="window"?"fixed-size":""}`}>
      {view==="references"?references:<div className="review-frame" style={size==="wide"?{width:1440,height:940}:size==="compact"?{width:1024,height:720}:undefined}>
        {view==="baseline"?<div className="review-baseline"><img src={ASSETS+(size==="compact"?"baseline-compact.png":"baseline-wide.png")}/><span>실제 BPMTracker 0.6.10 캡처 · 0.6.11은 커서 표시/원점 이동 수정 · 30초 스템 4개 · 12 px/s</span></div>:app}
      </div>}
    </div>
    {menu&&<ContextMenu key={`${menu.x}:${menu.y}:${menu.title}`} menu={menu} close={()=>setMenu(null)}/>}
    {notice&&<div className="review-notice" role="status">{notice}</div>}
  </div>;
}

createRoot(document.getElementById("root")!).render(<DesignReview/>);
