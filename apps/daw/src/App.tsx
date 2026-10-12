import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  AudioLines,
  ArrowRightToLine,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Download,
  FileAudio,
  FolderOpen,
  Headphones,
  Link2,
  Layers,
  LoaderCircle,
  Magnet,
  Maximize2,
  Minus,
  Music2,
  MousePointer2,
  PanelLeftClose,
  PanelBottom,
  Plus,
  Redo2,
  Save,
  Scissors,
  StretchHorizontal,
  Trash2,
  Undo2,
  Waves,
  X,
} from "lucide-react";
import Timeline, { type TimelineViewportControl } from "./Timeline";
import AudioEditor from "./AudioEditor";
import { AudioEngine } from "./audio";
import { ProjectHistory } from "./history";
import { NumberField, PanFader } from "./controls";
import { cancelMenuGestures, cancelValueGesture } from "./valueGesture";
import ValueField from "./ValueField";
import ContextMenu, { editableText, menuCommand, type ArrangementContext, type MenuEntry, type MenuPopup } from "./ContextMenu";
import { captureControlContext, controlMenuItems } from "./controlContext";
import VolumeFader, { GainField } from "./VolumeFader";
import Transport, { SignatureField, TimeField } from "./Transport";
import ProjectMapEditor from "./ProjectMapEditor";
import ImportAudioDialog, { type ImportStart } from "./ImportAudioDialog";
import { AddAudioTrackDialog, RemoveTracksDialog } from "./TrackDialogs";
import SampleLibraryDialog from "./SampleLibrary";
import { DEFAULT_CLICK_GAIN } from "./click-level";
import SampleReviewPanel from "./SampleReviewPanel";
import SelectionMove from "./SelectionMove";
import ResizablePane from "./ResizablePane";
import { arrangementBounds, arrangementDestination, moveArrangement } from "./arrangement";
import { sampleWorkspace, sampleClicks, type SampleReference } from "./samples";
import { clockPlacement, editProjectMap, placeClockOnProject, positionAtQuarter, putSignature, putTempo, quarterAtTime, refreshMusicalAnchors, setTrackTimeBase, snapToProject, tempoAtQuarter, timeAtBar, timeAtQuarter, upgradeProject } from "./music";
import {
  applyAnalysis,
  addAudioTracks,
  clipEnd,
  clockGeometry,
  clockSourceScope,
  copyAudio,
  pasteAudio,
  moveRange,
  orderClips,
  createProject,
  duplicateTracks,
  formatTime,
  getAsset,
  importAssets,
  moveClips,
  projectEnd,
  relatedClips,
  removeClips,
  removeRange,
  removeTracks,
  reorderTracks,
  rangeClips,
  splitClips,
  trimClips,
  uid,
  type AudioClipboard,
  type Analysis,
  type Asset,
  type Clip,
  type Clock,
  type ClockValues,
  type ImportOptions,
  type ImportDestination,
  type JobEvent,
  type Project,
  type Snap,
  type TimeRange,
  type Tool,
  type Track,
  type MapSelection,
  type ArrangementSelection,
  type TempoEvent,
  type SignatureEvent,
  type TimeSignature,
  type AudioClock,
} from "./model";

type AnalysisScope = {
  clipId: string;
  asset: Asset;
  sourceStart: number;
  sourceEnd: number;
  start: number;
  end: number;
  whole: boolean;
  name: string;
};
type Modal = "import" | "samples" | "analyze" | "export" | "help" | "save-as" | "project-setup" | "add-track" | "remove-tracks" | null;
type EditContext = {
  projectId: string; owner: number; selection: ArrangementSelection; range: TimeRange | null;
  linked: boolean; cursor: number; trackId: string | null; point?: number;
};
function importPreferences(): { mode: ImportOptions["mode"]; copy: boolean } {
  try {
    const value = JSON.parse(localStorage.getItem("joljak.import-preferences") ?? "null");
    return { mode: ["sequence", "tracks", "stems"].includes(value?.mode) ? value.mode : "sequence", copy: value?.copy === true };
  } catch { return { mode: "sequence", copy: false }; }
}
const keyGuide = [
  ["1 / 2 / 3 / 5", "Object / Range / Split / Erase tool"],
  ["Space / Num Enter / Num 0", "Start–stop / Start / Stop"],
  ["Double-click / Ctrl E / Enter", "Open selected event in Audio Editor"],
  ["Num .", "Go to project start"],
  ["P / Alt P", "Locators to selection / Loop selection"],
  ["Num /", "Cycle on–off"],
  ["Num 1 / Num 2", "Go to left / right locator"],
  ["Shift P / Shift L / Shift R", "Focus project position / Left locator / Right locator"],
  ["Ctrl Num 1 / Ctrl Num 2", "Set left / right locator at the cursor"],
  ["C / F / J", "Metronome / Auto-scroll / Snap"],
  ["G / H / Shift F", "Zoom out / Zoom in / Fit project"],
  ["Alt S", "Zoom to selection"],
  ["Ctrl Z / Ctrl Shift Z", "Undo / Redo"],
  ["Ctrl C / Ctrl X / Ctrl V", "Copy / Cut / Paste"],
  ["Ctrl D", "Duplicate after selection"],
  ["U / Shift U", "Move selected events to front / back"],
  ["Range drag / Alt range drag", "Move / Copy range contents"],
  ["Alt X / Shift X", "Split at cursor / Split range boundaries"],
  ["Ctrl G / Ctrl U / K", "Group / Ungroup / Linked stem editing"],
  ["M / S", "Mute / Solo selected track"],
  ["Ctrl Shift A", "Clear selection"],
  ["T / Shift Delete", "Add audio tracks / Remove selected tracks"],
  ["Ctrl click / Shift click track", "Toggle track selection / Select a range of tracks"],
  ["Ctrl S / Ctrl Shift S", "Save / Save as"],
  ["Alt click / Alt drag", "Split event / Drag a copy"],
  ["Ctrl drag", "Constrain movement direction"],
  ["Ctrl on trim handle", "Temporarily disable snap"],
  ["Ctrl wheel / Shift wheel", "Zoom at pointer / Horizontal scroll"],
];

