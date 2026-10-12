import { useEffect, useRef } from "react";
import ValueField, { parseNumber } from "./ValueField";
import { registerValueGesture } from "./valueGesture";
import { registerControlContext } from "./controlContext";

// More travel near normal mix levels; the bottom detent is silence.
const scale = [[.03, -60], [.15, -48], [.32, -30], [.50, -18], [.68, -6], [.82, 0], [1, 6]];
const clamp = (value: number) => Math.max(0, Math.min(1, value));
const unityTravel = travelForDb(0);
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
function gainWithDetent(travel: number, extent: number, fine: boolean) {
  const gain = gainForTravel(travel);
  return !fine && gain > 0 && Math.abs(20 * Math.log10(gain)) <= .5 && Math.abs(travel - unityTravel) * extent <= 4 ? 1 : gain;
}
export function GainField({ gain, label, onChange, referenceGain=1, maxDb=6 }: {
  gain: number; label: string; onChange: (gain: number) => void; referenceGain?:number;maxDb?:number;
}) {
  const db = (value: number) => value > 0 ? 20 * Math.log10(value / referenceGain) : -96;
  return <label className="gain-field"><span>{label}</span><ValueField label={label} value={gain} onChange={onChange}
    min={0} max={referenceGain * 10 ** (maxDb / 20)} resetValue={referenceGain} resetLabel="Reset to 0 dB"
    format={value => value > 0 ? db(value).toFixed(2) : "−∞"}
    inputFormat={value => value > 0 ? String(db(value)) : "−∞"}
    parse={text => {
      if (/^(?:-inf|-infinity|-∞|−∞)$/i.test(text.trim())) return 0;
      const value = parseNumber(text);
      return value !== null && value >= -96 && value <= maxDb ? referenceGain * 10 ** (value / 20) : null;
    }}
    parseError={`Enter −∞ for silence, or a dB value from −96 to +${maxDb}.`}
    adjust={(value, steps, _part, fine) => {
      const next = Math.max(-96, Math.min(maxDb, db(value) + steps * (fine ? .01 : .1)));
      return next <= -96 ? 0 : referenceGain * 10 ** (next / 20);
    }} title={`Drag up/down · Double-click for dB entry (−96 to +${maxDb}) · Ctrl-click: 0 dB · Escape: cancel`}/><small>dB</small></label>;
}

export default function VolumeFader({ gain, label, compact = false, horizontal = false, onPreview, onCommit }: {
  gain: number; label: string; compact?: boolean; horizontal?: boolean; onPreview: (gain: number) => void; onCommit: (gain: number) => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ point: number; travel: number; extent: number; gain: number; initial: number;
    node: HTMLDivElement; preview: typeof onPreview; commit: typeof onCommit } | null>(null);
  const db = gain > 0 ? 20 * Math.log10(gain) : -60;
  const travel = gain > 0 ? travelForDb(db) : 0;
  const positionAt = (point: number) => {
    const node = rail.current!, rect = node.getBoundingClientRect();
    return horizontal ? clamp((point - rect.left - node.clientLeft - 11) / Math.max(1, node.clientWidth - 22))
      : clamp(1 - (point - rect.top - node.clientTop - 11) / Math.max(1, node.clientHeight - 22));
  };
  const finish = () => {
    const drag = gesture.current;
    if (!drag) return;
    gesture.current = null;
    registerValueGesture(drag.node, null);
    if (drag.gain !== drag.initial) drag.commit(drag.gain);
  };
  const cancel = () => {
    const drag = gesture.current; gesture.current = null;
    if (drag) { registerValueGesture(drag.node, null); drag.preview(drag.initial); }
  };
  useEffect(() => cancel, []);
  const menuCommit = useRef(onCommit); menuCommit.current = onCommit;
  useEffect(() => {
    const node = rail.current;
    registerControlContext(node, () => {
      const commit = menuCommit.current; cancel();
      return { label, valid: () => !!node?.isConnected && rail.current === node,
        resetLabel: "Reset to 0 dB", reset: () => commit(1) };
    });
    return () => registerControlContext(node, null);
  }, [label]);
  return <div className={`channel-volume-fader ${compact ? "compact" : ""} ${horizontal ? "horizontal" : ""}`}>
    <div className="volume-rail" ref={rail} data-slider-control role="slider" tabIndex={0} aria-label={label} aria-orientation={horizontal ? "horizontal" : "vertical"}
      aria-valuemin={-60} aria-valuemax={6} aria-valuenow={Math.max(-60, Math.min(6, db))} aria-valuetext={gain > 0 ? `${db.toFixed(1)} dB` : "Silence, minus infinity dB"}
      title="Drag volume · Shift: fine adjustment without 0 dB snap · Ctrl-click: 0 dB"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault(); e.currentTarget.focus();
        if (e.ctrlKey) { onCommit(1); return; }
        e.currentTarget.setPointerCapture(e.pointerId);
        const onCap = (e.target as HTMLElement).closest(".fader-cap");
        const point = horizontal ? e.clientX : e.clientY;
        const initial = onCap ? travel : positionAt(point);
        const extent = Math.max(1, (horizontal ? e.currentTarget.clientWidth : e.currentTarget.clientHeight) - 22);
        const value = onCap ? gain : gainWithDetent(initial, extent, e.shiftKey);
        gesture.current = { point, travel: initial, extent, gain: value, initial: gain, node: e.currentTarget, preview: onPreview, commit: onCommit };
        registerValueGesture(e.currentTarget, cancel);
        if (!onCap) onPreview(value);
      }}
      onPointerMove={(e) => {
        const drag = gesture.current;
        if (!drag) return;
        const point = horizontal ? e.clientX : e.clientY;
        const delta = (point - drag.point) / drag.extent * (horizontal ? 1 : -1) * (e.shiftKey ? .12 : 1);
        const position = clamp(drag.travel + delta);
        drag.gain = gainWithDetent(position, drag.extent, e.shiftKey);
        // Rebase unsnapped travel; Shift changes and leaving the detent cannot jump or stick.
        drag.point = point; drag.travel = position;
        drag.preview(drag.gain);
      }} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel}
      onKeyDown={(e) => {
        if (e.key === "Escape" && gesture.current) { e.preventDefault(); e.stopPropagation(); cancel(); return; }
        if (gesture.current) return;
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
      <i className="fader-zero" aria-hidden="true" style={horizontal ? { left: `calc(11px + (100% - 22px) * ${unityTravel})` } : { bottom: `calc(11px + (100% - 22px) * ${unityTravel})` }}/>
      <span className="fader-cap" style={horizontal ? { left: `calc(11px + (100% - 22px) * ${travel})` } : { bottom: `calc(11px + (100% - 22px) * ${travel})` }}><i/><i/><i/></span>
    </div>
    <div className="fader-scale" aria-hidden="true">{[6, 0, -6, -12, -18, -30, -48].map((value) =>
      <span key={value} style={{ bottom: `calc(11px + (100% - 22px) * ${travelForDb(value)})` }}>{value > 0 ? "+" : ""}{value}</span>)}<span style={{ bottom: 11 }}>−∞</span></div>
  </div>;
}
