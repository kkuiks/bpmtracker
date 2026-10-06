import { NumberField } from "./controls";
import { TimeField } from "./Transport";
import type { MapSelection, Project, SignatureEvent, TempoEvent } from "./model";
import { musicalTime, quarterAtTime, signaturesInOrder, temposInOrder, timeAtQuarter } from "./music";

export default function ProjectMapEditor({ project, selection, onSelect, onTempo, onSignature, onRemove }: {
  project: Project; selection: MapSelection; onSelect: (selection: MapSelection) => void;
  onTempo: (event: TempoEvent) => void; onSignature: (event: SignatureEvent) => void; onRemove: () => void;
}) {
  const tempo = selection.kind === "tempo" ? project.tempos.find((t) => t.id === selection.id) : null;
  const signature = selection.kind === "signature" ? project.signatures.find((s) => s.id === selection.id) : null;
  const isTempo = selection.kind === "tempo";
  return <div className="map-inspector">
    <div className={`map-inspector-title ${isTempo ? "tempo" : "signature"}`}>{isTempo ? "Tempo" : "Signature"}</div>
    <div className="map-event-list" aria-label={isTempo ? "Project tempo events" : "Project signature events"}>
      <div className="map-list-heading"><span>{isTempo ? "Position" : "Bar"}</span><span>{isTempo ? "BPM" : "Signature"}</span></div>
      {isTempo ? temposInOrder(project).map((event) => <button key={event.id} className={`map-list-row ${selection.id === event.id ? "selected" : ""}`} onClick={() => onSelect({ kind: "tempo", id: event.id })}>
        <span>{musicalTime(project, timeAtQuarter(project, event.quarter))}</span><span>{Number(event.bpm.toFixed(3))}</span></button>)
        : signaturesInOrder(project).map((event) => <button key={event.id} className={`map-list-row ${selection.id === event.id ? "selected" : ""}`} onClick={() => onSelect({ kind: "signature", id: event.id })}>
          <span>{event.bar}</span><span>{event.numerator}/{event.denominator}</span></button>)}
    </div>
    {(tempo || signature) && <div className="inspector-section map-editor">
      {tempo && <>
        {tempo.quarter === 0 ? <p className="field-help">Position · 1.1.1.0</p> : <TimeField project={project} format="bars" label="Tempo position" value={timeAtQuarter(project, tempo.quarter)} onChange={(seconds) => onTempo({ ...tempo, quarter: quarterAtTime(project, seconds), origin: "manual" })}/>}
        <NumberField label="Tempo" value={tempo.bpm} min={1} max={1000} step={.25} commitEqual onChange={(bpm) => onTempo({ ...tempo, bpm, origin: "manual" })}/>
      </>}
      {signature && <>
        {signature.bar === 1 ? <p className="field-help">Position · Bar 1</p> : <NumberField label="Signature bar" value={signature.bar} min={2} step={1} commitEqual onChange={(bar) => onSignature({ ...signature, bar: Math.round(bar), origin: "manual" })}/>}
        <div className="meter-fields"><NumberField label="Numerator" value={signature.numerator} min={1} max={32} step={1} commitEqual onChange={(numerator) => onSignature({ ...signature, numerator: Math.round(numerator), origin: "manual" })}/>
          <select aria-label="Signature denominator" value={signature.denominator} onChange={(e) => onSignature({ ...signature, denominator: Number(e.target.value), origin: "manual" })}>{[1,2,4,8,16,32].map((denominator) => <option key={denominator}>{denominator}</option>)}</select>
        </div>
      </>}
      <button className="secondary-button full" disabled={tempo?.quarter === 0 || signature?.bar === 1} onClick={onRemove}>Remove {isTempo ? "tempo" : "signature"} event</button>
    </div>}
  </div>;
}
