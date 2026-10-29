import { NumberField } from "./controls";
import { TimeField } from "./Transport";
import type { MapSelection, Project, SignatureEvent, TempoEvent } from "./model";
import { musicalTime, signaturesInOrder, temposInOrder, timeAtBar, timeAtQuarter } from "./music";
import { arrangementDestination } from "./arrangement";
import type { ArrangementContext } from "./ContextMenu";

export default function ProjectMapEditor({ project, selection, selectedMaps, selectedClips = [], onSelect, onTempo, onSignature, onMove, onRemove, onEdit, listOnly = false, onContext }: {
  project: Project; selection: MapSelection; selectedMaps:MapSelection[];onSelect: (selection: MapSelection,additive?:boolean) => void;
  onTempo: (event: TempoEvent) => void; onSignature: (event: SignatureEvent) => void; onRemove: () => void;
  onMove: (selection: MapSelection, seconds: number) => void;
  onEdit: (selection: MapSelection) => void;
  listOnly?: boolean; onContext?: (context: ArrangementContext) => void;
  selectedClips?: string[];
}) {
  const tempo = selection.kind === "tempo" ? project.tempos.find((t) => t.id === selection.id) : null;
  const signature = selection.kind === "signature" ? project.signatures.find((s) => s.id === selection.id) : null;
  const requested = signature ? { ...signature, ...signature.shortBar?.original } : null;
  const calculated = !!signature?.shortBar && !signature.shortBar.original;
  const isTempo = selection.kind === "tempo";
  const positionGrid = arrangementDestination(project, { clips: [], maps: [selection] });
  return <div className="map-inspector">
    <div className={`map-inspector-title ${isTempo ? "tempo" : "signature"}`}>{isTempo ? "Tempo" : "Signature"}</div>
    <div className="map-event-list" aria-label={isTempo ? "Project tempo events" : "Project signature events"}>
      <div className="map-list-heading"><span>Position</span><span>{isTempo ? "BPM" : "Signature"}</span></div>
      {isTempo ? temposInOrder(project).map((event) => <button key={event.id} className={`map-list-row ${selectedMaps.some(item=>item.kind==="tempo"&&item.id===event.id) ? "selected" : ""}`} onClick={e => onSelect({ kind: "tempo", id: event.id },e.shiftKey||e.ctrlKey)}
        onContextMenu={e => { if (!onContext) return; e.preventDefault(); e.stopPropagation(); onContext({ domain: "map", x: e.clientX, y: e.clientY, time: timeAtQuarter(project, event.quarter), map: { kind: "tempo", id: event.id }, invoker: e.currentTarget,
          selection: selectedMaps.some(item => item.kind === "tempo" && item.id === event.id) ? { clips: selectedClips, maps: selectedMaps } : { clips: [], maps: [{ kind: "tempo", id: event.id }] } }); }}>
        <span>{musicalTime(project, timeAtQuarter(project, event.quarter))}</span><span>{event.bpm.toFixed(3)}</span></button>)
        : signaturesInOrder(project).map((event) => <button key={event.id} className={`map-list-row ${selectedMaps.some(item=>item.kind==="signature"&&item.id===event.id) ? "selected" : ""}`} onClick={e => onSelect({ kind: "signature", id: event.id },e.shiftKey||e.ctrlKey)}
          onDoubleClick={() => onEdit({ kind: "signature", id: event.id })}
          title={event.shortBar ? `${event.numerator}/${event.denominator} · Calculated short bar` : `${event.numerator}/${event.denominator}`}
          onContextMenu={e => { if (!onContext) return; e.preventDefault(); e.stopPropagation(); onContext({ domain: "map", x: e.clientX, y: e.clientY, time: timeAtBar(project, event.bar), map: { kind: "signature", id: event.id }, invoker: e.currentTarget,
            selection: selectedMaps.some(item => item.kind === "signature" && item.id === event.id) ? { clips: selectedClips, maps: selectedMaps } : { clips: [], maps: [{ kind: "signature", id: event.id }] } }); }}>
          <span>{musicalTime(project,timeAtBar(project,event.bar))}</span><span>{event.numerator}/{event.denominator}</span></button>)}
    </div>
    {!listOnly && (tempo || signature) && <div className="inspector-section map-editor">
      {tempo && <>
        <TimeField project={positionGrid} label="Tempo position" value={timeAtQuarter(project, tempo.quarter)} onChange={(seconds) => onMove(selection, seconds)}/>
        <NumberField label="Tempo" value={tempo.bpm} min={1} max={1000} step={1} integerSteps commitEqual onChange={(bpm) => onTempo({ ...tempo, bpm, origin: "manual" })}/>
      </>}
      {calculated ? <button onClick={() => onEdit(selection)}>Edit following signature…</button> : signature && requested && <>
        <TimeField project={positionGrid} label="Signature position" caption="Position in previous meter" beatStartOnly value={timeAtBar(project,signature.bar)} onChange={(seconds) => onMove(selection, seconds)}/>
        <div className="meter-fields"><NumberField label="Numerator" value={requested.numerator} min={1} max={32} step={1} precision={0} commitEqual onChange={(numerator) => onSignature({ ...requested, numerator: Math.round(numerator), origin: "manual" })}/>
          <select aria-label="Signature denominator" value={requested.denominator} onChange={(e) => onSignature({ ...requested, denominator: Number(e.target.value), origin: "manual" })}>{[1,2,4,8,16,32].map((denominator) => <option key={denominator}>{denominator}</option>)}</select>
        </div>
      </>}
      <button className="secondary-button full" disabled={calculated} onClick={onRemove}>Remove {isTempo ? "tempo" : "signature"} event</button>
    </div>}
  </div>;
}