function InspectorSection({ title, children, initiallyOpen = false, badge }: {
  title: string; children: ReactNode; initiallyOpen?: boolean; badge?: string;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return <details className="inspector-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
    <summary>{title}{badge && <small>{badge}</small>}</summary>
    <div className="inspector-section">{children}</div>
  </details>;
}

export default function App() {
  const api = window.joljak;
  const history = useRef(new ProjectHistory(createProject()));
  const [project, setProject] = useState(history.current.current);
  const projectRef = useRef(project);
  projectRef.current = project;
  const [path, setPath] = useState<string | null>(null),
    [dirty, setDirty] = useState(false);
  const openProject = useRef<(filename?: string) => Promise<void>>(async () => {});
  const [arrangement,setArrangement]=useState<ArrangementSelection>({clips:[],maps:[]});
  const selection=arrangement.clips, selectedMaps=arrangement.maps;
  const setSelection=(ids:string[]|((previous:string[])=>string[]))=>setArrangement(previous=>
    ({...previous,clips:typeof ids==="function"?ids(previous.clips):ids}));
  const [activeTrack, setActiveTrack] = useState<string | null>(null);
  const [selectedTracks, setSelectedTracks] = useState<string[]>([]);
  const trackSelection = useRef<{ ids: string[]; active: string | null; anchor: string | null }>({ ids: [], active: null, anchor: null });
  const [popup, setPopup] = useState<MenuPopup | null>(null);
  const popupRef = useRef(popup); popupRef.current = popup;
  const closeMenu = useCallback(() => setPopup(null), []);
  const appMenu = popup?.appMenu ?? null;
  const [addBeforeTrack, setAddBeforeTrack] = useState<string | null>(null), [removingTracks, setRemovingTracks] = useState<string[]>([]);
  const [range, setRange] = useState<TimeRange | null>(null),
    [selectedClock, setSelectedClock] = useState<string | null>(null);
  const rangeRef = useRef(range); rangeRef.current = range;
  const [editorClipId, setEditorClipId] = useState<string | null>(null);
  const editorClip = project.clips.find((c) => c.id === editorClipId) ?? null;
  const [selectedMap,setMapFocus]=useState<MapSelection|null>(null);
  const setSelectedMap=(next:MapSelection|null)=>{
    setMapFocus(next);
    setArrangement(previous=>!next?{...previous,maps:[]}:selectedMap?
      {...previous,maps:previous.maps.map(item=>item.id===selectedMap.id&&item.kind===selectedMap.kind?next:item)}:previous);
  };
  const [previewing, setPreviewing] = useState(false);
  const [referencePreview,setReferencePreview]=useState<"accepted"|"comparison"|null>(null);
  const previewClocks = useRef<AudioClock[] | undefined>(undefined);
  const [tool, setTool] = useState<Tool>("object"),
    [snap, setSnap] = useState<Snap>("beat"),
    [linked, setLinked] = useState(true);
  const chooseTool = (next: Tool) => {
    if (next !== "range") setRange(null);
    setTool(next);
  };
  const [position, setPosition] = useState(0),
    [playing, setPlaying] = useState(false),
    [buffering, setBuffering] = useState(false);
  const timelineViewport = useRef<TimelineViewportControl | null>(null);
  const [follow, setFollow] = useState(true);
  const [loop, setLoop] = useState({ start: 0, end: 0, enabled: false });
  const [metronome, setMetronome] = useState(false),
    [mixer, setMixer] = useState(false),
    [inspector, setInspector] = useState(true);
  const [showMaps, setShowMaps] = useState(() => localStorage.getItem("joljak.ui.maps") !== "hidden");
  const [layoutRevision, setLayoutRevision] = useState(0);
  const toggleMaps = () => setShowMaps(value => { const next = !value; localStorage.setItem("joljak.ui.maps", next ? "shown" : "hidden"); return next; });
  const [meter, setMeter] = useState([0, 0]);
  const peaks = useRef(new Map<string, Float32Array>()),
    [, refreshPeaks] = useState(0);
  const [modal, setModal] = useState<Modal>(null),
    [message, setMessage] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobEvent[]>([]);
  const pendingImports = useRef(new Map<string, ImportOptions>());
  const pendingSampleImports=useRef(new Map<string,{reference:SampleReference;comparison:boolean}>());
  const [sampleBusy,setSampleBusy]=useState(false);
  const session = useRef(0);
  const jobSessions = useRef(new Map<string, { session: number; kind: string }>());
  const switchSession = () => {
    session.current++;
    for (const [id, owner] of jobSessions.current)
      if (owner.kind !== "export") void api?.cancel(id);
    setJobs((list) => list.filter((job) => job.kind === "export"));
    setModal(null); closeMenu(); setEditorClipId(null);
    setImportMode(confirmedImportPrefs.current.mode); setCopyMedia(confirmedImportPrefs.current.copy);
    trackSelection.current = { ids: [], active: null, anchor: null };
    setSelectedTracks([]); setActiveTrack(null);
    importRequest.current = null; setImportBusy(false);
    setReferencePreview(null);setSampleBusy(false);
  };
  const [importPrefs] = useState(importPreferences);
  const confirmedImportPrefs = useRef(importPrefs);
  const [importPaths, setImportPaths] = useState<string[]>([]),
    [importMode, setImportMode] = useState<ImportOptions["mode"]>(importPrefs.mode),
    [copyMedia, setCopyMedia] = useState(importPrefs.copy),
    [importAt, setImportAt] = useState<ImportStart>("cursor");
  const [importDestination, setImportDestination] = useState<ImportDestination>({ start: 0, targetTrackId: null, beforeTrackId: null, source: "cursor" });
  const [importStart, setImportStart] = useState(0), [importBusy, setImportBusy] = useState(false);
  const importSnapshot = useRef({ session: 0, cursor: 0, end: 0, drop: 0 });
  const importRequest = useRef<string | null>(null);
  const [scope, setScope] = useState<AnalysisScope | null>(null),
    [tap, setTap] = useState(""),
    [tapCount, setTapCount] = useState(0);
  const tapTimes = useRef<number[]>([]);
  const [pendingAnalysis, setPendingAnalysis] = useState<Analysis | null>(null);
  const [exportMix, setExportMix] = useState(true),
    [exportStems, setExportStems] = useState(true),
    [exportClick, setExportClick] = useState(true),
    [exportMaps, setExportMaps] = useState(true),
    [exportScope, setExportScope] = useState<"project" | "locators">("project");
  const [saveCollect, setSaveCollect] = useState(false);
  const engine = useRef<AudioEngine | null>(null);
  const commands = useRef<(command: string) => void>(() => {});
  useEffect(() => { closeMenu(); }, [project.id, modal]);
  const commit = (next: Project, label: string) => {
    if (next === projectRef.current) return;
    const value = history.current.commit(refreshMusicalAnchors(next), label);
    projectRef.current = value;
    setProject(value);
    setPreviewing(false);
    setReferencePreview(null);
    setDirty(true);
  };
  const change = (modify: (p: Project) => Project, label: string) =>
    commit(modify(projectRef.current), label);
  const tell = (text: string) => setMessage(text);
  const selectTracks = (ids: string[], active = ids.at(-1) ?? null, anchor = active) => {
    trackSelection.current = { ids, active, anchor };
    setSelectedTracks(ids); setActiveTrack(active);
  };
  const selectTrack = (id: string, modifiers = { ctrl: false, shift: false }, preserve = false) => {
    const current = trackSelection.current, tracks = projectRef.current.tracks;
    if (!tracks.some((track) => track.id === id)) return [];
    let ids: string[];
    if (modifiers.shift && current.anchor && tracks.some((track) => track.id === current.anchor)) {
      const indexes = [tracks.findIndex((track) => track.id === current.anchor), tracks.findIndex((track) => track.id === id)].sort((a, b) => a - b);
      const rangeIds = tracks.slice(indexes[0], indexes[1] + 1).map((track) => track.id);
      ids = modifiers.ctrl ? [...new Set([...current.ids, ...rangeIds])] : rangeIds;
    } else if (modifiers.ctrl) ids = current.ids.includes(id) ? current.ids.filter((track) => track !== id) : [...current.ids, id];
    else ids = preserve && current.ids.includes(id) ? current.ids : [id];
    selectTracks(ids, ids.includes(id) ? id : ids.at(-1) ?? null, modifiers.shift ? current.anchor : id);
    // Track focus and object selection are independent, as in the project
    // window: selecting a channel must not discard the user's edit/analysis scope.
    closeMenu();
    return ids;
  };
  useEffect(() => {
    const current = trackSelection.current, available = new Set(project.tracks.map((track) => track.id));
    const ids = current.ids.filter((id) => available.has(id));
    if (ids.length !== current.ids.length || (current.active && !available.has(current.active)))
      selectTracks(ids, current.active && available.has(current.active) ? current.active : ids.at(-1) ?? null,
        current.anchor && available.has(current.anchor) ? current.anchor : ids.at(-1) ?? null);
  }, [project.tracks]);
  const selectedClip = project.clips.find((c) => c.id === selection[0]);
  const track = project.tracks.find(
    (t) => t.id === (activeTrack ?? selectedClip?.trackId),
  );
  const clock =
    project.clocks.find((c) => c.id === selectedClock && clockSourceScope(project, c)) ??
    [...project.clocks].reverse().find((c) => c.clipId === selectedClip?.id && clockSourceScope(project, c));
  const mapTempo = selectedMap?.kind === "tempo" ? project.tempos.find((t) => t.id === selectedMap.id) : null;
  const mapSignature = selectedMap?.kind === "signature" ? project.signatures.find((s) => s.id === selectedMap.id) : null;
  const arrangementInfo=arrangementBounds(project,arrangement,linked);
  const mixedInfo = selectedMaps.length > 1 || (selectedMaps.length > 0 && selection.length > 0);
  const mapPositionGrid = selectedMap ? arrangementDestination(project, { clips: [], maps: [selectedMap] }) : project;
  const activeJob = jobs.find(
    (j) => !["complete", "failed", "cancelled"].includes(j.stage),
  );
  let placementLabel: string | null = null;
  const alignmentLabel = (saved: Clock) => {
    try {
      const aligned = clockPlacement(project, saved);
      return `First downbeat → bar ${aligned.bar}. Song and linked stems: ${aligned.delta >= 0 ? "+" : ""}${aligned.delta.toFixed(4)} s.`;
    } catch (e) { return e instanceof Error ? e.message : String(e); }
  };
  if (pendingAnalysis?.result.period_seconds) {
    const result = pendingAnalysis.result;
    const proposal: Clock = { id: pendingAnalysis.id, clipId: pendingAnalysis.clipId, name: "Analysis proposal", sourceStart: pendingAnalysis.sourceStart, sourceEnd: pendingAnalysis.sourceEnd,
      values: { bpm: result.quarter_bpm, numerator: result.time_signature.numerator, denominator: result.time_signature.denominator, offset: result.offset_seconds },
      original: { bpm: result.quarter_bpm, numerator: result.time_signature.numerator, denominator: result.time_signature.denominator, offset: result.offset_seconds }, analysisId: pendingAnalysis.id };
    try {
      const aligned = clockPlacement(project, proposal);
      placementLabel = `First downbeat → bar ${aligned.bar}. Song and linked stems: ${aligned.delta >= 0 ? "+" : ""}${aligned.delta.toFixed(4)} s.`;
    } catch { /* A removed source event cannot be applied. */ }
  }

  const loadPeaks = async (assets: Asset[]) => {
    if (!api) return;
    await api.registerAssets(assets);
    for (const asset of assets)
      if (!peaks.current.has(asset.id)) {
        try {
          peaks.current.set(asset.id, new Float32Array(await api.peaks(asset)));
          refreshPeaks((n) => n + 1);
        } catch {
          /* Restoring a project may need asynchronous decode first. */
        }
      }
  };
  useEffect(() => {
    if (!api) return;
    const audio = new AudioEngine(api);
    engine.current = audio;
    audio.onPosition = (time, state, levels) => {
      setPosition(time);
      setPlaying(state);
      setMeter(levels);
    };
    audio.onBuffering = setBuffering;
    audio.onError = tell;
    let disposed = false, initializing = true, opening = false;
    const requests: string[] = [];
    const drain = async () => {
      if (initializing || opening || disposed) return;
      opening = true;
      try { while (requests.length && !disposed) await openProject.current(requests.shift()); }
      finally { opening = false; }
    };
    const externalOpen = () => {
      void api.pendingProjects().then(files => { requests.push(...files); return drain(); }).catch(error => tell(String(error)));
    };
    const unsubscribeOpen = api.onOpenProject?.(externalOpen);
    void (async () => {
      requests.push(...(await api.pendingProjects?.() ?? []));
      if (disposed) return;
      if (!requests.length) {
        const recovery = await api.recovery();
        if (
          !disposed && !requests.length && recovery?.project.clips.length &&
          confirm("Recover the last automatically saved session?")
        ) {
          const restored = upgradeProject(recovery.project);
          history.current.replace(restored);
          projectRef.current = restored;
          setProject(restored);
          setDirty(true);
          void loadPeaks(recovery.project.assets);
        }
      }
      initializing = false;
      await drain();
    })().catch(error => { initializing = false; tell(String(error)); void drain(); });
    const unsubscribe = api.onCommand((command) => {
      const menu = popupRef.current;
      if (menu) { const entry = menuCommand(menu.items, command); if (entry && !entry.disabled) { closeMenu(); void entry.action?.(); } return; }
      const focused = document.activeElement as HTMLElement | null;
      const textEditor = focused instanceof HTMLInputElement && !focused.readOnly && focused.type !== "range"
        || focused instanceof HTMLTextAreaElement || focused?.isContentEditable;
      if (textEditor && (command === "undo" || command === "redo")) { document.execCommand(command); return; }
      if ((command === "undo" || command === "redo") && cancelValueGesture(focused)) return;
      commands.current(command);
    });
    return () => {
      disposed = true; unsubscribeOpen?.();
      unsubscribe();
      audio.dispose();
    };
  }, []);
  useEffect(() => {
    engine.current?.updateProject(project, previewing ? previewClocks.current : undefined,
      referencePreview ? sampleClicks(project,referencePreview==="comparison") : undefined);
  }, [project, previewing,referencePreview]);
  useEffect(() => {
    const valid=selectedMaps.filter(item=>(item.kind==="tempo"?project.tempos:project.signatures).some(event=>event.id===item.id));
    if(valid.length!==selectedMaps.length)setArrangement(previous=>({...previous,maps:valid}));
    if(selectedMap&&!valid.some(item=>item.id===selectedMap.id&&item.kind===selectedMap.kind))setMapFocus(valid[0]??null);
  }, [project.tempos, project.signatures, selectedMap,selectedMaps]);
  useEffect(() => {
    if (api && project.assets.length) void loadPeaks(project.assets);
  }, [project.assets]);
  useEffect(() => {
    const close = () => {
      api?.closingProject(projectRef.current);
    };
    window.addEventListener("beforeunload", close);
    return () => window.removeEventListener("beforeunload", close);
  }, []);
  useEffect(() => {
    engine.current?.setLoop(loop);
  }, [loop]);
  useEffect(() => {
    engine.current?.setClick(metronome, project.clickGain ?? DEFAULT_CLICK_GAIN);
  }, [metronome, project.clickGain]);
  useEffect(() => {
    if (!api || !dirty) return;
    const timer = setTimeout(() => {
      void api.autosave(project).catch((e) => tell(`Autosave: ${e.message}`));
    }, 1200);
    return () => clearTimeout(timer);
  }, [project, dirty]);
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 6500);
    return () => clearTimeout(timer);
  }, [message]);
  useEffect(() => {
    if (!api) return;
    return api.onJob((event) => {
      const owner = jobSessions.current.get(event.id);
      if (owner && owner.kind !== "export" && owner.session !== session.current) {
        if (["complete", "failed"].includes(event.stage)) {
          pendingImports.current.delete(event.id);
          pendingSampleImports.current.delete(event.id);
          jobSessions.current.delete(event.id);
          if (event.kind === "decode") void api.finishImport(event.id, false).catch(() => {});
        }
        return;
      }
      setJobs((list) => {
        const index = list.findIndex((j) => j.id === event.id);
        return index < 0
          ? [...list, event]
          : list.map((j) => (j.id === event.id ? { ...j, ...event } : j));
      });
      if (event.stage === "failed") {
        pendingImports.current.delete(event.id);
        if(pendingSampleImports.current.delete(event.id))setSampleBusy(false);
        jobSessions.current.delete(event.id);
        tell(event.error || "Job failed");
      }
      if (event.stage !== "complete") return;
      jobSessions.current.delete(event.id);
      if (event.kind === "decode") {
        const assets: Asset[] = event.result.assets;
        const sample=pendingSampleImports.current.get(event.id);
        if(sample){
          pendingSampleImports.current.delete(event.id);setSampleBusy(false);
          try{
            const next=sampleWorkspace(sample.reference,assets[0],sample.comparison);
            engine.current?.reset();switchSession();history.current.replace(next);
            projectRef.current=next;setProject(next);setPath(null);setDirty(true);
            const clip=next.clips[0];setSelection([clip.id]);selectTracks([clip.trackId]);
            setRange(null);setSelectedClock(null);setSelectedMap(null);setPendingAnalysis(null);
            const suppliedClock=sample.reference.availableClock!==false;
            setPreviewing(false);setReferencePreview(suppliedClock?(sample.comparison?"comparison":"accepted"):null);setMetronome(suppliedClock);
            setLoop({start:clip.start,end:clip.start+clip.duration,enabled:false});
            engine.current?.reset(clip.start);setPosition(clip.start);peaks.current.clear();
            void api.finishImport(event.id,true).catch(e=>tell(e.message));void loadPeaks(assets);
            requestAnimationFrame(()=>timelineViewport.current?.setScale(
              Math.max(.2,Math.min(1200,(document.querySelector(".timeline-scroll")?.clientWidth??900)/(next.projectDuration+5))),0));
            tell("Sample workspace ready. Edit the project map and save a separate sample draft.");
          }catch(e){tell(String(e));void api.finishImport(event.id,false).catch(()=>{});}
          return;
        }
        const options = pendingImports.current.get(event.id);
        if (options) {
          pendingImports.current.delete(event.id);
          try {
            const next = importAssets(projectRef.current, assets, options);
            commit(next, "Import audio");
            const created = next.clips.filter((clip) => assets.some((asset) => asset.id === clip.assetId));
            setSelection(created.map((clip) => clip.id));
            selectTracks([...new Set(created.map((clip) => clip.trackId))], created[0]?.trackId ?? null);
            setRange(null); setSelectedClock(null); setSelectedMap(null);
            void api.finishImport(event.id, true).catch((e) => tell(e.message));
          } catch (error) {
            tell(error instanceof Error ? error.message : String(error));
            void api.finishImport(event.id, false).catch(() => {});
            return;
          }
        } else {
          if (!assets.some((asset) => projectRef.current.assets.some((current) => current.id === asset.id))) return;
          change(
            (p) => ({
              ...p,
              assets: p.assets.map(
                (a) => assets.find((x) => x.id === a.id) ?? a,
              ),
            }),
            "Restore audio cache",
          );
        }
        void loadPeaks(assets);
      } else if (event.kind === "analyze") {
        setProject(history.current.record(event.result));
        setDirty(true);
        setPendingAnalysis(event.result);
        tell(
          event.result.result.period_seconds
            ? "Clock proposal ready. Audition or apply it to the analyzed scope."
            : "No supported clock. The tap could not create one without audio evidence.",
        );
      } else if (event.kind === "export") {
        tell(
          `Exported ${event.result.files.length} files. All WAV files share the same start and length.`,
        );
        void api.reveal(event.result.files[0] ?? event.result.folder);
      }
    });
  }, []);

  const seek = (time: number) => {
    const value = Math.max(0, time);
    setPosition(value);
    if (engine.current)
      void engine.current.seek(value).catch((e) => tell(e.message));
  };
  const openSample=async(reference:SampleReference,comparison:boolean)=>{
    if(!api||sampleBusy)return;
    if(dirty&&!confirm("Open a sample workspace? Save the current project first if you want to keep it."))return;
    setSampleBusy(true);
    const owner=session.current,id=uid();
    try{
      // Read the selected catalog reference again before decode; the dialog is a
      // viewing snapshot, not authority to use a changed reference version.
      const current=reference.candidateDescriptorPath?
        await api.candidateReference(reference.candidateDescriptorPath,reference.id):await api.sampleReference(reference.id);
      if(owner!==session.current){setSampleBusy(false);return;}
      pendingSampleImports.current.set(id,{reference:current,comparison});
      jobSessions.current.set(id,{session:owner,kind:"decode"});
      await api.decode([current.audioPath],false,id);
    }catch(e){pendingSampleImports.current.delete(id);jobSessions.current.delete(id);setSampleBusy(false);tell(String(e));}
  };
  const auditionSample=(comparison=false)=>{
    const p=projectRef.current,clicks=sampleClicks(p,comparison),audio=engine.current;
    if(!clicks||!audio)return;
    setPreviewing(false);setReferencePreview(comparison?"comparison":"accepted");
    audio.updateProject(p,undefined,clicks);audio.setClick(true,p.clickGain);setMetronome(true);
    const clip=p.clips.find(c=>c.id===p.sampleReview?.clipId)!;
    if(!audio.playing)void audio.play(audio.position>=clip.start&&audio.position<clipEnd(clip)?audio.position:clip.start).catch(e=>tell(e.message));
  };
  const auditionSampleProject=()=>{
    setReferencePreview(null);setPreviewing(false);
    engine.current?.updateProject(projectRef.current);engine.current?.setClick(true,projectRef.current.clickGain);setMetronome(true);
    startPlayback();
  };
  const saveSampleDraft=async()=>{
    if(!api)return;
    try{const filename=await api.saveSampleDraft(projectRef.current);tell(`Sample draft saved: ${filename}`);}
    catch(e){tell(String(e));}
  };
  const startPlayback = () => {
    if (!api) { tell("Open Joljak as a desktop app to play local audio."); return; }
    const audio = engine.current;
    if (!audio || audio.playing) return;
    if (audio.position >= project.projectDuration) void audio.play(loop.enabled ? loop.start : 0);
    else void audio.play();
  };
  const togglePlay = () => {
    if (!api) {
      tell("Open Joljak as a desktop app to play local audio.");
      return;
    }
    const audio = engine.current;
    if (!audio) return;
    if (!audio.playing && audio.position >= project.projectDuration) void audio.play(loop.enabled ? loop.start : 0);
    else audio.toggle();
  };
  const selectionBounds = () => {
    if (range && range.end > range.start)
      return { start: range.start, end: range.end };
    if(selectedMaps.length)return arrangementBounds(project,arrangement,linked);
    const clips = relatedClips(project, selection, linked);
    return clips.length
      ? {
          start: Math.min(...clips.map((c) => c.start)),
          end: Math.max(...clips.map(clipEnd)),
        }
      : null;
  };
  const setLocators = (cycle = false, startPlayback = false) => {
    const bounds = selectionBounds();
    if (!bounds) {
      tell("Select an event or a time range first.");
      return;
    }
    setLoop({ ...bounds, enabled: cycle || loop.enabled });
    if (startPlayback) {
      engine.current?.setLoop({ ...bounds, enabled: cycle });
      void engine.current?.play(bounds.start).catch((e) => tell(e.message));
    }
  };
  const selectCopies = (next: Project, ids: string[], nextRange: TimeRange | null = null) => {
    setSelection(nextRange ? [] : ids); setRange(nextRange); setSelectedClock(null); setSelectedMap(null);
    const tracks = [...new Set(nextRange?.trackIds ?? ids.flatMap((id) => {
      const clip = next.clips.find((c) => c.id === id); return clip ? [clip.trackId] : [];
    }))];
    if (tracks.length) selectTracks(tracks, tracks[0]);
  };
  const editAudio = (clip = selectedClip) => {
    if (!clip) { tell("Select an audio event to open the editor."); return; }
    setEditorClipId(clip.id); setMixer(false); setSelection([clip.id]); setRange(null);
    setSelectedClock(null); setSelectedMap(null); selectTracks([clip.trackId]);
    if (editorClipId === clip.id) queueMicrotask(() => document.querySelector<HTMLElement>(".audio-editor")?.focus({ preventScroll: true }));
  };
  const move = (ids: string[], delta: number, targetTrack?: string, copy = false) => {
    if(selectedMaps.length) {
      if(copy){tell("Copy currently requires an audio-only selection.");return;}
      moveSelectedArrangement(delta,{clips:ids,maps:selectedMaps});return;
    }
    const p = projectRef.current, next = moveClips(p, ids, delta, linked, targetTrack, copy);
    commit(next, copy ? "Copy events" : "Move events");
    if (!copy && next !== p) {
      const primary = next.clips.find((c) => c.id === ids[0]);
      const tracks = [...new Set(relatedClips(next, ids, linked).map((c) => c.trackId))];
      if (primary) selectTracks(tracks, primary.trackId);
    }
    if (copy && next !== p) {
      const before = new Set(p.clips.map((c) => c.id));
      const copied = next.clips.filter((c) => !before.has(c.id));
      const originals = relatedClips(p, ids, linked);
      const primary = copied[originals.findIndex((c) => c.id === ids[0])] ?? copied[0];
      selectCopies(next, [primary.id, ...copied.filter((c) => c.id !== primary.id).map((c) => c.id)]);
      if (editorClipId && ids.includes(editorClipId)) setEditorClipId(copied[originals.findIndex((c) => c.id === editorClipId)]?.id ?? null);
    }
  };
  const editRange = (value: TimeRange, delta: number, targetTrack?: string, copy = false) => {
    const result = moveRange(projectRef.current, value, delta, linked, targetTrack, copy);
    commit(result.project, copy ? "Copy audio range" : "Move audio range");
    selectCopies(result.project, result.ids, result.range);
  };
  const trim = (ids: string[], edge: "start" | "end", delta: number) =>
    change((p) => trimClips(p, ids, edge, delta, linked), `Trim event ${edge}`);
  const audioValuePreview = (edge: "move" | "end", original: number) => {
    const base = project, ids = selection, useLinked = linked, owner = session.current;
    return (value: number) => {
      if (session.current !== owner || projectRef.current.id !== base.id) return;
      const next = edge === "move" ? moveClips(base, ids, value - original, useLinked)
        : trimClips(base, ids, edge, value - original, useLinked);
      projectRef.current = next;
      setProject(next);
    };
  };
  const split = (ids: string[], time: number) => {
    const p = projectRef.current, next = splitClips(p, ids, time, linked);
    if (next === p) return;
    const before = new Set(p.clips.map((c) => c.id));
    const affected = new Set(relatedClips(p, ids, linked).map((c) => c.id));
    commit(next, "Split events");
    setSelection(next.clips.filter((c) => affected.has(c.id) || !before.has(c.id)).map((c) => c.id));
    setRange(null); setSelectedMap(null); setSelectedClock(null);
  };
  const removeSavedClock = (id: string) => {
    change((p) => p.clocks.some((c) => c.id === id) ? { ...p, clocks: p.clocks.filter((c) => c.id !== id) } : p, "Remove saved clock");
    setSelectedClock(null);
  };
  const remove = (ids = selection) => {
    if (selectedMaps.length && ids === selection) {
      const tempoIds=new Set(selectedMaps.filter(item=>item.kind==="tempo").map(item=>item.id));
      const signatureIds=new Set(selectedMaps.filter(item=>item.kind==="signature").map(item=>item.id));
      change(p=>editProjectMap(removeClips(p,selection,linked),
        p.tempos.filter(event=>!tempoIds.has(event.id)),
        p.signatures.filter(event=>!signatureIds.has(event.id))),"Delete selected arrangement items");
      setArrangement({clips:[],maps:[]});setMapFocus(null);setSelectedClock(null);return;
    }
    if (range && range.end > range.start && ids === selection) {
      change((p) => removeRange(p, range, linked), "Delete selected audio range");
    } else change((p) => removeClips(p, ids, linked), "Delete events");
    setSelection([]); setSelectedClock(null);
  };
  const updateTrack = (id: string, fields: Partial<Track>) => change((p) => {
    const track = p.tracks.find((t) => t.id === id);
    const committedTrack = history.current.current.tracks.find((t) => t.id === id);
    if (!track || (committedTrack && Object.entries(fields).every(([key, value]) => committedTrack[key as keyof Track] === value))) {
      setProject(p); return p;
    }
    return { ...p, tracks: p.tracks.map((t) => t.id === id ? { ...t, ...fields } : t) };
  }, "Edit track");
  const timeBase = (id: string) => change((p) => {
    const current = p.tracks.find((t) => t.id === id)!;
    return setTrackTimeBase(p, id, current.timeBase === "linear" ? "musical" : "linear");
  }, "Switch track time base");
  const selectArrangement=(value:ArrangementSelection,primary?:MapSelection)=>{
    const current=projectRef.current;
    const clips=[...new Set(value.clips)].filter(id=>current.clips.some(clip=>clip.id===id));
    const maps=value.maps.filter((item,index,items)=>items.findIndex(other=>other.id===item.id&&other.kind===item.kind)===index&&
      (item.kind==="tempo"?current.tempos:current.signatures).some(event=>event.id===item.id));
    setArrangement({clips,maps});setRange(null);setSelectedClock(null);closeMenu();
    const focus=primary&&maps.some(item=>item.id===primary.id&&item.kind===primary.kind)?primary:clips.length?null:maps[0]??null;
    setMapFocus(focus);
    const tracks=[...new Set(clips.map(id=>current.clips.find(clip=>clip.id===id)!.trackId))];
    selectTracks(focus?[]:tracks,focus?null:tracks[0]??null);setInspector(true);
  };
  const chooseMap = (selected: MapSelection,additive=false) => {
    const exists=selectedMaps.some(item=>item.id===selected.id&&item.kind===selected.kind);
    selectArrangement({clips:additive?selection:[],maps:additive?
      exists?selectedMaps.filter(item=>item.id!==selected.id||item.kind!==selected.kind):[...selectedMaps,selected]:[selected]},selected);
  };
  const moveSelectedArrangement=(delta:number,value:ArrangementSelection=arrangement)=>{
    try{commit(moveArrangement(projectRef.current,value,delta,linked),"Move arrangement selection");setRange(null);}
    catch(e){tell(e instanceof Error?e.message:String(e));}
  };
  const updateTempo = (event: TempoEvent) => {
    const next = putTempo(projectRef.current, event);
    commit(next, "Edit project tempo");
    if (selectedMap?.id === event.id) setSelectedMap({ kind: "tempo", id: next.tempos.find((t) => Math.abs(t.quarter - Math.max(0, event.quarter)) < 1e-8)!.id });
  };
  const updateSignature = (event: SignatureEvent) => {
    const next = putSignature(projectRef.current, event);
    commit(next, "Edit project signature");
    if (selectedMap?.id === event.id) setSelectedMap({ kind: "signature", id: next.signatures.find((s) => s.id === event.id)?.id ?? next.signatures.find((s) => s.quarter === event.quarter)!.id });
  };
  const addMap = (kind: "tempo" | "signature", time: number) => {
    if (kind === "tempo") {
      const quarter = quarterAtTime(project, Math.max(0, time));
      const current = project.tempos.find((t) => Math.abs(t.quarter - quarter) < 1e-8);
      const event: TempoEvent = { id: current?.id ?? uid(), quarter, bpm: tempoAtQuarter(project, quarter).bpm, origin: "manual" };
      updateTempo(event); chooseMap({ kind, id: event.id });
    } else {
      const quarter = quarterAtTime(project, snapToProject(project, time, "beat"));
      const position = positionAtQuarter(project, quarter);
      const current = project.signatures.find((s) => Math.abs((s.quarter ?? 0)-quarter)<1e-8);
      const event: SignatureEvent = { id: current?.id ?? uid(), quarter, bar: Math.max(1, position.bar), numerator: position.signature.numerator, denominator: position.signature.denominator, origin: "manual" };
      updateSignature(event); chooseMap({ kind, id: event.id });
    }
  };
  const removeMap = (selected: MapSelection) => {
    const event = selected.kind === "tempo" ? project.tempos.find((t) => t.id === selected.id) : project.signatures.find((s) => s.id === selected.id);
    if (!event) return;
    change((p) => selected.kind === "tempo" ? editProjectMap(p, p.tempos.filter((t) => t.id !== selected.id)) : editProjectMap(p, undefined, p.signatures.filter((s) => s.id !== selected.id)), "Remove project map event");
    setSelectedMap(null);
  };
  const moveMap = (selected: MapSelection, time: number, bpm?: number) => {
    const current = projectRef.current;
    const event = selected.kind === "tempo" ? current.tempos.find(t => t.id === selected.id) : current.signatures.find(s => s.id === selected.id);
    if (!event) return;
    const originalTime = selected.kind === "tempo" ? timeAtQuarter(current, (event as TempoEvent).quarter) : timeAtBar(current, (event as SignatureEvent).bar);
    try {
      let next = moveArrangement(current, { clips: [], maps: [selected] }, time - originalTime, false);
      if (selected.kind === "tempo" && bpm !== undefined) {
        const moved = next.tempos.find(t => t.id === selected.id)!;
        if (moved.bpm !== bpm) next = putTempo(next, { ...moved, bpm, origin: "manual" });
      }
      commit(next, "Move project map point");
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); }
  };
  const tempoFromCursor = (bpm: number, at?: number) => {
    const current = projectRef.current;
    const quarter = quarterAtTime(current, at ?? engine.current?.position ?? position);
    const existing = current.tempos.find((event) => Math.abs(event.quarter - quarter) < 1e-8);
    commit(putTempo(current, { id: existing?.id ?? uid(), quarter, bpm, origin: "manual" }), "Declare tempo at cursor");
  };
  const signatureFromCursor = (fields: Partial<TimeSignature>, at?: number) => {
    const current = projectRef.current;
    const quarter = quarterAtTime(current, at ?? engine.current?.position ?? position);
    const basis = positionAtQuarter(current, quarter).signature;
    const signature = { numerator: fields.numerator ?? basis.numerator, denominator: fields.denominator ?? basis.denominator };
    if (!current.signatures.length) {
      commit(editProjectMap(current, undefined, undefined, { signature }), "Set whole-project signature");
      return true;
    }
    const cursor = positionAtQuarter(current, quarter);
    const beats = (quarter-cursor.barStart)*cursor.signature.denominator/4;
    if (Math.abs(beats-Math.round(beats)) > 1e-8) {
      tell("Move the cursor to an existing beat boundary to declare a signature point.");
      return false;
    }
    const existing = current.signatures.find(event => Math.abs((event.quarter??0)-quarter)<1e-8);
    commit(putSignature(current, { id: existing?.id ?? uid(), quarter, bar: cursor.bar, ...signature, origin: "manual" }), "Declare signature at cursor");
    return true;
  };
  const previewTrack = (id: string, fields: Partial<Track>) =>
    setProject((p) => ({
      ...p,
      tracks: p.tracks.map((t) => (t.id === id ? { ...t, ...fields } : t)),
    }));
  const afterTracks = (ids = trackSelection.current.ids) => {
    const tracks = projectRef.current.tracks;
    const last = Math.max(-1, ...tracks.map((track, index) => ids.includes(track.id) ? index : -1));
    return last >= 0 ? tracks[last + 1]?.id ?? null : selectedMap ? tracks[0]?.id ?? null : null;
  };
  const addTrack = (beforeTrackId: string | null = afterTracks()) => {
    setAddBeforeTrack(beforeTrackId); closeMenu(); setModal("add-track");
  };
  const addTracks = (name: string, count: number) => {
    try {
      const p = projectRef.current, next = addAudioTracks(p, count, name, addBeforeTrack);
      const ids = next.tracks.filter((track) => !p.tracks.some((original) => original.id === track.id)).map((track) => track.id);
      commit(next, count === 1 ? "Add audio track" : "Add audio tracks");
      selectTracks(ids, ids[0]); setSelection([]); setRange(null); setSelectedClock(null); setSelectedMap(null); setModal(null);
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); }
  };
  const duplicateTrackSelection = (ids = trackSelection.current.ids) => {
    const p = projectRef.current, next = duplicateTracks(p, ids);
    if (next === p) return;
    const copies = next.tracks.filter((track) => !p.tracks.some((original) => original.id === track.id)).map((track) => track.id);
    commit(next, "Duplicate tracks"); selectTracks(copies, copies[0]);
    setSelection([]); setRange(null); setSelectedClock(null); setSelectedMap(null); closeMenu();
  };
  const performRemoveTracks = (ids: string[]) => {
    const p = projectRef.current, first = p.tracks.findIndex((track) => ids.includes(track.id)), next = removeTracks(p, ids);
    commit(next, "Remove tracks");
    const remaining = trackSelection.current.ids.filter((id) => !ids.includes(id));
    const fallback = next.tracks[Math.min(Math.max(0, first), next.tracks.length - 1)]?.id;
    selectTracks(remaining.length ? remaining : fallback ? [fallback] : []);
    setSelection((selected) => selected.filter((id) => next.clips.some((clip) => clip.id === id)));
    setRange((value) => {
      if (!value) return null;
      const trackIds = value.trackIds.filter((id) => next.tracks.some((track) => track.id === id));
      return trackIds.length ? { ...value, trackIds } : null;
    });
    closeMenu(); setModal(null);
  };
  const removeTrackSelection = (ids = trackSelection.current.ids) => {
    const p = projectRef.current, current = ids.filter((id) => p.tracks.some((track) => track.id === id));
    if (!current.length) return;
    closeMenu();
    if (p.clips.some((clip) => current.includes(clip.trackId))) { setRemovingTracks(current); setModal("remove-tracks"); }
    else performRemoveTracks(current);
  };
  const trackEvents = (ids = trackSelection.current.ids) => {
    const p = projectRef.current;
    selectTracks(ids, ids.includes(trackSelection.current.active ?? "") ? trackSelection.current.active : ids[0]);
    setSelection(p.clips.filter((clip) => ids.includes(clip.trackId)).map((clip) => clip.id));
    setRange(null); setSelectedClock(null); setSelectedMap(null); closeMenu();
  };
  const moveTracks = (ids: string[], beforeTrackId: string | null) => {
    change((p) => reorderTracks(p, ids, beforeTrackId), "Reorder tracks"); closeMenu();
  };
  const moveTrackSelection = (direction: -1 | 1, ids = trackSelection.current.ids) => {
    const p = projectRef.current, indexes = p.tracks.flatMap((track, index) => ids.includes(track.id) ? [index] : []);
    if (!indexes.length) return;
    const first = Math.min(...indexes), last = Math.max(...indexes);
    if (direction < 0 && first > 0) moveTracks(ids, p.tracks[first - 1].id);
    if (direction > 0 && last < p.tracks.length - 1) moveTracks(ids, p.tracks[last + 2]?.id ?? null);
  };
  const openTrackMenu = (id: string | null, x: number, y: number) => trackContext(id, x, y);
  const updateClock = (id: string, fields: Partial<ClockValues>, label = "Edit saved analysis clock") => change((p) => {
    const clock = p.clocks.find((c) => c.id === id);
    if (!clock || Object.entries(fields).every(([key, value]) => clock.values[key as keyof ClockValues] === value)) return p;
    return { ...p, clocks: p.clocks.map((c) => c.id === id ? { ...c, values: { ...c.values, ...fields } } : c) };
  }, label);
  const restoreClockValues = (id: string) => {
    const clock = projectRef.current.clocks.find((c) => c.id === id);
    if (clock) updateClock(id, clock.original, "Restore original prediction values");
  };
  const alignClock = (id: string) => {
    try {
      const p = projectRef.current, saved = p.clocks.find((c) => c.id === id);
      if (!saved) return;
      const placement = placeClockOnProject(p, saved);
      commit(placement.project, "Apply saved analysis and align project");
      tell(`Project grid aligned at bar ${placement.bar}. Song and linked stems moved ${placement.delta >= 0 ? "+" : ""}${placement.delta.toFixed(4)} s.`);
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); }
  };
  const zoom = (factor: number) => timelineViewport.current?.zoom(factor);
  const fit = () =>
    timelineViewport.current?.setScale(
      Math.max(
        0.2,
        Math.min(
          24,
          (document.querySelector(".timeline-scroll")?.clientWidth ?? 900) /
            Math.max(10, projectEnd(project) + 4),
        ),
      ),
    );
  const queueImport = async (paths: string[], options: ImportOptions, owner: number, requestId?: string) => {
    if (!api || owner !== session.current) return;
    if (!paths.length || paths.length > 32) throw new Error("Import between 1 and 32 audio files.");
    if (options.mode === "sequence" && options.targetTrackId && !projectRef.current.tracks.some((track) => track.id === options.targetTrackId))
      throw new Error("Choose an available import target track.");
    const id = requestId ?? uid();
    // Register the immutable destination before IPC starts. A short decode may
    // finish before its invocation promise resolves.
    pendingImports.current.set(id, options);
    jobSessions.current.set(id, { session: owner, kind: "decode" });
    setJobs((list) => [...list, { id, kind: "decode", stage: "Preparing audio", progress: 0 }]);
    try {
      await api.decode(paths, options.copy, id);
      if (owner !== session.current) void api.finishImport(id, false).catch(() => {});
    } catch (error) {
      pendingImports.current.delete(id); jobSessions.current.delete(id);
      if (owner === session.current) setJobs((list) => list.filter((job) => job.id !== id));
      if (owner === session.current) throw error;
    }
  };
  const beginImport = async (paths?: string[], destination?: ImportDestination, review = false, capturedCursor?: number) => {
    if (!api) {
      tell("Use the Windows desktop app to import local audio.");
      return;
    }
    try {
      const owner = session.current, p = projectRef.current;
      const cursor = capturedCursor ?? engine.current?.position ?? position;
      const target = trackSelection.current.active && p.tracks.some((track) => track.id === trackSelection.current.active) ? trackSelection.current.active : null;
      const initial = destination ?? { start: cursor, targetTrackId: target, beforeTrackId: afterTracks(), source: "cursor" as const };
      const snapshot = { session: owner, cursor, end: projectEnd(p), drop: initial.start };
      const chosen = paths ?? (await api.chooseAudio());
      if (owner !== session.current) return;
      if (chosen.length) {
        if (destination && chosen.length === 1 && !review) {
          await queueImport(chosen, { ...initial, mode: "sequence", copy: copyMedia }, owner);
          return;
        }
        importSnapshot.current = snapshot;
        setImportDestination(initial); setImportStart(initial.start);
        setImportAt(destination ? "drop" : "cursor");
        if (destination?.source === "track-list" && importMode === "sequence") setImportMode("tracks");
        setImportPaths(chosen);
        setModal("import");
        closeMenu();
      }
    } catch (e) {
      tell(String(e));
    }
  };
  const runImport = async () => {
    if (!api || importRequest.current || importSnapshot.current.session !== session.current) return;
    const request = uid(); importRequest.current = request; setImportBusy(true);
    try {
      confirmedImportPrefs.current = { mode: importMode, copy: copyMedia };
      try { localStorage.setItem("joljak.import-preferences", JSON.stringify({ mode: importMode, copy: copyMedia })); } catch { /* Import works without preference storage. */ }
      const options: ImportOptions = {
        mode: importMode,
        copy: copyMedia,
        start: importStart,
        targetTrackId: importDestination.targetTrackId,
        beforeTrackId: importDestination.beforeTrackId,
      };
      await queueImport([...importPaths], options, importSnapshot.current.session, request);
      if (importRequest.current === request) setModal(null);
    } catch (e) {
      if (importRequest.current === request) tell(String(e));
    } finally {
      if (importRequest.current === request) { importRequest.current = null; setImportBusy(false); }
    }
  };
  const importStartKind = (kind: ImportStart) => {
    setImportAt(kind);
    if (kind !== "custom") setImportStart(importSnapshot.current[kind]);
  };
  const closeModal = () => {
    if(modal==="samples"){
      for(const id of pendingSampleImports.current.keys())void api?.cancel(id);
      pendingSampleImports.current.clear();setSampleBusy(false);
    }
    if (modal === "import") {
      setImportMode(confirmedImportPrefs.current.mode);
      setCopyMedia(confirmedImportPrefs.current.copy);
    }
    if (modal === "import" && importRequest.current) {
      const id = importRequest.current; importRequest.current = null; setImportBusy(false);
      pendingImports.current.delete(id);
      void api?.cancel(id).catch(() => {});
      setJobs((list) => list.map((job) => job.id === id ? { ...job, stage: "cancelled" } : job));
    }
    setModal(null);
  };
  const save = async (as = false) => {
    if (!api) return;
    try {
      const result = await api.save(
        projectRef.current,
        as ? null : path,
        as && saveCollect,
      );
      if (result) {
        history.current.saved(result.project);
        projectRef.current = history.current.current;
        setProject(history.current.current);
        setPath(result.path);
        setDirty(false);
        setModal(null);
        tell("Project saved. Original recordings are unchanged.");
      }
    } catch (e) {
      tell(String(e));
    }
  };
  const open = async (filename?: string) => {
    if (filename && path && filename.toLowerCase() === path.toLowerCase()) return;
    if (
      !api ||
      (dirty &&
        !confirm(
          "Open another project? Your current session has an automatic recovery copy.",
        ))
    )
      return;
    try {
      const result = await api.open(filename);
      if (!result) return;
      switchSession();
      engine.current?.reset();
      const opened = upgradeProject(result.project);
      history.current.replace(opened);
      projectRef.current = opened;
      setProject(opened);
      setPath(result.path);
      setDirty(false);
      setSelection([]);
      setRange(null);
      setSelectedClock(null);
      setSelectedMap(null);
      setPreviewing(false);
      setPendingAnalysis(null);
      setPosition(0);
      setLoop({ start: 0, end: 0, enabled: false });
      peaks.current.clear();
      void loadPeaks(result.project.assets);
      if (result.missing.length)
        tell(`Missing audio: ${result.missing.join(", ")}`);
      else if (Number(result.project.version) === 1 && result.project.clocks.length)
        tell("Saved analysis clocks were preserved. Choose Apply & Align to place them on the new project tempo and signature tracks.");
    } catch (e) {
      tell(String(e));
    }
  };
  openProject.current = open;
  const newProject = () => {
    if (
      dirty &&
      !confirm(
        "Create a new project? Your current session has an automatic recovery copy.",
      )
    )
      return;
    engine.current?.reset();
    switchSession();
    const p = createProject();
    history.current.replace(p);
    projectRef.current = p;
    setProject(p);
    setPath(null);
    setDirty(false);
    setSelection([]);
    setRange(null);
    setSelectedClock(null);
    setSelectedMap(null);
    setPreviewing(false);
    setPendingAnalysis(null);
    setPosition(0);
    setLoop({ start: 0, end: 0, enabled: false });
    peaks.current.clear();
  };

  const beginAnalysis = (explicit?: Clip, capturedRange?: TimeRange | null) => {
    const project = projectRef.current;
    const range = capturedRange !== undefined ? capturedRange : rangeRef.current;
    const refTrack = activeTrack ?? range?.trackIds[0];
    const intersecting =
      range && range.end > range.start
        ? project.clips.filter(
            (c) =>
              c.trackId === refTrack &&
              c.start < range.end &&
              clipEnd(c) > range.start,
          )
        : [];
    const clip =
      explicit ??
      (range && range.end > range.start
        ? intersecting.length === 1
          ? intersecting[0]
          : undefined
        : selectedClip);
    if (!clip) {
      tell(
        range
          ? "Select a range within one reference audio event. Analyze different songs separately."
          : "Select a song event to analyze its entire length, or select a range inside it.",
      );
      return;
    }
    const asset = getAsset(project, clip);
    if (!asset) return;
    const useRange =
      range &&
      range.end > range.start &&
      range.trackIds.includes(clip.trackId) &&
      range.start < clipEnd(clip) &&
      range.end > clip.start;
    const start = useRange ? Math.max(clip.start, range!.start) : clip.start;
    const end = useRange ? Math.min(clipEnd(clip), range!.end) : clipEnd(clip);
    setScope({
      clipId: clip.id,
      asset,
      start,
      end,
      sourceStart: clip.sourceStart + start - clip.start,
      sourceEnd: clip.sourceStart + end - clip.start,
      whole: !useRange,
      name: clip.name,
    });
    setTap("");
    setTapCount(0);
    tapTimes.current = [];
    setModal("analyze");
    closeMenu();
  };
  const tapNow = () => {
    const now = performance.now(),
      previous = tapTimes.current.at(-1);
    const button = document.querySelector<HTMLButtonElement>(".tap-button");
    const pressed = { transform: "translateY(2px) scale(.96)", backgroundColor: "#58957c", borderColor: "#a4ddc5", boxShadow: "inset 0 2px 4px #0006" };
    button?.getAnimations().forEach((animation) => animation.cancel());
    button?.animate([pressed, { ...pressed, offset: .6 },
      { transform: "none", backgroundColor: "#294b41", borderColor: "#4f8073", boxShadow: "none" }],
      { duration: 120, easing: "ease-out" });
    if (previous && now - previous > 2500) tapTimes.current = [];
    tapTimes.current.push(now);
    if (tapTimes.current.length > 9) tapTimes.current.shift();
    setTapCount(tapTimes.current.length);
    const differences = tapTimes.current
      .slice(1)
      .map((time, index) => time - tapTimes.current[index])
      .filter((delta) => delta > 100)
      .sort((a, b) => a - b);
    if (differences.length)
      setTap(
        (60000 / differences[Math.floor(differences.length / 2)]).toFixed(1),
      );
  };
  const analyze = async () => {
    if (!api || !scope) return;
    const value = tap.trim() ? Number(tap) : null;
    if (value !== null && (!Number.isFinite(value) || value <= 0)) {
      tell("Enter a positive approximate BPM, or leave it empty.");
      return;
    }
    try {
      const owner = session.current;
      const id = await api.analyze(
        scope.asset,
        scope.sourceStart,
        scope.sourceEnd,
        value,
        scope.clipId,
      );
      jobSessions.current.set(id, { session: owner, kind: "analyze" });
      setJobs((list) => [
        ...list,
        { id, kind: "analyze", stage: "Starting audio analysis" },
      ]);
      setPendingAnalysis(null);
      setModal(null);
    } catch (e) {
      tell(String(e));
    }
  };
  const apply = () => {
    if (!pendingAnalysis) return;
    try {
      const saved = applyAnalysis(projectRef.current, pendingAnalysis), clock = saved.clocks.at(-1)!;
      const placement = placeClockOnProject(saved, clock);
      commit(placement.project, "Apply analysis and align song to project grid");
      setSelectedClock(clock.id);
      setSelectedMap(null);
      setSelection([pendingAnalysis.clipId]);
      const selectedTrack = saved.clips.find((c) => c.id === pendingAnalysis.clipId)?.trackId;
      selectTracks(selectedTrack ? [selectedTrack] : []);
      setPendingAnalysis(null);
      tell(`Clock applied at bar ${placement.bar}. Song and linked stems moved ${placement.delta >= 0 ? "+" : ""}${placement.delta.toFixed(4)} s.`);
    } catch (e) { tell(e instanceof Error ? e.message : String(e)); }
  };
  const audition = async () => {
    setReferencePreview(null);
    if (!pendingAnalysis?.result.period_seconds || !engine.current) return;
    const preview = applyAnalysis(projectRef.current, pendingAnalysis),
      c = preview.clips.find((c) => c.id === pendingAnalysis.clipId);
    if (!c) return;
    const geometry = clockGeometry(preview, preview.clocks.at(-1)!);
    previewClocks.current = geometry ? [geometry] : [];
    engine.current.updateProject(projectRef.current, previewClocks.current);
    setPreviewing(true);
    engine.current.setClick(true, project.clickGain ?? DEFAULT_CLICK_GAIN);
    const start = c.start + pendingAnalysis.sourceStart - c.sourceStart;
    await engine.current.play(start).catch((e) => tell(e.message));
    setMetronome(true);
  };
  const auditionClock = async (saved: Clock) => {
    setReferencePreview(null);
    const geometry = clockGeometry(project, saved);
    if (!geometry || !engine.current) return;
    previewClocks.current = [geometry];
    setPreviewing(true);
    engine.current.updateProject(project, previewClocks.current);
    engine.current.setClick(true, project.clickGain);
    setMetronome(true);
    await engine.current.play(geometry.start).catch((e) => tell(e.message));
  };
  const clipboard = useRef<AudioClipboard | null>(null);
  const groupSelection = (group: boolean, selected = selection, useLinked = linked) => {
    const clips = relatedClips(projectRef.current, selected, useLinked);
    if (!clips.length || (group && clips.every((c) => c.groupId && c.groupId === clips[0].groupId)) || (!group && clips.every((c) => !c.groupId))) return;
    const id = group ? uid() : null;
    const ids = new Set(clips.map((c) => c.id));
    change(
      (p) => ({
        ...p,
        clips: p.clips.map((c) => (ids.has(c.id) ? { ...c, groupId: id } : c)),
      }),
      group ? "Group events" : "Ungroup events",
    );
  };
  const captureEdit = (fields: Partial<EditContext> = {}): EditContext => ({
    projectId: projectRef.current.id, owner: session.current,
    selection: structuredClone(arrangement), range: range && range.end > range.start ? structuredClone(range) : null,
    linked, cursor: engine.current?.position ?? position, trackId: trackSelection.current.active,
    ...fields,
  });
  const contextValid = (context: EditContext) => {
    const current = projectRef.current;
    return context.owner === session.current && context.projectId === current.id &&
      context.selection.clips.every(id => current.clips.some(clip => clip.id === id)) &&
      context.selection.maps.every(point => (point.kind === "tempo" ? current.tempos : current.signatures).some(item => item.id === point.id)) &&
      (!context.trackId || current.tracks.some(track => track.id === context.trackId)) &&
      (!context.range || context.range.trackIds.every(id => current.tracks.some(track => track.id === id)));
  };
  const contextBounds = (context: EditContext) => context.range ? { start: context.range.start, end: context.range.end } :
    arrangementBounds(projectRef.current, context.selection, context.linked);
  const editContext = (command: string, context = captureEdit()) => {
    if (!contextValid(context)) { tell("The menu target is no longer available."); return; }
    const current = projectRef.current, ids = context.selection.clips, maps = context.selection.maps;
    const audioOnly = !maps.length;
    if (["copy", "cut", "paste", "duplicate", "split", "split-here", "split-range", "group", "ungroup", "front", "back"].includes(command) && !audioOnly) return;
    const erase = () => {
      let next = context.range ? removeRange(current, context.range, context.linked) : removeClips(current, ids, context.linked);
      if (maps.length) next = editProjectMap(next,
        next.tempos.filter(point => !maps.some(item => item.kind === "tempo" && item.id === point.id)),
        next.signatures.filter(point => !maps.some(item => item.kind === "signature" && item.id === point.id)));
      commit(next, context.range ? "Delete selected audio range" : maps.length ? "Delete arrangement selection" : "Delete events");
      setArrangement({ clips: [], maps: [] }); setMapFocus(null); setSelectedClock(null);
    };
    if (command === "copy" || command === "cut") {
      const data = copyAudio(current, ids, context.range, context.linked);
      if (!data) return;
      clipboard.current = data;
      if (command === "cut") erase();
      else tell(data.kind === "range" ? "Copied audio range, including gaps." : `Copied ${data.clips.length} audio events.`);
    } else if (command === "delete") erase();
    else if (command === "paste" || command === "paste-here") {
      const data = clipboard.current; if (!data) return;
      if (context.trackId && !current.tracks.some(track => track.id === context.trackId)) { tell("The destination track was removed."); return; }
      const result = pasteAudio(current, data, command === "paste-here" ? context.point ?? context.cursor : context.cursor, context.trackId);
      commit(result.project, data.kind === "range" ? "Paste audio range" : "Paste events"); selectCopies(result.project, result.ids, result.range);
    } else if (command === "duplicate") {
      const bounds = contextBounds(context); if (!bounds) return;
      const data = copyAudio(current, ids, context.range, context.linked); if (!data) return;
      const result = pasteAudio(current, data, bounds.end, data.tracks[0]?.id);
      const primary = result.ids[data.clips.findIndex(clip => clip.id === ids[0])];
      commit(result.project, "Duplicate audio"); selectCopies(result.project, primary ? [primary, ...result.ids.filter(id => id !== primary)] : result.ids, result.range);
    } else if (["split", "split-here", "split-range"].includes(command)) {
      const targets = context.range ? current.clips.filter(clip => context.range!.trackIds.includes(clip.trackId)).map(clip => clip.id) : ids;
      const times = command === "split-range" && context.range ? [context.range.start, context.range.end] : [command === "split-here" ? context.point ?? context.cursor : context.cursor];
      const before = new Set(current.clips.map(clip => clip.id));
      const affected = new Set(relatedClips(current, targets, context.linked).map(clip => clip.id));
      let next = current;
      for (const at of times) {
        const available = next.clips.filter(clip => affected.has(clip.id) || !before.has(clip.id)).map(clip => clip.id);
        next = splitClips(next, available, at, context.linked);
      }
      if (next !== current) {
        commit(next, command === "split-range" ? "Split range boundaries" : "Split events");
        if (!context.range) selectCopies(next, next.clips.filter(clip => affected.has(clip.id) || !before.has(clip.id)).map(clip => clip.id));
      }
    } else if (command === "locators") {
      const bounds = contextBounds(context); if (bounds && bounds.end > bounds.start) setLoop(value => ({ ...value, start: bounds.start, end: bounds.end }));
    } else if (command === "group" || command === "ungroup") groupSelection(command === "group", ids, context.linked);
    else if (command === "front" || command === "back") change(value => orderClips(value, ids, command === "front", context.linked), command === "front" ? "Move events to front" : "Move events to back");
  };
  const showPopup = (value: MenuPopup, available?: () => boolean) => {
    cancelMenuGestures();
    const owner = session.current, projectId = projectRef.current.id;
    const guard = (entries: MenuEntry[]): MenuEntry[] => entries.map(entry => ({ ...entry,
      submenu: entry.submenu ? guard(entry.submenu) : undefined,
      action: entry.action ? () => {
        if (session.current !== owner || projectRef.current.id !== projectId || available && !available()) { tell("The menu target is no longer available."); return; }
        try { const result = entry.action!(); if (result instanceof Promise) void result.catch(error => tell(error.message ?? String(error))); }
        catch (error) { tell(error instanceof Error ? error.message : String(error)); }
      } : undefined,
    }));
    setPopup({ ...value, items: guard(value.items) });
  };
  const controlContext = (event: React.MouseEvent) => {
    if (event.defaultPrevented || editableText(event.target)) return;
    const target = event.target as HTMLElement, actions = captureControlContext(target);
    if (!actions) return;
    event.preventDefault(); event.stopPropagation();
    showPopup({ x: event.clientX, y: event.clientY, title: actions.label, items: controlMenuItems(actions),
      invoker: target.closest<HTMLElement>("[data-value-control]")?.querySelector("input") ?? target.closest<HTMLElement>("[data-slider-control]"),
      restoreFocus: actions.restoreFocus }, actions.valid);
  };
  const trackContext = (id: string | null, x: number, y: number) => {
    const ids = id ? trackSelection.current.ids.includes(id) ? [...trackSelection.current.ids] : selectTrack(id, { ctrl: false, shift: false }, true) : [];
    const current = projectRef.current, focused = current.tracks.find(track => track.id === id), separator: MenuEntry = { separator: true };
    const cursor = engine.current?.position ?? position, beforeTrackId = ids.length ? afterTracks(ids) : null;
    const valid = () => ids.every(id => projectRef.current.tracks.some(track => track.id === id));
    const empty = !ids.length ? "Select a track" : undefined;
    const rename = () => { const node = document.querySelector<HTMLElement>(`[data-track-id="${id}"] .track-name`); node?.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); };
    showPopup({ x, y, title: focused ? ids.length > 1 ? `${ids.length} tracks` : focused.name : undefined,
      invoker: id ? document.querySelector<HTMLElement>(`[data-track-id="${id}"]`) : document.querySelector<HTMLElement>(".arrangement"), items: [
        { id: "add-track", label: "Add Audio Track…", action: () => addTrack(ids.length ? afterTracks(ids) : null) },
        ...(!id ? [{ id: "import", label: "Import Audio…", action: () => beginImport(undefined,
          { start: cursor, targetTrackId: null, beforeTrackId, source: "cursor" }, true, cursor) }] : [
          separator,
          { id: "track-events", label: "Select All Events", action: () => trackEvents(ids) },
          { id: "duplicate-tracks", label: "Duplicate Tracks", action: () => duplicateTrackSelection(ids) },
          { label: "Rename…", disabled: ids.length !== 1 ? "Choose one track to rename" : undefined, action: rename }, separator,
          { id: "tracks-up", label: "Move Up", disabled: ids.includes(current.tracks[0]?.id) ? "Track is already first" : empty, action: () => moveTrackSelection(-1, ids) },
          { id: "tracks-down", label: "Move Down", disabled: ids.includes(current.tracks.at(-1)?.id ?? "") ? "Track is already last" : empty, action: () => moveTrackSelection(1, ids) },
          { label: "Time Base", disabled: ids.length !== 1 ? "Choose one track to change time base" : undefined, submenu: [
            { label: "Linear", checked: focused?.timeBase === "linear", action: () => change(value => setTrackTimeBase(value, ids[0], "linear"), "Track time base") },
            { label: "Musical", checked: focused?.timeBase === "musical", action: () => change(value => setTrackTimeBase(value, ids[0], "musical"), "Track time base") },
          ] }, separator,
          { id: "remove-tracks", label: "Remove Tracks…", shortcut: "Shift Del", danger: true, action: () => removeTrackSelection(ids) },
        ]),
      ] }, valid);
  };
  const arrangementContext = (target: ArrangementContext) => {
    cancelMenuGestures();
    const current = projectRef.current;
    const selection = target.selection ?? { clips: [], maps: [] };
    if (target.domain === "audio" || target.domain === "map") {
      const same = JSON.stringify(selection) === JSON.stringify(arrangement);
      if (!same) {
        setArrangement(selection); setRange(null); setSelectedClock(null);
        setMapFocus(target.domain === "map" ? target.map ?? null : null);
      }
      if (target.domain === "audio" && target.trackId && !same) selectTrack(target.trackId, { ctrl: false, shift: false }, true);
    }
    const context = captureEdit({ selection, range: target.domain === "range" || target.domain === "editor" ? target.range ?? null : null,
      trackId: target.trackId ?? trackSelection.current.active, point: target.time });
    const clips = relatedClips(current, selection.clips, context.linked), bounds = contextBounds(context);
    const mixed = !!selection.maps.length && !!selection.clips.length;
    const separator: MenuEntry = { separator: true };
    const action = (id: string, label: string, shortcut?: string, disabled?: string): MenuEntry => ({ id, label, shortcut, disabled, action: () => editContext(id, context) });
    const mapClipboard = selection.maps.length ? "Audio clipboard cannot include tempo/signature points" : undefined;
    const pasteReason = mapClipboard ?? (!clipboard.current ? "No copied audio" : undefined);
    const lead = current.clips.find(clip => clip.id === selection.clips[0]);
    let title: string | undefined, entries: MenuEntry[] = [];
    if (target.domain === "audio" || target.domain === "editor") {
      const clicked = current.clips.find(clip => clip.id === target.clipId); if (!clicked) return;
      title = mixed ? "Selection" : clips.length > 1 ? `${clips.length} events` : clicked.name;
      const overlap = [...current.clips].reverse().filter(clip => clip.trackId === clicked.trackId && clip.start <= target.time && clipEnd(clip) > target.time);
      entries = [action("cut", "Cut", "Ctrl X", mapClipboard), action("copy", "Copy", "Ctrl C", mapClipboard), action("paste", "Paste", "Ctrl V", pasteReason), separator,
        action("duplicate", "Duplicate", "Ctrl D", mapClipboard),
        action("split-here", "Split Here", undefined, mapClipboard ?? (!clips.some(clip => target.time > clip.start && target.time < clipEnd(clip)) ? "Pointer is outside the selected events" : undefined)),
        action("split", "Split at Cursor", "Alt X", mapClipboard ?? (!clips.some(clip => context.cursor > clip.start && context.cursor < clipEnd(clip)) ? "Cursor is outside the selected events" : undefined)),
        { label: "Group", submenu: [action("group", "Group", "Ctrl G", mapClipboard), action("ungroup", "Ungroup", "Ctrl U", mapClipboard)] }, separator,
        { id: "analyze", label: "Analyze Audio…", action: () => { const source = projectRef.current.clips.find(clip => clip.id === (lead?.id ?? clicked.id)); if (source) beginAnalysis(source, context.range); } },
        action("locators", "Locators to Selection", "P", !bounds || bounds.end <= bounds.start ? "Selection has no duration" : undefined),
        { id: "editor", label: "Open Audio Editor", shortcut: "Ctrl E", action: () => { const clip = projectRef.current.clips.find(clip => clip.id === clicked.id); if (clip) editAudio(clip); } },
        { label: "Order", submenu: [action("front", "Move to Front", "U", mapClipboard), action("back", "Move to Back", "Shift U", mapClipboard)] },
        ...(overlap.length > 1 ? [{ label: "Select Event", submenu: overlap.map(clip => ({ label: clip.name, checked: clip.id === clicked.id, action: () => {
          selectArrangement({ clips: [clip.id], maps: [] });
        } })) }] : []), separator,
        { ...action("delete", mixed ? "Delete Selection" : "Delete Events", "Del"), danger: true },
      ];
    } else if (target.domain === "range" && context.range) {
      const range = context.range, references = current.clips.filter(clip => clip.trackId === context.trackId && clip.start < range.end && clipEnd(clip) > range.start);
      const reference = references.length === 1 ? references[0] : null;
      title = `Range · ${range.trackIds.length} tracks`;
      entries = [action("cut", "Cut Range", "Ctrl X"), action("copy", "Copy Range", "Ctrl C"), action("paste", "Paste", "Ctrl V", pasteReason), separator,
        action("duplicate", "Duplicate Range", "Ctrl D"), action("split-range", "Split at Range Edges", "Shift X"), separator,
        { id: "analyze", label: "Analyze Range…", disabled: !reference ? "Choose one reference audio event for this range" : undefined, action: () => { const clip = projectRef.current.clips.find(clip => clip.id === reference?.id); if (clip) beginAnalysis(clip, range); } },
        action("locators", "Locators to Range", "P"), separator, { ...action("delete", "Delete Contents", "Del"), danger: true }];
    } else if (target.domain === "lane") {
      title = current.tracks.find(track => track.id === target.trackId)?.name;
      entries = [action("paste-here", "Paste Here", undefined, !clipboard.current ? "No copied audio" : undefined),
        { id: "import", label: "Import Audio Here…", action: () => beginImport(undefined, { start: target.time, targetTrackId: target.trackId ?? null, beforeTrackId: null, source: "timeline" }, false, context.cursor) },
        separator, { id: "add-track", label: "Add Audio Track…", action: () => addTrack(target.trackId ? afterTracks([target.trackId]) : null) }];
    } else if (target.domain === "ruler") {
      title = "Ruler";
      const selected = captureEdit(); const selectedBounds = contextBounds(selected);
      entries = [{ label: "Move Cursor Here", action: () => seek(target.time) }, separator,
        { label: "Set Left Locator", action: () => setLoop(value => ({ ...value, start: target.time, end: Math.max(target.time + .001, value.end) })) },
        { label: "Set Right Locator", action: () => setLoop(value => ({ ...value, start: Math.min(value.start, Math.max(0, target.time - .001)), end: target.time })) },
        { label: "Locators to Selection", shortcut: "P", disabled: !selectedBounds || selectedBounds.end <= selectedBounds.start ? "Select events or a range" : undefined, action: () => editContext("locators", selected) },
        { id: "cycle", label: "Cycle", checked: loop.enabled, action: () => setLoop(value => ({ ...value, enabled: !value.enabled })) }, separator,
        { label: "Time Format", submenu: [
          { label: "Bars + Beats", checked: current.rulerFormat === "bars", action: () => change(value => ({ ...value, rulerFormat: "bars" }), "Ruler time format") },
          { label: "Seconds", checked: current.rulerFormat === "seconds", action: () => change(value => ({ ...value, rulerFormat: "seconds" }), "Ruler time format") },
        ] }, { label: "Tempo / Signature", checked: showMaps, action: toggleMaps }];
    } else if (target.domain === "map") {
      title = mixed ? "Selection" : target.map?.kind === "tempo" ? "Tempo" : "Signature";
      entries = [{ label: "Edit Properties", action: () => document.querySelector<HTMLInputElement>(".info-line input")?.focus() },
        ...(mixed ? [action("copy", "Copy", "Ctrl C", mapClipboard), action("cut", "Cut", "Ctrl X", mapClipboard)] : []), separator,
        { ...action("delete", mixed || selection.maps.length > 1 ? "Delete Selection" : target.map?.kind === "tempo" ? "Delete Tempo Point" : "Delete Signature Point", "Del"), danger: true }];
    } else if (target.domain === "map-lane") {
      entries = [{ label: target.mapKind === "tempo" ? "Add Tempo Here…" : "Add Signature at Beat…", action: () => addMap(target.mapKind!, target.time) },
        separator, { label: "Hide Tempo / Signature", action: toggleMaps }];
    }
    showPopup({ x: target.x, y: target.y, title, items: entries, invoker: target.invoker ?? document.querySelector<HTMLElement>(".arrangement") }, () => contextValid(context));
  };
  const openAppMenu = (name: string) => {
    if (appMenu === name) { closeMenu(); return; }
    const node = document.querySelector<HTMLElement>(`.menus [data-menu="${name}"]`), box = node?.getBoundingClientRect();
    const context = captureEdit(), separator: MenuEntry = { separator: true };
    const trackIds = [...trackSelection.current.ids], editorId = selectedClip?.id ?? editorClip?.id;
    const beforeTrackId = trackIds.length ? afterTracks(trackIds) : null;
    const references = context.range ? projectRef.current.clips.filter(clip => clip.trackId === context.trackId &&
      clip.start < context.range!.end && clipEnd(clip) > context.range!.start) : [];
    const analysisId = context.range ? references.length === 1 ? references[0].id : undefined : context.selection.clips[0];
    const entry = (id: string, label: string, shortcut?: string, disabled?: string): MenuEntry => ({ id, label, shortcut, disabled,
      action: () => {
        if (["copy", "cut", "paste", "duplicate", "delete", "split", "front", "back", "locators"].includes(id)) editContext(id, context);
        else if (id === "import") void beginImport(undefined, { start: context.cursor, targetTrackId: context.trackId, beforeTrackId, source: "cursor" }, true, context.cursor);
        else if (["duplicate-tracks", "remove-tracks", "add-track"].includes(id)) {
          if (!trackIds.every(id => projectRef.current.tracks.some(track => track.id === id))) { tell("The menu target is no longer available."); return; }
          if (id === "duplicate-tracks") duplicateTrackSelection(trackIds);
          else if (id === "remove-tracks") removeTrackSelection(trackIds);
          else addTrack(trackIds.length ? afterTracks(trackIds) : null);
        } else if (id === "editor" || id === "analyze") {
          const clip = projectRef.current.clips.find(clip => clip.id === (id === "editor" ? editorId : analysisId));
          if (!clip) { tell("The menu target is no longer available."); return; }
          if (id === "editor") editAudio(clip); else beginAnalysis(clip, context.range);
        } else commands.current(id);
      } });
    const noAudio = !context.selection.clips.length && !context.range ? "Select audio or a range" : undefined;
    const mapClipboard = context.selection.maps.length ? "Audio clipboard cannot include tempo/signature points" : undefined;
    let items: MenuEntry[];
    if (name === "file") items = [entry("new", "New Project", "Ctrl N"), entry("open", "Open Project…", "Ctrl O"), separator,
      entry("save", "Save", "Ctrl S"), entry("save-as", "Save As…", "Ctrl Shift S"), separator,
      entry("import", "Import Audio…"), entry("export", "Export Audio & Map…", undefined, projectEnd(projectRef.current) <= 0 && loop.end <= loop.start ? "No audio or locator range to export" : undefined)];
    else if (name === "edit") items = [entry("undo", "Undo", "Ctrl Z", !history.current.undoLabel ? "Nothing to undo" : undefined), entry("redo", "Redo", "Ctrl Shift Z", !history.current.redoLabel ? "Nothing to redo" : undefined), separator,
      entry("cut", "Cut", "Ctrl X", mapClipboard ?? noAudio), entry("copy", "Copy", "Ctrl C", mapClipboard ?? noAudio), entry("paste", "Paste", "Ctrl V", mapClipboard ?? (!clipboard.current ? "No copied audio" : undefined)),
      entry("duplicate", "Duplicate", "Ctrl D", mapClipboard ?? noAudio), entry("split", "Split at Cursor", "Alt X", mapClipboard ?? noAudio), entry("delete", "Delete", "Del", !contextBounds(context) ? "Select an event, point or range" : undefined)];
    else if (name === "project") items = [entry("project-setup", "Project Setup…"), separator,
      entry("add-track", "Add Audio Track…", "T"), entry("duplicate-tracks", "Duplicate Tracks", undefined, !selectedTracks.length ? "Select tracks" : undefined), entry("remove-tracks", "Remove Tracks…", "Shift Del", !selectedTracks.length ? "Select tracks" : undefined)];
    else if (name === "audio") items = [entry("editor", "Open Audio Editor", "Ctrl E", !selectedClip ? "Select an audio event" : undefined), entry("analyze", "Analyze Audio…", undefined, !analysisId ? "Choose one reference audio event" : undefined),
      { id: "linked", label: "Linked Edits", checked: linked, action: () => setLinked(value => !value) }];
    else if (name === "transport") items = [entry("start", "Start / Resume", "Num Enter"), entry("stop", "Stop", "Num 0"), entry("rewind", "Return to Start", "Num ."), separator,
      entry("locators", "Locators to Selection", "P", !contextBounds(context) ? "Select events or a range" : undefined),
      { id: "cycle", label: "Cycle", shortcut: "Num /", checked: loop.enabled, action: () => setLoop(value => ({ ...value, enabled: !value.enabled })) },
      { id: "click", label: "Metronome", shortcut: "C", checked: metronome, action: () => setMetronome(value => !value) }];
    else items = [{ label: "Inspector", checked: inspector, action: () => setInspector(value => !value) }, { label: "Tempo / Signature", checked: showMaps, action: toggleMaps }, separator,
      { ...entry("editor", "Audio Editor", "Ctrl E", !editorId ? "Select an audio event" : undefined), checked: !!editorClip,
        action: () => { if (editorClip) setEditorClipId(null); else { const clip = projectRef.current.clips.find(clip => clip.id === editorId); if (clip) editAudio(clip); } } },
      { id: "mixconsole", label: "MixConsole", checked: mixer, action: () => { setMixer(value => !value); setEditorClipId(null); } }, separator,
      { label: "Fit Project", shortcut: "Shift F", action: fit }, { label: "Restore Layout", action: () => {
        for (const key of ["joljak.ui.inspector-width", "joljak.ui.track-list-width", "joljak.ui.lower-height"]) localStorage.removeItem(key);
        setLayoutRevision(value => value + 1);
        setInspector(true); setShowMaps(true); localStorage.setItem("joljak.ui.maps", "shown"); setMixer(false); setEditorClipId(null);
      } }];
    showPopup({ x: box?.left ?? 8, y: box?.bottom ?? 58, appMenu: name, invoker: node, items,
      navigate: direction => { const order = ["file", "edit", "project", "audio", "transport", "view"]; openAppMenu(order[(order.indexOf(name) + direction + order.length) % order.length]); } });
  };
  const runExport = async () => {
    if (!api) return;
    const bounds =
      exportScope === "locators"
        ? loop
        : { start: 0, end: projectEnd(project) };
    try {
      const id = await api.exportProject(project, {
        start: bounds.start,
        end: bounds.end,
        mix: exportMix,
        stems: exportStems,
        click: exportClick,
        maps: exportMaps,
      });
      if (id) {
        jobSessions.current.set(id, { session: session.current, kind: "export" });
        setJobs((list) => [
          ...list,
          { id, kind: "export", stage: "Preparing export" },
        ]);
        setModal(null);
      }
    } catch (e) {
      tell(String(e));
    }
  };
  const beginExport = () => {
    if (projectEnd(project) <= 0 && loop.end <= loop.start) return;
    if (projectEnd(project) <= 0) setExportScope("locators");
    setModal("export");
  };

  commands.current = (command) => {
    closeMenu();
    if (command === "editor") editAudio();
    else if (command === "mixconsole") setMixer(true);
    else if (command === "start") startPlayback();
    else if (command === "stop") engine.current?.stop();
    else if (command === "play") togglePlay();
    else if (command === "rewind") seek(0);
    else if (command === "undo") {
      if (!history.current.undoLabel) return;
      setPreviewing(false);
      projectRef.current = history.current.undo(); setProject(projectRef.current);
      setDirty(true);
    } else if (command === "redo") {
      if (!history.current.redoLabel) return;
      setPreviewing(false);
      projectRef.current = history.current.redo(); setProject(projectRef.current);
      setDirty(true);
    } else if (command === "import") void beginImport();
    else if (command === "save") void save();
    else if (command === "save-as") setModal("save-as");
    else if (command === "open") void open();
    else if (command === "new") newProject();
    else if (command === "analyze") beginAnalysis();
    else if (command === "export") {
      beginExport();
    } else if (command === "project-setup") {
      setModal("project-setup");
    } else if (command === "help") setModal("help");
    else if (command === "add-track") addTrack();
    else if (command === "duplicate-tracks") duplicateTrackSelection();
    else if (command === "remove-tracks") removeTrackSelection();
    else if (command === "track-events") trackEvents();
    else if (command === "tracks-up") moveTrackSelection(-1);
    else if (command === "tracks-down") moveTrackSelection(1);
    else if (["copy", "cut", "paste", "delete", "duplicate", "locators", "front", "back"].includes(command)) editContext(command);
    else if (command === "split") {
      if(selectedMaps.length){tell("Split currently requires an audio-only selection.");return;}
      const ids = selection.length ? selection : range ? [] :
        editorClip && document.activeElement?.closest(".audio-editor") ? [editorClip.id] : projectRef.current.clips.map(clip => clip.id);
      editContext("split", captureEdit({ selection: { clips: ids, maps: [] } }));
    }
    else if (command === "cycle")
      setLoop((value) => ({ ...value, enabled: !value.enabled }));
    else if (command === "click") setMetronome((value) => !value);
    else if (command === "linked") setLinked((value) => !value);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || popupRef.current) return;
      const node = e.target as HTMLElement;
      if ((e.shiftKey && e.code === "F10" || e.key === "ContextMenu") && !editableText(node)) {
        e.preventDefault();
        const actions = captureControlContext(node);
        if (actions) {
          const bounds = node.getBoundingClientRect(); showPopup({ x: bounds.left, y: bounds.bottom, title: actions.label,
            items: controlMenuItems(actions), invoker: node, restoreFocus: actions.restoreFocus }, actions.valid); return;
        }
        const header = node.closest<HTMLElement>("[data-track-id]");
        if (header) { const bounds = header.getBoundingClientRect(); openTrackMenu(header.dataset.trackId!, bounds.left + 12, bounds.top + 16); return; }
        const point = node.closest<HTMLElement>("[data-map-id]");
        if (point || selectedMap && !selectedClip) {
          const map = point ? { id: point.dataset.mapId!, kind: point.dataset.mapKind as "tempo" | "signature" } : selectedMap!;
          const bounds = point?.getBoundingClientRect() ?? document.querySelector<HTMLElement>(".info-line")!.getBoundingClientRect();
          arrangementContext({ domain: "map", x: bounds.left + 12, y: bounds.bottom, time: position,
            map, selection: arrangement, invoker: point ?? node }); return;
        }
        if (selectedClip) {
          const clip = document.querySelector<HTMLElement>(`[data-clip-id="${selectedClip.id}"]`), bounds = clip?.getBoundingClientRect();
          if (bounds) arrangementContext({ domain: "audio", x: Math.max(8, bounds.left + 12), y: bounds.top + 24, time: engine.current?.position ?? position,
            clipId: selectedClip.id, trackId: selectedClip.trackId, selection: arrangement, invoker: node });
        } else if (range) {
          const bounds = document.querySelector<HTMLElement>(".timeline-scroll")!.getBoundingClientRect();
          arrangementContext({ domain: "range", x: bounds.left + 12, y: bounds.top + 40, time: range.start, range, trackId: activeTrack ?? range.trackIds[0], invoker: node });
        } else if (activeTrack) { const bounds = node.getBoundingClientRect(); openTrackMenu(activeTrack, bounds.left + 12, bounds.bottom); }
        return;
      }
      const editing =
        node.matches("textarea,select,summary") || node.isContentEditable
        || node instanceof HTMLInputElement && !node.readOnly && node.type !== "range";
      if (e.key === "Escape") {
        closeModal();
        closeMenu();
        return;
      }
      if (modal === "analyze" && (e.code === "KeyT" || e.code === "Space")) {
        e.preventDefault();
        if (!e.repeat) tapNow();
        return;
      }
      if (editing) return;
      if (modal) {
        if (e.code === "Space") {
          e.preventDefault();
          togglePlay();
        }
        return;
      }
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.code === "KeyZ" && cancelValueGesture(node)) { e.preventDefault(); return; }
      if (e.shiftKey && !ctrl && !e.altKey && ["KeyP", "KeyL", "KeyR"].includes(e.code)) {
        e.preventDefault();
        const labels: Record<string, string> = { KeyP: "Project position", KeyL: "Left locator", KeyR: "Right locator" };
        const label = labels[e.code];
        const input = document.querySelector<HTMLInputElement>('.transport-bar input[aria-label="' + label + '"]');
        input?.focus(); input?.select();
        return;
      }
      if (ctrl && !e.shiftKey && !e.altKey && (e.code === "Numpad1" || e.code === "Numpad2")) {
        e.preventDefault();
        const cursor = Math.max(0, engine.current?.position ?? position);
        if (e.code === "Numpad1") setLoop({ ...loop, start: cursor, end: Math.max(loop.end, cursor + .001) });
        else {
          const end = Math.max(.001, cursor);
          setLoop({ ...loop, start: Math.min(loop.start, end - .001), end });
        }
        return;
      }
      let command: string | null = null;
      if (ctrl && !e.altKey) {
        command =
          (
            {
              KeyZ: e.shiftKey ? "redo" : "undo",
              KeyC: "copy",
              KeyX: "cut",
              KeyV: "paste",
              KeyD: "duplicate",
              KeyE: "editor",
              KeyG: "group",
              KeyU: "ungroup",
              KeyA: e.shiftKey ? "select-none" : "select-all",
            } as Record<string, string>
          )[e.code] ?? null;
        if (["KeyS", "KeyN", "KeyO"].includes(e.code)) return; // Electron File menu owns its native accelerators.
      } else if (e.code === "Space") command = "play";
      else if (e.code === "Numpad0") {
        e.preventDefault();
        engine.current?.stop();
        return;
      } else if (e.code === "NumpadDecimal") command = "rewind";
      else if (e.code === "Numpad1") {
        e.preventDefault();
        seek(loop.start);
        return;
      } else if (e.code === "Numpad2") {
        e.preventDefault();
        seek(loop.end);
        return;
      } else if (e.code === "NumpadDivide") command = "cycle";
      else if (e.code === "Enter" || e.code === "NumpadEnter") {
        e.preventDefault();
        if (e.code === "Enter" && selectedClip) editAudio();
        else startPlayback();
        return;
      } else if (e.code === "KeyX" && e.altKey) command = "split";
      else if (e.code === "KeyX" && e.shiftKey) {
        e.preventDefault();
        if (range)
          change((p) => {
            const first = splitClips(
              p,
              selection.length
                ? selection
                : p.clips
                    .filter((c) => range.trackIds.includes(c.trackId))
                    .map((c) => c.id),
              range.start,
              linked,
            );
            return splitClips(
              first,
              first.clips
                .filter((c) => range.trackIds.includes(c.trackId))
                .map((c) => c.id),
              range.end,
              linked,
            );
          }, "Split range");
        return;
      } else if (e.code === "Delete" || e.code === "Backspace")
        command = e.shiftKey ? "remove-tracks" : "delete";
      else if (e.code === "KeyP" && !e.shiftKey) {
        e.preventDefault();
        if (e.altKey) setLocators(true, true);
        else setLocators();
        return;
      } else if (e.code === "KeyL" && !ctrl && !e.shiftKey && !e.altKey) {
        const bounds = selectionBounds();
        if (bounds) {
          e.preventDefault();
          seek(bounds.start);
        }
        return;
      } else if (e.code === "KeyC") command = "click";
      else if (e.code === "KeyF" && e.shiftKey) {
        e.preventDefault();
        fit();
        return;
      } else if (e.code === "KeyF") {
        e.preventDefault();
        setFollow((value) => !value);
        return;
      } else if (e.code === "KeyJ") {
        e.preventDefault();
        setSnap((value) => (value === "off" ? "beat" : "off"));
        return;
      } else if (e.code === "KeyK") command = "linked";
      else if (e.code === "KeyT" && !ctrl) command = "add-track";
      else if (e.code === "KeyU" && !ctrl) command = e.shiftKey ? "back" : "front";
      else if (e.code === "KeyG") {
        e.preventDefault();
        zoom(1 / 1.25);
        return;
      } else if (e.code === "KeyH") {
        e.preventDefault();
        zoom(1.25);
        return;
      } else if (e.code === "KeyS" && e.altKey) {
        const bounds = selectionBounds();
        if (bounds) {
          e.preventDefault();
          const next = Math.max(0.2, Math.min(1200, 900 / (bounds.end - bounds.start + 0.2)));
          timelineViewport.current?.setScale(next, bounds.start * next);
        }
        return;
      } else if ((e.code === "KeyM" || e.code === "KeyS") && track) {
        e.preventDefault();
        updateTrack(
          track.id,
          e.code === "KeyM" ? { mute: !track.mute } : { solo: !track.solo },
        );
        return;
      } else if (
        { Digit1: "object", Digit2: "range", Digit3: "split", Digit5: "erase" }[
          e.code
        ]
      ) {
        e.preventDefault();
        chooseTool(
          (
            {
              Digit1: "object",
              Digit2: "range",
              Digit3: "split",
              Digit5: "erase",
            } as Record<string, Tool>
          )[e.code],
        );
        return;
      }
      if (!command) return;
      e.preventDefault();
      if (command === "group" || command === "ungroup")
        groupSelection(command === "group");
      else if (command === "select-all") {
        if (editorClip && node.closest(".audio-editor")) {
          setArrangement({clips:[],maps:[]});setMapFocus(null);setRange({ start: editorClip.start, end: clipEnd(editorClip), trackIds: [editorClip.trackId] });
          return;
        }
        selectArrangement({clips:project.clips.map(clip=>clip.id),maps:[
          ...project.tempos.map(event=>({kind:"tempo" as const,id:event.id})),
          ...project.signatures.map(event=>({kind:"signature" as const,id:event.id}))]});
      } else if (command === "select-none") {
        setSelection([]);
        setRange(null);
        setSelectedClock(null);
        setSelectedMap(null);
      } else commands.current(command);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="app-shell" onContextMenu={controlContext} onPointerDownCapture={event => {
      if ((event.target as HTMLElement).closest(".menu-bar,.app-dropdown,.context-menu")) return;
      closeMenu();
    }} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}
      onDrop={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}>
      <header className="title-bar">
        <div className="wordmark">
          <Waves size={20} strokeWidth={1.5} />
          <span>JOLJAK</span>
          <i />
        </div>
        <span className="title-project">
          {project.name}
          {dirty && <b> •</b>}
        </span>
      </header>
      <div className="menu-bar">
        <div className="menus" role="menubar" aria-label="Application menus">
          {["file", "edit", "project", "audio", "transport", "view"].map(name => <button key={name} data-menu={name}
            className={appMenu === name ? "active" : ""} aria-haspopup="menu" aria-expanded={appMenu === name}
            onKeyDown={event => {
              if (event.key === "ArrowDown") { event.preventDefault(); openAppMenu(name);
                requestAnimationFrame(() => document.querySelector<HTMLElement>(".owned-menu > button")?.focus({ preventScroll: true })); }
              else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault(); const order = ["file", "edit", "project", "audio", "transport", "view"];
                const next = order[(order.indexOf(name) + (event.key === "ArrowRight" ? 1 : -1) + order.length) % order.length];
                document.querySelector<HTMLElement>(`.menus [data-menu="${next}"]`)?.focus({ preventScroll: true });
              }
            }}
            onPointerEnter={() => { if (popupRef.current?.appMenu && appMenu !== name) openAppMenu(name); }}
            onClick={() => openAppMenu(name)}>{name[0].toUpperCase() + name.slice(1)}</button>)}
          <button onClick={() => { closeMenu(); setModal("samples"); }}>Samples</button>
          <button onClick={() => { closeMenu(); setModal("help"); }}>Help</button>
        </div>
      </div>
      <section className="edit-toolbar" aria-label="Project toolbar">
        <button className="icon-button" aria-label="Undo" disabled={!history.current.undoLabel} title="Undo (Ctrl Z)" onClick={() => commands.current("undo")}><Undo2 size={17}/></button>
        <button className="icon-button" aria-label="Redo" disabled={!history.current.redoLabel} title="Redo (Ctrl Shift Z)" onClick={() => commands.current("redo")}><Redo2 size={17}/></button>
        <span className="toolbar-divider"/>
        <div className="tool-group">{[["object", MousePointer2, "Object Selection (1)"], ["range", StretchHorizontal, "Range Selection (2)"], ["split", Scissors, "Split (3)"], ["erase", Trash2, "Erase (5)"]].map(([value, Icon, label]) =>
          <button key={value as string} className={`tool-button ${tool === value ? "active" : ""}`} title={label as string} aria-label={label as string} aria-pressed={tool === value}
            onClick={() => chooseTool(value as Tool)}>{typeof Icon !== "string" && <Icon size={17}/>}</button>)}</div>
        <span className="toolbar-divider"/>
        <button className={`icon-button ${snap !== "off" ? "active" : ""}`} title="Snap (J)" aria-label="Snap" aria-pressed={snap !== "off"} onClick={() => setSnap(snap === "off" ? "beat" : "off")}><Magnet size={17}/></button>
        <select aria-label="Snap grid" value={snap} onChange={event => setSnap(event.target.value as Snap)}>
          <option value="off">Off</option><option value="bar">Bar</option><option value="beat">Beat</option>
          <option value="half">1/2</option><option value="quarter">1/4</option><option value="eighth">1/8</option><option value="sixteenth">1/16</option><option value="second">Second</option>
        </select>
        <span className="toolbar-divider"/>
        <button className={`icon-button ${linked ? "active" : ""}`} title="Linked edits (K)" aria-label="Linked edits" aria-pressed={linked} onClick={() => setLinked(value => !value)}><Link2 size={17}/></button>
        <button className={`icon-button ${follow ? "active" : ""}`} title="Follow playback (F)" aria-label="Follow playback" aria-pressed={follow} onClick={() => setFollow(value => !value)}><ArrowRightToLine size={17}/></button>
        <div className="toolbar-spacer"/>
        <button className="icon-button" title="Import Audio" aria-label="Import Audio" onClick={() => void beginImport()}><FolderOpen size={17}/></button>
        <button className="analyze-button" aria-label="Analyze Audio" disabled={!selectedClip && !(range && range.end > range.start)} onClick={() => beginAnalysis()}><AudioLines size={16}/>Analyze</button>
        <button className="icon-button" title="Export Audio & Map" aria-label="Export Audio & Map" onClick={beginExport}><Download size={17}/></button>
        <span className="toolbar-divider"/>
        <button className={`icon-button ${inspector ? "active" : ""}`} title="Show/Hide Inspector" aria-label="Show/Hide Inspector" aria-pressed={inspector} onClick={() => setInspector(value => !value)}><PanelLeftClose size={17}/></button>
        <button className={`icon-button ${showMaps ? "active" : ""}`} title="Show/Hide Tempo and Signature" aria-label="Show/Hide Tempo and Signature" aria-pressed={showMaps} onClick={toggleMaps}><Music2 size={17}/></button>
      </section>
      <section key={`${session.current}:${range ? "range:" + range.trackIds.join(",") : selection.join(",") + selectedMaps.map(item => item.id).join(",")}`}
        className={`info-line ${(arrangementInfo?.audioCount ?? 0) > 1 || mixedInfo ? "multiple-selection" : ""}`} aria-label="Info Line">
        {mixedInfo ? <><div className="info-name object-title"><AudioLines size={15}/><strong>Selection</strong></div><SelectionMove project={project} selection={arrangement} linked={linked} onMove={moveSelectedArrangement} compact/></> : range && range.end > range.start ? <>
          <div className="info-name"><span>Range</span><div><StretchHorizontal size={14}/><strong>{range.trackIds.length} tracks</strong></div></div>
          <TimeField project={project} label="Range start" caption="Start" value={range.start} max={range.end - .001} onChange={start => setRange({ ...range, start })}/>
          <TimeField project={project} label="Range end" caption="End" value={range.end} min={range.start + .001} onChange={end => setRange({ ...range, end })}/>
          <label className="info-duration"><span>Length</span><ValueField label="Range length" value={range.end - range.start} min={.001} step={.001} format={value => `${value.toFixed(3)} s`} onChange={duration => setRange({ ...range, end: range.start + duration })}/></label>
        </> : selectedClip ? <>
          <div className="info-name"><span>Event</span><div><AudioLines size={14}/><strong title={selectedClip.name}>{selectedClip.name}</strong>
            {(arrangementInfo?.audioCount ?? 0) > 1 && <span className="info-selection-count" title={`${arrangementInfo!.audioCount} events · relative edit`} aria-label={`${arrangementInfo!.audioCount} selected events`}>{linked && selectedClip.groupId ? <Link2 size={13}/> : <Layers size={13}/>}<span>{arrangementInfo!.audioCount}</span></span>}
          </div></div>
          <TimeField project={project} label="Event start" caption="Start" value={selectedClip.start} onPreview={audioValuePreview("move", selectedClip.start)} onChange={start => move(selection, start - selectedClip.start)}/>
          <TimeField project={project} label="Event end" caption="End" value={clipEnd(selectedClip)} min={selectedClip.start + .001} onPreview={audioValuePreview("end", clipEnd(selectedClip))} onChange={end => trim(selection, "end", end - clipEnd(selectedClip))}/>
          <label className="info-duration"><span>Length</span><ValueField label="Event length" value={selectedClip.duration} min={.001} step={.001} format={value => `${value.toFixed(3)} s`}
            onPreview={audioValuePreview("end", selectedClip.duration)} onChange={duration => trim(selection, "end", duration - selectedClip.duration)}/></label>
          <div className="info-source"><span>Source In</span><strong>{selectedClip.sourceStart.toFixed(3)} <small>s</small></strong></div>
        </> : mapTempo ? <>
          <div className="info-name object-title"><AudioLines size={15}/><strong>Tempo</strong></div>
          <TimeField project={mapPositionGrid} label="Tempo position" caption="Position" value={timeAtQuarter(project, mapTempo.quarter)} onChange={seconds => moveMap({ kind: "tempo", id: mapTempo.id }, seconds)}/>
          <NumberField label="Tempo BPM" caption="BPM" commitEqual value={mapTempo.bpm} min={1} max={1000} step={1} integerSteps onChange={bpm => updateTempo({ ...mapTempo, bpm, origin: "manual" })}/>
        </> : mapSignature ? <>
          <div className="info-name object-title"><Music2 size={15}/><strong>Signature</strong></div>
          <TimeField project={mapPositionGrid} label="Signature position" caption="Position" beatStartOnly value={timeAtBar(project, mapSignature.bar)} onChange={seconds => moveMap({ kind: "signature", id: mapSignature.id }, seconds)}/>
          <div className="info-signature"><span>Signature</span><SignatureField value={mapSignature} title="Time signature" onChange={fields => { updateSignature({ ...mapSignature, ...fields, origin: "manual" }); return true; }}/></div>
        </> : <span className="info-empty">No selection</span>}
      </section>
      <main className="workspace">
        {inspector && (
          <ResizablePane axis="x" initialSize={220} minSize={190} maxSize={380} storageKey="joljak.ui.inspector-width" label="Inspector width" className="inspector-pane" resetKey={layoutRevision}>
          <aside className="inspector">
            <div className="panel-heading">
              <span>Inspector</span>
              <button
                className="icon-button small"
                title="Hide Inspector"
                onClick={() => setInspector(false)}
              >
                <PanelLeftClose size={15} />
              </button>
            </div>
            {project.sampleReview&&<SampleReviewPanel project={project}
              onPreview={auditionSample} onProject={auditionSampleProject} onSave={()=>void saveSampleDraft()}
              onNote={note=>change(p=>({...p,sampleReview:{...p.sampleReview!,note}}),"Edit sample draft note")}
              onAlignment={milliseconds=>{
                const review=projectRef.current.sampleReview!,clip=projectRef.current.clips.find(c=>c.id===review.clipId);
                if(clip){const start=review.initialAudioOrigin+clip.sourceStart-milliseconds/1000;
                  commit(moveClips(projectRef.current,[clip.id],start-clip.start,linked),"Adjust sample alignment");
                  selectArrangement({clips:[clip.id],maps:[]});}
              }}/>
            }
            {track ? (
              <>
                <div
                  className="inspector-track"
                  style={
                    { "--track-color": track.color } as React.CSSProperties
                  }
                >
                  <AudioLines size={20} />
                  <div>
                    <small>AUDIO TRACK</small>
                    <h3>{track.name}</h3>
                  </div>
                </div>
                <div key={`${session.current}:${track.id}`} className="inspector-channel">
                  <div className="channel-state">
                    <button className={`track-switch mute ${track.mute ? "on" : ""}`} title="Mute (M)" aria-label="Mute focused track" aria-pressed={track.mute} onClick={() => updateTrack(track.id, { mute: !track.mute })}>M</button>
                    <button className={`track-switch solo ${track.solo ? "on" : ""}`} title="Solo (S)" aria-label="Solo focused track" aria-pressed={track.solo} onClick={() => updateTrack(track.id, { solo: !track.solo })}>S</button>
                    <label className="track-timebase" title="Track time base">{track.timeBase === "musical" ? <Music2 size={13}/> : <Clock3 size={13}/>}<select aria-label="Track time base" value={track.timeBase}
                      onChange={event => change(value => setTrackTimeBase(value, track.id, event.target.value as "linear" | "musical"), "Track time base")}><option value="linear">Linear</option><option value="musical">Musical</option></select></label>
                  </div>
                  <div className="inspector-volume">
                    <span className="inspector-control-name">Volume</span>
                    <VolumeFader horizontal gain={track.gain} label="Track volume slider" onPreview={(gain) => previewTrack(track.id, { gain })} onCommit={(gain) => updateTrack(track.id, { gain })}/>
                    <GainField label="Volume" gain={track.gain} onChange={(gain) => updateTrack(track.id, { gain })}/>
                  </div>
                  <div className="inspector-pan">
                    <span className="inspector-control-name">Pan</span>
                    <PanFader label="Track pan slider" value={Math.round(track.pan * 100)}
                      onPreview={(value) => previewTrack(track.id, { pan: value / 100 })} onCommit={(value) => updateTrack(track.id, { pan: value / 100 })}/>
                    <ValueField label="Pan" value={track.pan * 100} min={-100} max={100} resetValue={0} resetLabel="Reset to Center" step={1}
                      format={value => value === 0 ? "C" : `${value < 0 ? "L" : "R"}${Math.round(Math.abs(value))}`} inputFormat={String}
                      adjust={(value, steps) => Math.max(-100, Math.min(100, Math.round(value) + steps))} onChange={value => updateTrack(track.id, { pan: value / 100 })}/>
                  </div>
                </div>
              </>
            ) : !selectedMap && (
              <div className="inspector-empty">
                <MousePointer2 size={25} strokeWidth={1.3} />
                <p>No track</p>
              </div>
            )}
            {selectedClip && (
              <InspectorSection title="Event" key={selectedClip.id}>
                <h4>{selectedClip.name}</h4>
                <dl className="event-details">
                  <dt>Length</dt>
                  <dd>{formatTime(selectedClip.duration)}</dd>
                  <dt>Source in</dt>
                  <dd>{formatTime(selectedClip.sourceStart)}</dd>
                  <dt>Time base</dt>
                  <dd>{project.tracks.find((t) => t.id === selectedClip.trackId)?.timeBase === "musical" ? "Musical" : "Linear"}</dd>
                  <dt>Group</dt>
                  <dd>
                    {selectedClip.groupId ? "Linked stems" : "Independent"}
                  </dd>
                </dl>
                <button className="secondary-button full" onClick={() => editAudio(selectedClip)}>Open Audio Editor</button>
              </InspectorSection>
            )}
            {selectedClip && !clock && <InspectorSection title="Analysis" key={`analysis:${selectedClip.id}`}>
              <button className="secondary-button full" onClick={() => beginAnalysis(selectedClip)}><Waves size={14}/>Analyze Audio…</button>
            </InspectorSection>}
            {clock && (
              <InspectorSection title="Analysis" key={clock.id} initiallyOpen={selectedClock === clock.id} badge={JSON.stringify(clock.values) === JSON.stringify(clock.original) ? "ANALYZED" : "EDITED"}>
                <select className="saved-clock-select" aria-label="Saved analysis scope" value={clock.id} onChange={(e) => setSelectedClock(e.target.value)}>
                  {project.clocks.filter((saved) => saved.clipId === clock.clipId && clockSourceScope(project, saved)).map((saved) => <option key={saved.id} value={saved.id}>{formatTime(saved.sourceStart)}–{formatTime(saved.sourceEnd)} · {saved.values.bpm.toFixed(2)} BPM</option>)}
                </select>
                <p className="field-help">Original analyzed source: {formatTime(clock.sourceStart)}–{formatTime(clock.sourceEnd)}.
                  {(() => { const scope = clockSourceScope(project, clock)!; return scope.start !== clock.sourceStart || scope.end !== clock.sourceEnd
                    ? ` This fragment covers ${formatTime(scope.start)}–${formatTime(scope.end)}; no new analysis was run.` : ""; })()}</p>
                <NumberField
                  label="Quarter BPM"
                  value={clock.values.bpm}
                  step={1}
                  integerSteps
                  min={1}
                  max={1000}
                  onChange={(bpm) => updateClock(clock.id, { bpm })}
                />
                <div className="meter-fields">
                  <NumberField
                    label="Meter"
                    value={clock.values.numerator}
                    step={1}
                    precision={0}
                    min={1}
                    max={32}
                    onChange={(numerator) =>
                      updateClock(clock.id, {
                        numerator: Math.round(numerator),
                      })
                    }
                  />
                  <select
                    value={clock.values.denominator}
                    aria-label="Meter denominator"
                    onChange={(e) =>
                      updateClock(clock.id, {
                        denominator: Number(e.target.value),
                      })
                    }
                  >
                    {[1, 2, 4, 8, 16, 32].map((d) => (
                      <option key={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <NumberField
                  label="Downbeat offset"
                  value={clock.values.offset}
                  suffix="s"
                  step={0.001}
                  onChange={(offset) => updateClock(clock.id, { offset })}
                />
                <p className="field-help">
                  Edit or restore the saved values, then Apply &amp; Align to update the project grid and move this song with its linked stems.
                  The offset is measured from the original analyzed source start.
                </p>
                <p className="field-help alignment-preview">{alignmentLabel(clock)}</p>
                <button className="primary-button full" onClick={() => alignClock(clock.id)}>Apply &amp; Align</button>
                <button className="secondary-button full" onClick={() => void auditionClock(clock)}>Audition saved clock</button>
                <button
                  className="secondary-button full"
                  title="Restore the original prediction values. Apply & Align separately to update the grid and song position."
                  onClick={() => restoreClockValues(clock.id)}
                >
                  <Undo2 size={13} />
                  Restore Original Prediction
                </button>
                <button className="secondary-button full" title="Remove this saved clock draft; retain the original prediction and project map."
                  onClick={() => removeSavedClock(clock.id)}>Remove Saved Clock</button>
              </InspectorSection>
            )}
            {selectedMap && <ProjectMapEditor key={selectedMap.id} project={project} selection={selectedMap} selectedMaps={selectedMaps} selectedClips={selection} onSelect={chooseMap} onTempo={updateTempo} onSignature={updateSignature} onMove={moveMap} onRemove={() => removeMap(selectedMap)} listOnly onContext={arrangementContext}/>}

          </aside>
          </ResizablePane>
        )}
        {!inspector && (
          <button
            className="inspector-restore"
            title="Show Inspector"
            onClick={() => setInspector(true)}
          >
            <ChevronRight size={15} />
          </button>
        )}
        <div className="workspace-center">
          <Timeline
            project={project}
            showMaps={showMaps} layoutRevision={layoutRevision} onContext={arrangementContext} onMenuClose={closeMenu}
            selectedMap={selectedMap}
            selectedMaps={selectedMaps}
            selection={selection}
            activeTrack={activeTrack}
            selectedTracks={selectedTracks}
            range={range}
            tool={tool}
            snap={snap}
            linked={linked}
            position={position}
            viewportControl={timelineViewport}
            follow={follow && playing}
            loop={loop}
            peaks={peaks.current}
            onSelect={(ids, track) => {
              setSelection(ids); setRange(null);
              if (track) selectTracks([track]);
              setSelectedClock(null);
              setSelectedMap(null);
              closeMenu();
            }}
            onArrangementSelect={selectArrangement}
            onArrangementMove={(value,delta)=>moveSelectedArrangement(delta,value)}
            onTrackSelect={selectTrack}
            onTrackMenu={openTrackMenu}
            onTrackReorder={moveTracks}
            onRange={value => { setRange(value); if (value) { setArrangement({ clips: [], maps: [] }); setMapFocus(null); setSelectedClock(null); } }}
            onSeek={seek}
            onLoop={(start, end) =>
              setLoop((value) => ({
                ...value,
                start: Math.max(0, start),
                end: Math.max(0.001, end),
              }))
            }
            onMove={move}
            onTrim={trim}
            onSplit={split}
            onDelete={remove}
            onAddTrack={() => addTrack()}
            onFront={(ids) => change((p) => orderClips(p, ids, true, linked), "Move events to front")}
            onBack={(ids) => change((p) => orderClips(p, ids, false, linked), "Move events to back")}
            onEdit={editAudio}
            onRangeMove={editRange}
            onTrack={updateTrack}
            onAnalyze={beginAnalysis}
            onMapSelect={chooseMap} onMapAdd={addMap} onMapMove={moveMap} onMapDelete={removeMap} onTimeBase={timeBase}
            onImport={beginImport}
          />
          {pendingAnalysis && (
            <div className="analysis-result">
              <div className="analysis-result-icon">
                <Waves size={23} />
              </div>
              <div className="analysis-result-copy">
                <small>CLOCK PROPOSAL · ANALYZED SCOPE ONLY</small>
                <strong>
                  {pendingAnalysis.result.period_seconds
                    ? `${pendingAnalysis.result.quarter_bpm.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} BPM   ·   ${pendingAnalysis.result.time_signature.numerator}/${pendingAnalysis.result.time_signature.denominator}   ·   offset ${pendingAnalysis.result.offset_seconds.toFixed(4)} s`
                    : "No supported clock"}
                </strong>
                <span>
                  {placementLabel ?? "Listen with the click, then keep the original prediction or apply it."}
                </span>
                {pendingAnalysis.result.confidence_flags?.length > 0 && <span>Audition first: some musical evidence is ambiguous.</span>}
              </div>
              <button
                className="secondary-button"
                disabled={!pendingAnalysis.result.period_seconds}
                onClick={() => void audition()}
              >
                <Headphones size={15} />
                Audition
              </button>
              <button
                className="primary-button"
                disabled={
                  !pendingAnalysis.result.period_seconds ||
                  !placementLabel ||
                  !project.clips.some((c) => c.id === pendingAnalysis.clipId)
                }
                onClick={apply}
              >
                Apply & Align
              </button>
              <button
                className="icon-button"
                title="Discard preview; keep saved prediction"
                onClick={() => {
                  setPendingAnalysis(null);
                  setPreviewing(false);
                  engine.current?.updateProject(project);
                }}
              >
                <X size={17} />
              </button>
            </div>
          )}
          {(editorClip || mixer) && <ResizablePane axis="y" initialSize={300} minSize={240} maxSize={560} storageKey="joljak.ui.lower-height" label="Lower zone height" className="lower-zone" resetKey={layoutRevision}>
          {(paneHeight) => <><div className="lower-zone-body">
          {editorClip && <div className="lower-editor-panel" aria-hidden={mixer} style={{ visibility: mixer ? "hidden" : "visible", pointerEvents: mixer ? "none" : "auto" }}>
          <AudioEditor key={editorClip.id} project={project} clip={editorClip} peaks={peaks.current.get(editorClip.assetId)} paneHeight={paneHeight - 33}
            onContext={arrangementContext}
            range={range} snap={snap} linked={linked} position={position}
            onRange={(value) => { setRange(value); setSelection(value ? [] : [editorClip.id]); setSelectedClock(null); setSelectedMap(null); }}
            onSeek={seek} onTrim={trim} onSplit={split} onClose={() => setEditorClipId(null)} onAnalyze={() => beginAnalysis(editorClip)}/></div>}
          {mixer && (
            <div className="mix-console">
              <div className="panel-heading">
                <span>MixConsole</span>
              </div>
              <div className="mixer-channels">
                {project.tracks.map((t) => (
                  <div
                    className={`mixer-strip ${selectedTracks.includes(t.id) ? "selected" : ""}`}
                    key={t.id}
                    style={{ "--track-color": t.color } as React.CSSProperties}
                  >
                    <span className="mixer-track-name" title={t.name}
                      onClick={(e) => selectTrack(t.id, { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey })}
                      onContextMenu={(e) => { e.preventDefault(); openTrackMenu(t.id, e.clientX, e.clientY); }}>{t.name}</span>
                    <div className="mixer-switches">
                      <button
                        className={`track-switch mute ${t.mute ? "on" : ""}`}
                        onClick={() => updateTrack(t.id, { mute: !t.mute })}
                      >
                        M
                      </button>
                      <button
                        className={`track-switch solo ${t.solo ? "on" : ""}`}
                        onClick={() => updateTrack(t.id, { solo: !t.solo })}
                      >
                        S
                      </button>
                    </div>
                    <PanFader
                      label={`${t.name} pan`}
                      value={Math.round(t.pan * 100)}
                      onPreview={(value) =>
                        previewTrack(t.id, { pan: value / 100 })
                      }
                      onCommit={(value) =>
                        updateTrack(t.id, { pan: value / 100 })
                      }
                    />
                    <VolumeFader compact gain={t.gain} label={`${t.name} volume`}
                      onPreview={(gain) => previewTrack(t.id, { gain })} onCommit={(gain) => updateTrack(t.id, { gain })}/>
                    <small>
                      {t.gain > 0 ? (20 * Math.log10(t.gain)).toFixed(1) : "−∞"}{" "}
                      dB
                    </small>
                  </div>
                ))}
                <div className="mixer-strip master">
                  <span>STEREO OUT</span>
                  <VolumeFader compact gain={project.masterGain} label="Master volume"
                    onPreview={(masterGain) => setProject((p) => ({ ...p, masterGain }))}
                    onCommit={(masterGain) => change((p) => ({ ...p, masterGain }), "Master volume")}/>
                  <small>
                    {project.masterGain > 0
                      ? (20 * Math.log10(project.masterGain)).toFixed(1)
                      : "−∞"}{" "}
                    dB
                  </small>
                </div>
              </div>
            </div>
          )}
          </div><div className="lower-zone-tabs" role="tablist" aria-label="Lower zone">
            <button className="icon-button small" title="Close lower zone" onClick={() => { setMixer(false); setEditorClipId(null); }}><X size={14}/></button>
            <button role="tab" aria-selected={mixer} className={mixer ? "active" : ""} onClick={() => setMixer(true)}>MixConsole</button>
            <button role="tab" aria-selected={!mixer && !!editorClip} className={!mixer && editorClip ? "active" : ""} disabled={!editorClip && !selectedClip}
              onClick={() => { if (editorClip) { setMixer(false); queueMicrotask(() => document.querySelector<HTMLElement>(".audio-editor")?.focus({ preventScroll: true })); } else editAudio(); }}>Editor</button>
          </div></>}
          </ResizablePane>}
        </div>
      </main>
      {(previewing||referencePreview) && <div className="preview-status"><Headphones size={13}/><span>{referencePreview?(referencePreview==="comparison"?"Sample comparison · 102 / 110 BPM":project.sampleReview?.reference.previouslyAccepted?"Approved sample click":"Original candidate click · unaccepted"):"Analysis preview"}</span><button onClick={() => { setPreviewing(false);setReferencePreview(null); engine.current?.updateProject(project); }}>Return to project</button></div>}
      {activeJob && <div className="job-status"><LoaderCircle size={13} className="spin"/><span>{activeJob.stage}</span>
        {activeJob.progress !== undefined && <span>{Math.round(activeJob.progress * 100)}%</span>}
        <button onClick={() => void api?.cancel(activeJob.id)}>Cancel</button></div>}
      <Transport key={session.current} project={project} position={position} playing={playing} buffering={buffering} loop={loop} metronome={metronome} levels={meter}
        onStart={startPlayback} onStop={() => engine.current?.stop()} onSeek={seek} onLoop={setLoop}
        onClick={() => setMetronome((value) => !value)}
        onMenu={showPopup}
        onMasterPreview={masterGain => setProject(value => ({ ...value, masterGain }))}
        onMasterCommit={masterGain => change(value => ({ ...value, masterGain }), "Master volume")}
        onTempo={tempoFromCursor}
        onSignature={signatureFromCursor}
        onClickPreview={(clickGain) => setProject((p) => ({ ...p, clickGain }))}
        onClickCommit={(clickGain) => {
          const referenceMode=referencePreview,analysisMode=previewing;
          change((p) => ({ ...p, clickGain }), "Metronome volume");
          setReferencePreview(referenceMode);setPreviewing(analysisMode);
        }}/>
      {message && (
        <div className="toast" role="status" aria-live="polite">
          <span>{message}</span>
          <button
            className="icon-button small"
            onClick={() => setMessage(null)}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {popup && <ContextMenu menu={popup} onClose={closeMenu}/> }
      {modal && (
        <div
          className="modal-backdrop"
          onPointerDown={(e) => {
            if (e.target === e.currentTarget) closeModal();
          }}
        >
          <div className={`modal ${modal === "help" ? "help-modal" : ""} ${modal==="samples"?"sample-modal":""}`}>
            <button
              className="modal-close icon-button"
              onClick={closeModal}
            >
              <X size={18} />
            </button>
            {modal === "project-setup" && <>
              <h2>Project Setup</h2><p>Project length controls the timeline and playback end. Audio export can use the content range or locators.</p>
              <NumberField label="Project length" value={project.projectDuration / 60} min={.01} step={1} suffix="min" onChange={(minutes) => change((p) => ({ ...p, projectDuration: minutes * 60 }), "Set project length")}/>
              <label className="form-label">Ruler format<select value={project.rulerFormat} onChange={(e) => change((p) => ({ ...p, rulerFormat: e.target.value as "bars" | "seconds" }), "Change ruler format")}><option value="bars">Bars + Beats</option><option value="seconds">Seconds</option></select></label>
              <p className="field-help">New projects start at 120 BPM and 4/4. Bottom tempo input changes the tempo from the cursor; earlier values remain. Edit a track point to change an existing segment. Map values continue until the next event.</p>
              {projectEnd(project) > project.projectDuration && <p className="field-help">Some content is beyond the project end. Extend the project length to play it.</p>}
              <div className="modal-actions"><button className="primary-button" onClick={() => setModal(null)}>Done</button></div>
            </>}
            {modal==="samples"&&<SampleLibraryDialog api={api} busy={sampleBusy} onOpen={(ref,comparison)=>void openSample(ref,comparison)} onClose={closeModal}/>}
            {modal === "add-track" && <AddAudioTrackDialog
              location={addBeforeTrack ? `Before ${project.tracks.find((track) => track.id === addBeforeTrack)?.name ?? "the chosen track"}` : "After the last audio track"}
              onAdd={addTracks} onCancel={() => setModal(null)}/>}
            {modal === "remove-tracks" && <RemoveTracksDialog
              tracks={project.tracks.filter((track) => removingTracks.includes(track.id))}
              events={project.clips.filter((clip) => removingTracks.includes(clip.trackId)).length}
              onRemove={() => performRemoveTracks(removingTracks)} onCancel={() => setModal(null)}/>}
            {modal === "import" && <ImportAudioDialog project={project} paths={importPaths} mode={importMode} copy={copyMedia}
              destination={importDestination} startKind={importAt} start={importStart} busy={importBusy}
              onMode={setImportMode} onCopy={setCopyMedia}
              onDestination={(targetTrackId, beforeTrackId) => setImportDestination((value) => ({ ...value, targetTrackId, beforeTrackId }))}
              onStartKind={importStartKind} onStart={setImportStart}
              onOrder={(index, delta) => setImportPaths((files) => { const next = [...files], [file] = next.splice(index, 1); next.splice(index + delta, 0, file); return next; })}
              onCancel={closeModal} onImport={() => void runImport()}/>}
            {modal === "analyze" && scope && (
              <>
                <div className="modal-symbol">
                  <Waves size={27} />
                </div>
                <h2>Find the musical clock</h2>
                <p>One fixed quarter BPM, meter and downbeat offset.</p>
                <div className="analysis-source">
                  <FileAudio size={20} />
                  <div>
                    <strong>{scope.name}</strong>
                    <span>
                      {scope.whole ? "WHOLE EVENT" : "SELECTED RANGE"} ·{" "}
                      {formatTime(scope.start)} — {formatTime(scope.end)}
                    </span>
                  </div>
                </div>
                <div className="tap-box">
                  <div>
                    <span className="section-label">
                      INITIAL QUARTER-BPM TAP
                    </span>
                    <small>Optional · chooses the beat unit only</small>
                  </div>
                  <div className="tap-control">
                    <button
                      className={`tap-button ${tapCount ? "tapped" : ""}`}
                      onClick={tapNow}
                    >
                      <Activity size={24} />
                      <strong>TAP</strong>
                      <kbd>T / Space</kbd>
                    </button>
                    <label>
                      <input
                        autoFocus
                        type="number"
                        value={tap}
                        placeholder="—"
                        min={1}
                        onChange={(e) => setTap(e.target.value)}
                      />
                      <span>approx. BPM</span>
                    </label>
                  </div>
                  <p>
                    Play the start of this scope and tap its quarter beat with T, Space, or the TAP button.
                    Precise BPM, meter and phase still come from audio.
                  </p>
                </div>
                <button
                  className="secondary-button full"
                  onClick={() => {
                    seek(scope.start);
                    if (!playing)
                      void engine.current
                        ?.play(scope.start)
                        .catch((e) => tell(e.message));
                  }}
                >
                  <Headphones size={15} />
                  Play from scope start
                </button>
                <p className="scope-note">
                  <Clock3 size={14} />
                  The result applies only to this scope. Audio remains
                  unchanged.
                </p>
                <div className="modal-actions">
                  <button
                    className="secondary-button"
                    onClick={() => setModal(null)}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary-button"
                    disabled={jobs.some(
                      (j) =>
                        j.kind === "analyze" &&
                        !["complete", "failed"].includes(j.stage),
                    )}
                    onClick={() => void analyze()}
                  >
                    <Waves size={16} />
                    Analyze Audio
                  </button>
                </div>
              </>
            )}
            {modal === "export" && (
              <>
                <div className="modal-symbol">
                  <Download size={25} />
                </div>
                <h2>Export your arrangement</h2>
                <p>
                  Aligned stereo WAV files, 48 kHz / 24-bit. No time-stretching.
                </p>
                <label className="form-label">
                  Time range
                  <select
                    value={exportScope}
                    onChange={(e) =>
                      setExportScope(e.target.value as "project" | "locators")
                    }
                  >
                    <option value="project" disabled={projectEnd(project) <= 0}>
                      Entire content · {formatTime(projectEnd(project))}
                    </option>
                    <option value="locators" disabled={loop.end <= loop.start}>
                      Between locators · {formatTime(loop.end - loop.start)}
                    </option>
                  </select>
                </label>
                <div className="export-options">
                  <label>
                    <input
                      type="checkbox"
                      checked={exportMix}
                      onChange={(e) => setExportMix(e.target.checked)}
                    />
                    <div>
                      <strong>Mixdown</strong>
                      <small>Audible tracks through the master channel</small>
                    </div>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={exportStems}
                      onChange={(e) => setExportStems(e.target.checked)}
                    />
                    <div>
                      <strong>Individual stems</strong>
                      <small>
                        Track levels, pan and mute/solo state · common origin
                      </small>
                    </div>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={exportClick}
                      onChange={(e) => setExportClick(e.target.checked)}
                    />
                    <div>
                      <strong>Click track</strong>
                      <small>Project tempo and signature tracks · current click level</small>
                    </div>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={exportMaps}
                      onChange={(e) => setExportMaps(e.target.checked)}
                    />
                    <div>
                      <strong>Tempo map</strong>
                      <small>
                        Exact second-based JSON and quantized MIDI derivative
                      </small>
                    </div>
                  </label>
                </div>
                <div className="modal-actions">
                  <button
                    className="secondary-button"
                    onClick={() => setModal(null)}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary-button"
                    disabled={
                      !exportMix &&
                      !(exportStems && project.tracks.length) &&
                      !exportClick &&
                      !exportMaps
                    }
                    onClick={() => void runExport()}
                  >
                    Choose Folder & Export
                  </button>
                </div>
              </>
            )}
            {modal === "save-as" && (
              <>
                <div className="modal-symbol">
                  <Save size={25} />
                </div>
                <h2>Save project as</h2>
                <p>
                  Store the arrangement, project tempo/signature tracks and original predictions.
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={saveCollect}
                    onChange={(e) => setSaveCollect(e.target.checked)}
                  />
                  Collect original audio beside the project file
                </label>
                <p className="field-help">
                  Collected projects can move to another computer. Existing
                  recordings are preserved.
                </p>
                <div className="modal-actions">
                  <button
                    className="secondary-button"
                    onClick={() => setModal(null)}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary-button"
                    onClick={() => void save(true)}
                  >
                    Choose File & Save
                  </button>
                </div>
              </>
            )}
            {modal === "help" && (
              <>
                <h2>Keyboard & mouse</h2>
                <p>
                  Cubase Pro 15 defaults for the implemented audio-editing
                  actions.
                </p>
                <div className="shortcut-list">
                  {keyGuide.map(([key, action]) => (
                    <div key={key}>
                      <kbd>{key}</kbd>
                      <span>{action}</span>
                    </div>
                  ))}
                </div>
                <p className="field-help">
                  Trim the lower event corners to reveal or hide source audio.
                  Linked edits preserve stem alignment. Range selection, event
                  selection and locators are separate.
                </p>
                <div className="modal-actions">
                  <button
                    className="primary-button"
                    onClick={() => setModal(null)}
                  >
                    Got it
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
      {!api && (
        <div className="desktop-notice">
          <span>
            This is the desktop UI. Launch the Windows app for local audio and
            analysis.
          </span>
        </div>
      )}
    </div>
  );
}
