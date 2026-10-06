import { useEffect, useRef, useState } from "react";
import { Activity, LoaderCircle, Play, Repeat2, SkipBack, Square } from "lucide-react";
import { Fader, NumberField } from "./controls";
import { GainField } from "./VolumeFader";
import { type Project } from "./model";
import { musicalTime, parseMusicalTime, positionAtQuarter, quarterAtTime, tempoAtQuarter } from "./music";

function secondsText(seconds: number) {
  const ms = Math.floor(Math.max(0, seconds) * 1000);
  return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
export function TimeField({ project, value, label, format = project.rulerFormat, onChange }: {
  project: Project; value: number; label: string; format?: "bars" | "seconds"; onChange: (value: number) => void;
}) {
  const formatted = format === "bars" ? musicalTime(project, value) : secondsText(value);
  const [text, setText] = useState(formatted);
  const focused = useRef(false), edited = useRef(false);
  useEffect(() => { if (!focused.current) setText(formatted); }, [formatted]);
  const commit = () => {
    focused.current = false;
    if (edited.current) {
      let parsed: number | null = null;
      if (format === "bars") parsed = parseMusicalTime(project, text);
      else if (/^\d+(?:\.\d+)?$/.test(text.trim())) parsed = Number(text);
      else {
        const parts = text.trim().split(":");
        if ((parts.length === 2 || parts.length === 3) && parts.every((part, i) => i === parts.length - 1 ? /^\d{1,2}(?:\.\d+)?$/.test(part) : /^\d+$/.test(part))) {
          const values = parts.map(Number);
          if (values.at(-1)! < 60 && (values.length === 2 || values[1] < 60)) parsed = values.reduce((total, value) => total * 60 + value, 0);
        }
      }
      if (parsed !== null && Number.isFinite(parsed) && parsed >= 0) onChange(parsed);
    }
    edited.current = false;
    setText(formatted);
  };
  return <label className="time-field"><span>{label}</span><input aria-label={label} value={text}
    title={format === "bars" ? "Bar.Beat.Sixteenth.Tick (120 ticks per sixteenth)" : "Hours:minutes:seconds.milliseconds, or seconds"}
    onFocus={() => { focused.current = true; }} onChange={(e) => { edited.current = true; setText(e.target.value); }}
    onBlur={commit} onKeyDown={(e) => {
      if (e.key === "Enter") e.currentTarget.blur();
      if (e.key === "Escape") { edited.current = false; e.currentTarget.blur(); }
    }} /></label>;
}

export default function Transport({ project, position, playing, buffering, loop, metronome, levels,
  onStart, onStop, onSeek, onLoop, onClick, onTempo, onSignature, onClickPreview, onClickCommit }: {
  project: Project; position: number; playing: boolean; buffering: boolean; levels: number[];
  loop: { start: number; end: number; enabled: boolean }; metronome: boolean;
  onStart: () => void; onStop: () => void; onSeek: (seconds: number) => void;
  onLoop: (loop: { start: number; end: number; enabled: boolean }) => void; onClick: () => void;
  onTempo: (bpm: number) => void; onSignature: () => void;
  onClickPreview: (gain: number) => void; onClickCommit: (gain: number) => void;
}) {
  const [format, setFormat] = useState<"bars" | "seconds">("bars");
  const quarter = quarterAtTime(project, position), tempo = tempoAtQuarter(project, quarter);
  const signature = positionAtQuarter(project, quarter).signature;
  return <section className="transport-bar" aria-label="Transport">
    <div className="locator-fields">
      <div className="locator-field"><button title="Go to left locator (Num 1)" onClick={() => onSeek(loop.start)}>L</button>
        <TimeField project={project} format={format} label="Left locator" value={loop.start} onChange={(start) => onLoop({ ...loop, start, end: Math.max(loop.end, start + .001) })}/></div>
      <div className="locator-field"><button title="Go to right locator (Num 2)" onClick={() => onSeek(loop.end)}>R</button>
        <TimeField project={project} format={format} label="Right locator" value={loop.end} onChange={(end) => onLoop({ ...loop, start: Math.min(loop.start, Math.max(0, end - .001)), end })}/></div>
    </div>
    <div className="transport-buttons">
      <button className="icon-button" title="Go to project start (Num .)" onClick={() => onSeek(0)}><SkipBack size={16}/></button>
      <button className={`icon-button ${loop.enabled ? "cycle-on" : ""}`} title="Cycle (Num /)" aria-pressed={loop.enabled} onClick={() => onLoop({ ...loop, enabled: !loop.enabled })}><Repeat2 size={18}/></button>
      <button className={`icon-button stop-button ${!playing && !buffering ? "active" : ""}`} title="Stop (Num 0) · Press again to return to playback start" onClick={onStop}><Square size={16} fill="currentColor"/></button>
      <button className={`play-button ${playing && !buffering ? "playing" : ""}`} title="Start / Resume (Enter) · Space toggles playback" onClick={onStart} aria-pressed={playing}>
        {buffering ? <LoaderCircle size={18} className="spin"/> : <Play size={18} fill="currentColor"/>}
      </button>
    </div>
    <div className="transport-position">
      <TimeField project={project} format={format} label="Project position" value={position} onChange={onSeek}/>
      <select className="position-format" aria-label="Transport time format" title="Transport time format" value={format} onChange={(e) => setFormat(e.target.value as "bars" | "seconds")}>
        <option value="bars">♩</option><option value="seconds">s</option>
      </select>
    </div>
    <div className="transport-tempo" title="Set tempo from the current project cursor">
      <NumberField label="Tempo" commitEqual value={tempo.bpm} min={1} max={1000} step={.25} suffix="BPM" onChange={onTempo}/>
      <button className="transport-signature" title="Select current signature event" onClick={onSignature}>{signature.numerator}/{signature.denominator}</button>
    </div>
    <div className="transport-spacer"/>
    <div className="metronome-control">
      <button className={`icon-button ${metronome ? "active teal" : ""}`} title="Metronome (C)" aria-pressed={metronome} onClick={onClick}><Activity size={18}/></button>
      <Fader className="click-fader" label="Metronome volume" min={-60} max={6} resetValue={20 * Math.log10(.7)} value={project.clickGain > 0 ? 20 * Math.log10(project.clickGain) : -60}
        onPreview={(db) => onClickPreview(db <= -60 ? 0 : 10 ** (db / 20))} onCommit={(db) => onClickCommit(db <= -60 ? 0 : 10 ** (db / 20))}/>
      <GainField label="Click level" gain={project.clickGain} onChange={onClickCommit}/>
    </div>
    <div className="transport-output" title={`Stereo Out · ${project.sampleRate / 1000} kHz`}>
      <div className="master-meter">{[0,1].map((channel) => <i key={channel} style={{ width: `${Math.min(100, (levels[channel] ?? 0) * 100)}%`, background: levels[channel] > 1 ? "#e78a86" : undefined }}/>)}</div>
      <small>OUT</small>
    </div>
  </section>;
}
