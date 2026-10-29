import { useMemo, useRef, useState } from "react";
import { LoaderCircle, Metronome, Play, Repeat2, SkipBack, Square, Volume2 } from "lucide-react";
import { NumberField } from "./controls";
import ValueField from "./ValueField";
import VolumeFader, { GainField } from "./VolumeFader";
import { captureControlContext, controlMenuItems } from "./controlContext";
import { editableText, type MenuPopup } from "./ContextMenu";
import { type Project, type TimeSignature } from "./model";
import { musicalTime, parseMusicalTime, positionAtQuarter, quarterAtTime, quarterAtBar, timeAtQuarter, tempoAtQuarter } from "./music";
import { DEFAULT_CLICK_GAIN, MAX_CLICK_BOOST_DB } from "./click-level";

function secondsText(seconds: number) {
  const ms = Math.floor(Math.max(0, seconds) * 1000);
  return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
export function TimeField({ project, value, label, caption, format = "bars", disabled = false, barStartOnly = false, beatStartOnly = false, min = 0, max, onChange, onPreview }: {
  project: Project; value: number; label: string; caption?: string; format?: "bars" | "seconds"; disabled?: boolean;
  barStartOnly?: boolean; beatStartOnly?: boolean; min?: number; max?: number; onChange: (value: number) => void; onPreview?: (value: number) => void;
}) {
  const mapKey = useMemo(() => [project.id, project.bpm, project.signature.numerator, project.signature.denominator,
    ...project.tempos.flatMap(point => [point.quarter, point.bpm]),
    ...project.signatures.flatMap(point => [point.quarter ?? point.bar, point.numerator, point.denominator])].join(":"),
    [project.id, project.bpm, project.signature, project.tempos, project.signatures]);
  const display = (seconds: number) => format === "bars" ? musicalTime(project, seconds) : secondsText(seconds);
  return <label className="time-field"><span>{caption ?? label}</span><ValueField label={label} value={value}
    disabled={disabled} min={min} max={max} onChange={onChange} onPreview={onPreview} format={display} contextKey={mapKey}
    inputFormat={seconds => format === "bars" ? musicalTime(project, seconds) : String(seconds)}
    parse={text => {
      if (format === "bars") return parseMusicalTime(project, text);
      if (/^\d+(?:\.\d+)?$/.test(text.trim())) return Number(text);
      const parts = text.trim().split(":");
      if ((parts.length === 2 || parts.length === 3) && parts.every((part, i) =>
        i === parts.length - 1 ? /^\d{1,2}(?:\.\d+)?$/.test(part) : /^\d+$/.test(part))) {
        const values = parts.map(Number);
        if (values.at(-1)! < 60 && (values.length === 2 || values[1] < 60)) return values.reduce((total, item) => total * 60 + item, 0);
      }
      return null;
    }}
    parseError={format === "bars" ? "Use Bar.Beat.Sixteenth.Tick, such as 5.1.1.0." : "Use seconds or Hours:Minutes:Seconds.Milliseconds."}
    validate={seconds => {
      const quarter = quarterAtTime(project, seconds);
      const position = positionAtQuarter(project, quarter), beats=(quarter-position.barStart)*position.signature.denominator/4;
      if (barStartOnly && Math.abs(quarter-position.barStart)>=1e-8)
        return "Signature changes need a bar start, such as 5.1.1.0.";
      return beatStartOnly && Math.abs(beats-Math.round(beats))>=1e-8 ? "Use an existing beat boundary, such as 5.3.1.0." : null;
    }}
    segments={seconds => {
      if (format === "bars") {
        const parts = musicalTime(project, seconds).split(".");
        return parts.map((text, i) => ({ text: i === 0 ? text.padStart(3, "0") : text,
          separator: i < 3 ? "." : "", label: ["Bar", "Beat", "Sixteenth", "Tick"][i],
          readOnly: barStartOnly && i > 0 || beatStartOnly && i > 1 }));
      }
      const parts = secondsText(seconds).split(/[:.]/);
      return parts.map((text, i) => ({ text, separator: i < 2 ? ":" : i === 2 ? "." : "",
        label: ["Hours", "Minutes", "Seconds", "Milliseconds"][i] }));
    }}
    adjust={(seconds, steps, part, fine) => {
      if (format === "seconds") return Number(Math.max(0, seconds + steps * [3600, 60, 1, .001][part] * (fine ? .1 : 1)).toFixed(9));
      const quarter = quarterAtTime(project, seconds), position = positionAtQuarter(project, quarter);
      if (barStartOnly || part === 0 && !fine) {
        const bar = Math.max(1, position.bar + Math.trunc(steps)), start = quarterAtBar(project, bar);
        const remainder = barStartOnly ? 0 : Math.min(quarter - position.barStart, quarterAtBar(project, bar + 1) - start - 1 / 480);
        return timeAtQuarter(project, start + remainder);
      }
      if (beatStartOnly) return timeAtQuarter(project, Math.max(0, quarter+Math.round(steps)*4/position.signature.denominator));
      const active = Math.min(3, part + (fine ? 1 : 0));
      return timeAtQuarter(project, Math.max(0, quarter + steps * [0, 4 / position.signature.denominator, .25, 1 / 480][active]));
    }} title={barStartOnly ? "Drag the bar · Double-click to type x.1.1.0 · Escape: cancel"
      : "Drag a position segment · Double-click to type or paste · Shift: fine · Escape: cancel"}/></label>;
}

export function SignatureField({ value, title, onChange, disabled = false }: {
  value: TimeSignature; title: string; onChange: (signature: Partial<TimeSignature>) => boolean; disabled?: boolean;
}) {
  const owner = useRef(onChange);
  const [held, setHeld] = useState<TimeSignature | null>(null);
  const shown = held ?? value;
  const hold = () => setHeld({ numerator: value.numerator, denominator: value.denominator });
  return <div className="transport-signature" title={title}>
    <ValueField label="Signature numerator" value={shown.numerator} disabled={disabled} min={1} max={32} step={1}
      onEditStart={hold} onEditEnd={() => setHeld(null)}
      parse={text => /^\d+$/.test(text.trim()) ? Number(text) : null}
      parseError="Enter a whole-number numerator from 1 to 32."
      adjust={(number, steps) => Math.max(1, Math.min(32, number + Math.trunc(steps)))}
      onChange={numerator => onChange({ numerator })}/><span aria-hidden="true">/</span>
    <select aria-label="Signature denominator" value={shown.denominator} disabled={disabled}
      onFocus={() => { owner.current = onChange; hold(); }} onBlur={() => setHeld(null)}
      onChange={event => {
        const denominator = Number(event.target.value);
        const focused = document.activeElement === event.currentTarget;
        const accepted = (focused ? owner.current : onChange)({ denominator });
        setHeld(focused && accepted ? { ...shown, denominator } : null);
      }}>
      {[1, 2, 4, 8, 16, 32].map(denominator => <option key={denominator} value={denominator}>{denominator}</option>)}
    </select>
  </div>;
}

export default function Transport({ project, position, playing, buffering, loop, metronome, levels,
  onStart, onStop, onSeek, onLoop, onClick, onTempo, onSignature, onClickPreview, onClickCommit,
  onMasterPreview, onMasterCommit, onMenu }: {
  project: Project; position: number; playing: boolean; buffering: boolean; levels: number[];
  loop: { start: number; end: number; enabled: boolean }; metronome: boolean;
  onStart: () => void; onStop: () => void; onSeek: (seconds: number) => void;
  onLoop: (loop: { start: number; end: number; enabled: boolean }) => void; onClick: () => void;
  onTempo: (bpm: number, at: number) => void; onSignature: (signature: Partial<TimeSignature>, at: number) => boolean;
  onClickPreview: (gain: number) => void; onClickCommit: (gain: number) => void;
  onMasterPreview: (gain: number) => void; onMasterCommit: (gain: number) => void;
  onMenu: (menu: MenuPopup) => void;
}) {
  const [format, setFormat] = useState<"bars" | "seconds">("bars");
  const quarter = quarterAtTime(project, position), tempo = tempoAtQuarter(project, quarter);
  const signature = positionAtQuarter(project, quarter).signature;
  return <section className="transport-bar" aria-label="Transport" onContextMenu={event => {
    if (editableText(event.target)) return;
    const target = event.target as HTMLElement;
    if (!target.closest(".transport-position,.locator-field")) return;
    const actions = captureControlContext(target); if (!actions) return;
    event.preventDefault(); event.stopPropagation();
    onMenu({ x: event.clientX, y: event.clientY, title: actions.label,
      invoker: target.closest<HTMLElement>("[data-value-control]")?.querySelector("input"), restoreFocus: actions.restoreFocus,
      items: [...controlMenuItems(actions), { separator: true }, { label: "Time Format", submenu: [
        { label: "Bars + Beats", checked: format === "bars", action: () => setFormat("bars") },
        { label: "Seconds", checked: format === "seconds", action: () => setFormat("seconds") },
      ] }] });
  }}>
    <div className="locator-fields">
      <div className="locator-field"><button title="Go to left locator (Num 1)" onClick={() => onSeek(loop.start)}>L</button>
        <TimeField project={project} format={format} label="Left locator" value={loop.start} onChange={(start) => onLoop({ ...loop, start, end: Math.max(loop.end, start + .001) })}/></div>
      <div className="locator-field"><button title="Go to right locator (Num 2)" onClick={() => onSeek(loop.end)}>R</button>
        <TimeField project={project} format={format} label="Right locator" value={loop.end} onChange={(end) => onLoop({ ...loop, start: Math.min(loop.start, Math.max(0, end - .001)), end })}/></div>
    </div>
    <span className="transport-divider"/>
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
    </div>
    <span className="transport-divider"/>
    <div className="transport-tempo">
      <div title="Declare or update a tempo point at the current project cursor">
        <NumberField label="Tempo" commitEqual value={tempo.bpm}
          min={1} max={1000} resetValue={120} step={1} integerSteps suffix="BPM" precision={3} contextKey={project.tempos}
          onChange={bpm => onTempo(bpm, position)}/>
      </div>
    </div>
      <SignatureField value={signature} onChange={value => onSignature(value, position)}
        title={project.signatures.length ? "Declare a signature point at the current cursor · use an existing beat boundary" : "Change time signature for the whole project"}/>
    <span className="transport-divider"/>
    <div className="metronome-control">
      <button className={`icon-button ${metronome ? "active teal" : ""}`} title="Metronome (C)" aria-pressed={metronome} onClick={onClick}><Metronome size={18}/></button>
      <GainField label="Click boost" gain={project.clickGain} referenceGain={DEFAULT_CLICK_GAIN} maxDb={MAX_CLICK_BOOST_DB} onChange={onClickCommit}/>
    </div>
    <div className="transport-spacer"/>
    <div className="transport-output" title={`Stereo Out · ${project.sampleRate / 1000} kHz`}>
      <Volume2 size={17} aria-label="Output"/>
      <VolumeFader label="Master volume slider" gain={project.masterGain} horizontal onPreview={onMasterPreview} onCommit={onMasterCommit}/>
      <GainField label="Output level" gain={project.masterGain} onChange={onMasterCommit}/>
      <div className="master-meter">{[0,1].map((channel) => <i key={channel} style={{ width: `${Math.min(100, (levels[channel] ?? 0) * 100)}%`, background: levels[channel] > 1 ? "#e78a86" : undefined }}/>)}</div>
    </div>
  </section>;
}
