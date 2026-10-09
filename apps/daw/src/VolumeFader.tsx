import { useEffect, useRef, useState } from "react";

// More travel near normal mix levels; the bottom detent is silence.
const scale = [[.03, -60], [.15, -48], [.32, -30], [.50, -18], [.68, -6], [.82, 0], [1, 6]];
const clamp = (value: number) => Math.max(0, Math.min(1, value));
function travelForDb(db: number) {
  if (db <= -60) return .03;
  for (let i = 1; i < scale.length; i++) {
    if (db <= scale[i][1]) return scale[i - 1][0] + (db - scale[i - 1][1]) / (scale[i][1] - scale[i - 1][1]) * (scale[i][0] - scale[i - 1][0]);
  }
  return 1;
}
function gainForTravel(travel: number) {
  if (travel < .015) return 0;
  travel = Math.max(.03, clamp(travel));
  for (let i = 1; i < scale.length; i++) {
    if (travel <= scale[i][0]) {
      const db = scale[i - 1][1] + (travel - scale[i - 1][0]) / (scale[i][0] - scale[i - 1][0]) * (scale[i][1] - scale[i - 1][1]);
      return 10 ** (Math.round(db * 10) / 10 / 20);
    }
  }
  return 10 ** (6 / 20);
}
export function GainField({ gain, label, onChange, referenceGain=1, maxDb=6 }: {
  gain: number; label: string; onChange: (gain: number) => void; referenceGain?:number;maxDb?:number;
}) {
  const formatted = gain > 0 ? (20 * Math.log10(gain/referenceGain)).toFixed(2) : "−∞";
  const [text, setText] = useState(formatted);
  const focused = useRef(false), edited = useRef(false);
  useEffect(() => { if (!focused.current) setText(formatted); }, [formatted]);
  const commit = () => {
    focused.current = false;
    if (edited.current) {
      const input = text.trim();
      if (/^(?:-inf|-infinity|-∞|−∞)$/i.test(input)) onChange(0);
      else {
        const db = input ? Number(input) : NaN;
        if (Number.isFinite(db) && db >= -96 && db <= maxDb) onChange(referenceGain*10 ** (db / 20));
      }
    }
    edited.current = false;
    setText(formatted);
  };
  return <label className="gain-field"><span>{label}</span><input aria-label={label} inputMode="decimal" value={text}
    onFocus={() => { focused.current = true; }} onChange={(e) => { edited.current = true; setText(e.target.value); }} onBlur={commit}
    onKeyDown={(e) => {
      if (e.key === "Enter") e.currentTarget.blur();
      if (e.key === "Escape") { edited.current = false; e.currentTarget.blur(); }
    }}/><small>dB</small></label>;
}

export default function VolumeFader({ gain, label, compact = false, onPreview, onCommit }: {
  gain: number; label: string; compact?: boolean; onPreview: (gain: number) => void; onCommit: (gain: number) => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ y: number; travel: number; height: number; gain: number } | null>(null);
  const db = gain > 0 ? 20 * Math.log10(gain) : -60;
  const travel = gain > 0 ? travelForDb(db) : 0;
  const positionAt = (y: number) => {
    const rect = rail.current!.getBoundingClientRect();
    return clamp(1 - (y - rect.top - 11) / Math.max(1, rect.height - 22));
  };
  const finish = () => {
    const drag = gesture.current;
    if (!drag) return;
    gesture.current = null;
    onCommit(drag.gain);
  };
  return <div className={`channel-volume-fader ${compact ? "compact" : ""}`}>
    <div className="volume-rail" ref={rail} role="slider" tabIndex={0} aria-label={label} aria-orientation="vertical"
      aria-valuemin={-60} aria-valuemax={6} aria-valuenow={Math.max(-60, Math.min(6, db))} aria-valuetext={gain > 0 ? `${db.toFixed(1)} dB` : "Silence, minus infinity dB"}
      title="Drag volume · Shift: fine adjustment · Ctrl-click: 0 dB"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault(); e.currentTarget.focus();
        if (e.ctrlKey) { onCommit(1); return; }
        e.currentTarget.setPointerCapture(e.pointerId);
        const onCap = (e.target as HTMLElement).closest(".fader-cap");
        const initial = onCap ? travel : positionAt(e.clientY);
        const value = onCap ? gain : gainForTravel(initial);
        gesture.current = { y: e.clientY, travel: initial, height: Math.max(1, e.currentTarget.clientHeight - 22), gain: value };
        if (!onCap) onPreview(value);
      }}
      onPointerMove={(e) => {
        const drag = gesture.current;
        if (!drag) return;
        const delta = (drag.y - e.clientY) / drag.height * (e.shiftKey ? .12 : 1);
        const position = clamp(drag.travel + delta);
        drag.gain = gainForTravel(position);
        // Rebase on every movement, so pressing/releasing Shift does not jump.
        drag.y = e.clientY; drag.travel = position;
        onPreview(drag.gain);
      }} onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish}
      onKeyDown={(e) => {
        const step = e.shiftKey ? .1 : .5;
        let next: number | null = null;
        if (e.key === "ArrowUp" || e.key === "ArrowRight") next = 10 ** (Math.min(6, db + step) / 20);
        if (e.key === "ArrowDown" || e.key === "ArrowLeft") next = db <= -60 + step ? 0 : 10 ** ((db - step) / 20);
        if (e.key === "PageUp") next = 10 ** (Math.min(6, db + 3) / 20);
        if (e.key === "PageDown") next = db <= -57 ? 0 : 10 ** ((db - 3) / 20);
        if (e.key === "Home") next = 0;
        if (e.key === "End") next = 10 ** (6 / 20);
        if (next !== null) { e.preventDefault(); e.stopPropagation(); onCommit(next); }
      }}>
      <i className="fader-groove"/>
      <span className="fader-cap" style={{ bottom: `calc(11px + (100% - 22px) * ${travel})` }}><i/><i/><i/></span>
    </div>
    <div className="fader-scale" aria-hidden="true">{[6, 0, -6, -12, -18, -30, -48].map((value) =>
      <span key={value} style={{ bottom: `calc(11px + (100% - 22px) * ${travelForDb(value)})` }}>{value > 0 ? "+" : ""}{value}</span>)}<span style={{ bottom: 11 }}>−∞</span></div>
  </div>;
}
