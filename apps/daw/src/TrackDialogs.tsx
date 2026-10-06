import { useState } from "react";
import { AudioLines, Trash2 } from "lucide-react";
import { type Track } from "./model";

export function AddAudioTrackDialog({ location, onAdd, onCancel }: {
  location: string; onAdd: (name: string, count: number) => void; onCancel: () => void;
}) {
  const [name, setName] = useState(""), [count, setCount] = useState("1");
  const number = Number(count), valid = Number.isInteger(number) && number >= 1 && number <= 32;
  return <form onSubmit={(e) => { e.preventDefault(); if (valid) onAdd(name, number); }}>
    <div className="modal-symbol"><AudioLines size={25}/></div><h2>Add Audio Track</h2>
    <p>{location}</p>
    <label className="form-label">Name<input autoFocus value={name} placeholder="Audio" maxLength={120} onChange={(e) => setName(e.target.value)}/></label>
    <label className="form-label">Count<input type="number" min={1} max={32} step={1} value={count} onChange={(e) => setCount(e.target.value)}/></label>
    <div className="modal-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button type="submit" className="primary-button" disabled={!valid}>Add Track{number > 1 ? "s" : ""}</button></div>
  </form>;
}

export function RemoveTracksDialog({ tracks, events, onRemove, onCancel }: {
  tracks: Track[]; events: number; onRemove: () => void; onCancel: () => void;
}) {
  return <>
    <div className="modal-symbol warning"><Trash2 size={25}/></div><h2>Remove Selected Tracks?</h2>
    <p>{tracks.length} track{tracks.length === 1 ? "" : "s"} contain{tracks.length === 1 ? "s" : ""} {events} audio event{events === 1 ? "" : "s"}.</p>
    <div className="file-list">{tracks.map((track) => <div key={track.id}><AudioLines size={14}/><span>{track.name}</span></div>)}</div>
    <p className="field-help">Original audio files and analysis records are preserved. You can restore the tracks and their events with Undo.</p>
    <div className="modal-actions"><button className="secondary-button" autoFocus onClick={onCancel}>Cancel</button><button className="primary-button danger-button" disabled={!tracks.length} onClick={onRemove}>Remove Tracks</button></div>
  </>;
}
