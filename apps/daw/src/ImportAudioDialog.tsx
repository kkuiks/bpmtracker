import { ArrowDown, ArrowUp, FileAudio } from "lucide-react";
import { type ImportDestination, type ImportOptions, type Project } from "./model";
import { TimeField } from "./Transport";

export type ImportStart = "cursor" | "end" | "drop" | "custom";

export default function ImportAudioDialog({ project, paths, mode, copy, destination, startKind, start,
  onMode, onCopy, onDestination, onStartKind, onStart, onOrder, onCancel, onImport, busy }: {
  project: Project; paths: string[]; mode: ImportOptions["mode"]; copy: boolean;
  destination: ImportDestination; startKind: ImportStart; start: number; busy: boolean;
  onMode: (mode: ImportOptions["mode"]) => void; onCopy: (copy: boolean) => void;
  onDestination: (targetTrackId: string | null, beforeTrackId: string | null) => void;
  onStartKind: (kind: ImportStart) => void; onStart: (start: number) => void;
  onOrder: (index: number, delta: number) => void; onCancel: () => void; onImport: () => void;
}) {
  const multiple = paths.length > 1;
  const validTarget = mode !== "sequence" || !destination.targetTrackId || project.tracks.some((track) => track.id === destination.targetTrackId);
  const validInsertion = (mode === "sequence" && !!destination.targetTrackId) || !destination.beforeTrackId || project.tracks.some((track) => track.id === destination.beforeTrackId);
  const valid = validTarget && validInsertion && paths.length > 0 && paths.length <= 32;
  return <>
    <div className="modal-symbol"><FileAudio size={25}/></div>
    <h2>Import Audio</h2>
    <p>{paths.length} file{multiple ? "s" : ""} selected. Original audio stays unchanged.</p>
    <div className="file-list import-file-list" aria-label="Import file order">
      {paths.map((file, index) => <div key={`${file}:${index}`}>
        <small>{String(index + 1).padStart(2, "0")}</small><FileAudio size={14}/>
        <span title={file}>{file.split(/[\\/]/).at(-1)}</span>
        {multiple && <div className="file-order-buttons">
          <button className="icon-button small" title="Move file up" aria-label={`Move ${file.split(/[\\/]/).at(-1)} up`} disabled={!index || busy} onClick={() => onOrder(index, -1)}><ArrowUp size={13}/></button>
          <button className="icon-button small" title="Move file down" aria-label={`Move ${file.split(/[\\/]/).at(-1)} down`} disabled={index === paths.length - 1 || busy} onClick={() => onOrder(index, 1)}><ArrowDown size={13}/></button>
        </div>}
      </div>)}
    </div>
    <label className="form-label">Placement
      <select value={mode} disabled={busy} onChange={(e) => onMode(e.target.value as ImportOptions["mode"])}>
        <option value="sequence">One track · files in sequence</option>
        <option value="tracks">Different tracks · same start</option>
        <option value="stems">Aligned stems · linked events</option>
      </select>
    </label>
    {mode === "sequence" ? <label className="form-label">Target track
      <select value={destination.targetTrackId ?? "new"} disabled={busy} onChange={(e) => {
        const id = e.target.value === "new" ? null : e.target.value;
        const index = project.tracks.findIndex((track) => track.id === id);
        onDestination(id, id ? project.tracks[index + 1]?.id ?? null : destination.beforeTrackId);
      }}>
        <option value="new">New audio track</option>
        {!validTarget && <option value={destination.targetTrackId!} disabled>Target track was removed</option>}
        {project.tracks.map((track) => <option value={track.id} key={track.id}>{track.name}</option>)}
      </select>
    </label> : null}
    {(mode !== "sequence" || !destination.targetTrackId) && <label className="form-label">Create tracks
      <select value={destination.beforeTrackId ?? "end"} disabled={busy} onChange={(e) => onDestination(destination.targetTrackId, e.target.value === "end" ? null : e.target.value)}>
        {!validInsertion && <option value={destination.beforeTrackId!} disabled>Insertion track was removed</option>}
        {project.tracks.map((track, index) => <option value={track.id} key={track.id}>
          {index ? `After ${project.tracks[index - 1].name}` : `Before ${track.name}`}
        </option>)}
        <option value="end">{project.tracks.length ? `After ${project.tracks.at(-1)!.name}` : "First audio track"}</option>
      </select>
    </label>}
    <div className="import-position-row">
      <label className="form-label">Start
        <select value={startKind} disabled={busy} onChange={(e) => onStartKind(e.target.value as ImportStart)}>
          {destination.source !== "cursor" && <option value="drop">At drop position</option>}
          <option value="cursor">At project cursor</option>
          <option value="end">After the last audio event</option>
          <option value="custom">Specify position</option>
        </select>
      </label>
      <TimeField project={project} label="Import position" value={start} onChange={(value) => { onStart(value); onStartKind("custom"); }}/>
    </div>
    {mode === "stems" && <p className="field-help">Each file starts at the same position on a new track. Their events are linked for moving, copying, splitting, trimming and deleting together.</p>}
    {mode === "tracks" && <p className="field-help">Each file starts at the same position on a new track. Events can be edited independently.</p>}
    {mode === "sequence" && multiple && <p className="field-help">Files follow the order above and join end to end on the target track.</p>}
    <label className="checkbox-label">
      <input type="checkbox" checked={copy} disabled={busy} onChange={(e) => onCopy(e.target.checked)}/>
      Copy originals into Joljak's local media storage
    </label>
    <p className="field-help">Unchecked: reference the existing files. This choice is remembered for file drops. Save As can collect originals into a portable project folder.</p>
    {!valid && <p className="form-error">{paths.length > 32 ? "Import up to 32 files at a time." : "Choose an available target and insertion position."}</p>}
    <div className="modal-actions">
      <button className="secondary-button" onClick={onCancel}>Cancel</button>
      <button className="primary-button" disabled={!valid || busy} onClick={onImport}>{busy ? "Preparing import…" : "Import Audio"}</button>
    </div>
  </>;
}
