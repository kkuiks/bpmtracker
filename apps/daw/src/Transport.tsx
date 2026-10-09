import { useEffect, useRef, useState } from "react";
import { Activity, LoaderCircle, Play, Repeat2, SkipBack, Square } from "lucide-react";
import { Fader, NumberField } from "./controls";
import { GainField } from "./VolumeFader";
import { type Project, type TimeSignature } from "./model";
import { musicalTime, parseMusicalTime, positionAtQuarter, quarterAtTime, tempoAtQuarter } from "./music";
import { DEFAULT_CLICK_GAIN, MAX_CLICK_BOOST_DB } from "./click-level";

function secondsText(seconds: number) {
  const ms = Math.floor(Math.max(0, seconds) * 1000);
  return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
export function TimeField({ project, value, label, format = "bars", disabled = false, barStartOnly = false, onChange }: {
  project: Project; value: number; label: string; format?: "bars" | "seconds"; disabled?: boolean;
  barStartOnly?: boolean; onChange: (value: number) => void;
}) {
  const formatted = format === "bars" ? musicalTime(project, value) : secondsText(value);
  const [text, setText] = useState(formatted);
  const [error, setError] = useState("");
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
      const valid = parsed !== null && Number.isFinite(parsed) && parsed >= 0;
      const quarter = valid && barStartOnly ? quarterAtTime(project, parsed!) : null;
      const atBarStart = quarter === null || Math.abs(quarter-positionAtQuarter(project,quarter).barStart)<1e-8;
      if(valid&&atBarStart) { setError("");onChange(parsed!); }
      else setError(barStartOnly?"Use a bar start, such as 5.1.1.0.":format==="bars"?"Enter a valid Bar.Beat.Sixteenth.Tick position.":"Enter a valid time position.");
    }
    edited.current = false;
    setText(formatted);
  };
  return <label className="time-field"><span>{label}</span><input aria-label={label} value={text} disabled={disabled} aria-invalid={!!error}
    title={barStartOnly?"Bar.Beat.Sixteenth.Tick · signature changes use x.1.1.0":format === "bars" ? "Bar.Beat.Sixteenth.Tick (120 ticks per sixteenth)" : "Hours:minutes:seconds.milliseconds, or seconds"}
    onFocus={() => { focused.current = true;setError(""); }} onChange={(e) => { edited.current = true;setError("");setText(e.target.value); }}
    onBlur={commit} onKeyDown={(e) => {
      if (e.key === "Enter") e.currentTarget.blur();
      if (e.key === "Escape") { edited.current = false; e.currentTarget.blur(); }
    }} />{error&&<small className="time-field-error" role="alert">{error}</small>}</label>;
}

function SignatureField({ value, title, onChange }: {
  value: TimeSignature; title: string; onChange: (signature: TimeSignature) => void;
}) {
  const formatted = `${value.numerator}/${value.denominator}`;
  const [text, setText] = useState(formatted), [error, setError] = useState("");
  const focused = useRef(false), edited = useRef(false);
  useEffect(() => { if (!focused.current) setText(formatted); }, [formatted]);
  const commit = () => {
    focused.current = false;
    if (edited.current) {
      const match = /^(\d+)\s*\/\s*(1|2|4|8|16|32)$/.exec(text.trim());
      if (match && Number(match[1]) >= 1 && Number(match[1]) <= 32) {
        setError(""); onChange({ numerator: Number(match[1]), denominator: Number(match[2]) });
      } else setError("Enter a signature such as 4/4 or 7/8 (numerator 1–32). ");
    }
    edited.current = false; setText(formatted);
  };
  return <label className="transport-signature" title={error || title}>
    <input aria-label="Time signature" value={text} aria-invalid={!!error}
      onFocus={() => { focused.current = true; setError(""); }}
      onChange={e => { edited.current = true; setError(""); setText(e.target.value); }}
      onBlur={commit} onKeyDown={e => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") { edited.current = false; e.currentTarget.blur(); }
      }}/>
  </label>;
}

export default function Transport({ project, position, playing, buffering, loop, metronome, levels,
  onStart, onStop, onSeek, onLoop, onClick, onTempo, onSignature, onClickPreview, onClickCommit }: {
  project: Project; position: number; playing: boolean; buffering: boolean; levels: number[];
  loop: { start: number; end: number; enabled: boolean }; metronome: boolean;
  onStart: () => void; onStop: () => void; onSeek: (seconds: number) => void;
  onLoop: (loop: { start: number; end: number; enabled: boolean }) => void; onClick: () => void;
  onTempo: (bpm: number) => void; onSignature: (signature: TimeSignature) => void;
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
      <button className={`play-button ${playing && !buffering ? "playing" : ""}`} title="Start / Resume (Num Enter) · Space toggles playback" onClick={onStart} aria-pressed={playing}>
        {buffering ? <LoaderCircle size={18} className="spin"/> : <Play size={18} fill="currentColor"/>}
      </button>
    </div>
    <div className="transport-position">
      <TimeField project={project} format={format} label="Project position" value={position} onChange={onSeek}/>
      <select className="position-format" aria-label="Transport time format" title="Transport time format" value={format} onChange={(e) => setFormat(e.target.value as "bars" | "seconds")}>
        <option value="bars">♩</option><option value="seconds">s</option>
      </select>
    </div>
    <div className="transport-tempo">
      <div title={project.tempos.length ? "Declare a tempo point at the current project cursor" : "Change tempo for the whole project"}>
        <NumberField label="Tempo" commitEqual value={tempo.bpm} min={1} max={1000} step={.25} suffix="BPM" onChange={onTempo}/>
      </div>
      <SignatureField value={signature} onChange={onSignature}
        title={project.signatures.length ? "Declare a signature point at the current cursor · use a whole bar start (x.1.1.0)" : "Change time signature for the whole project"}/>
    </div>
    <div className="transport-spacer"/>
    <div className="metronome-control">
      <button className={`icon-button ${metronome ? "active teal" : ""}`} title="Metronome (C)" aria-pressed={metronome} onClick={onClick}><Activity size={18}/></button>
      <Fader className="click-fader" label="Metronome volume" min={-60} max={MAX_CLICK_BOOST_DB} resetValue={0} value={project.clickGain > 0 ? 20 * Math.log10(project.clickGain/DEFAULT_CLICK_GAIN) : -60}
        onPreview={(db) => onClickPreview(db <= -60 ? 0 : DEFAULT_CLICK_GAIN*10 ** (db / 20))} onCommit={(db) => onClickCommit(db <= -60 ? 0 : DEFAULT_CLICK_GAIN*10 ** (db / 20))}/>
      <GainField label="Click boost" gain={project.clickGain} referenceGain={DEFAULT_CLICK_GAIN} maxDb={MAX_CLICK_BOOST_DB} onChange={onClickCommit}/>
    </div>
    <div className="transport-output" title={`Stereo Out · ${project.sampleRate / 1000} kHz`}>
      <div className="master-meter">{[0,1].map((channel) => <i key={channel} style={{ width: `${Math.min(100, (levels[channel] ?? 0) * 100)}%`, background: levels[channel] > 1 ? "#e78a86" : undefined }}/>)}</div>
      <small>OUT</small>
    </div>
  </section>;
}
