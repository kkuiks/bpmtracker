import { useEffect, useRef } from "react";
import ValueField from "./ValueField";
import { registerValueGesture } from "./valueGesture";
import { registerControlContext } from "./controlContext";

export function NumberField({
  label,
  caption,
  value,
  onChange,
  onPreview,
  step = 0.001,
  min,
  max,
  suffix,
  commitEqual = false,
  resetValue,
  contextKey,
  precision = 3,
  integerSteps = false,
}: {
  label: string;
  caption?: string;
  value: number;
  onChange: (n: number) => void;
  onPreview?: (n: number) => void;
  step?: number;
  min?: number;
  max?: number;
  suffix?: string;
  commitEqual?: boolean;
  resetValue?: number;
  contextKey?: unknown;
  precision?: number;
  integerSteps?: boolean;
}) {
  return (
    <label className="number-field">
      <span>{caption ?? label}</span>
      <div>
        <ValueField label={label} value={value} onChange={onChange} onPreview={onPreview} step={step} min={min} max={max}
          format={number => number.toFixed(precision)}
          adjust={integerSteps ? (number, steps, _segment, fine) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity,
            fine ? Number((number + steps * step * .1).toPrecision(14)) : Math.round(number) + steps * step)) : undefined}
          commitEqual={commitEqual} resetValue={resetValue} contextKey={contextKey}
          title={integerSteps ? "Drag or scroll: whole-number steps · Shift: fine · Double-click to type a number or fraction · Escape: cancel"
            : "Drag or scroll to adjust · Double-click to type a number or fraction · Shift: fine · Escape: cancel"}/>
        {suffix && <small>{suffix}</small>}
      </div>
    </label>
  );
}

export function Fader({
  value,
  min,
  max,
  className,
  label,
  onPreview,
  onCommit,
  resetValue = 0,
  step = 0.1,
}: {
  value: number;
  min: number;
  max: number;
  className: string;
  label: string;
  onPreview: (value: number) => void;
  onCommit: (value: number) => void;
  resetValue?: number;
  step?: number;
}) {
  const dragging = useRef<{ initial: number; node: HTMLInputElement; preview: typeof onPreview; commit: typeof onCommit } | null>(null);
  const cancel = () => {
    const gesture = dragging.current; dragging.current = null;
    if (gesture) { registerValueGesture(gesture.node, null); gesture.preview(gesture.initial); }
  };
  useEffect(() => cancel, []);
  return (
    <input
      className={className}
      aria-label={label}
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onPointerDown={(e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          onCommit(resetValue);
          return;
        }
        if (e.button !== 0) return;
        dragging.current = { initial: value, node: e.currentTarget, preview: onPreview, commit: onCommit };
        registerValueGesture(e.currentTarget, cancel);
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onChange={(e) => {
        if (dragging.current) dragging.current.preview(Number(e.target.value));
        else onCommit(Number(e.target.value));
      }}
      onPointerUp={(e) => {
        const gesture = dragging.current; dragging.current = null;
        if (gesture) registerValueGesture(gesture.node, null);
        if (gesture && Number(e.currentTarget.value) !== gesture.initial) {
          gesture.commit(Number(e.currentTarget.value));
        }
      }}
      onPointerCancel={cancel}
      onLostPointerCapture={cancel}
      onKeyDown={event => {
        if (event.key === "Escape" && dragging.current) { event.preventDefault(); event.stopPropagation(); cancel(); }
      }}
    />
  );
}

export function PanFader({ value, label, onPreview, onCommit }: {
  value: number; label: string; onPreview: (value: number) => void; onCommit: (value: number) => void;
}) {
  const rail = useRef<HTMLDivElement>(null), menuCommit = useRef(onCommit); menuCommit.current = onCommit;
  const gesture = useRef<{ point: number; raw: number; extent: number; value: number; initial: number;
    node: HTMLDivElement; preview: typeof onPreview; commit: typeof onCommit } | null>(null);
  const bounded = (position: number) => Math.max(-100, Math.min(100, position));
  const valueAt = (position: number, extent: number, fine: boolean) =>
    !fine && Math.abs(position) <= 5 && Math.abs(position) / 200 * extent <= 4 ? 0 : Math.round(bounded(position));
  const finish = () => {
    const drag = gesture.current;
    if (!drag) return;
    gesture.current = null;
    registerValueGesture(drag.node, null);
    if (drag.value !== drag.initial) drag.commit(drag.value);
  };
  const cancel = () => {
    const drag = gesture.current; gesture.current = null;
    if (drag) { registerValueGesture(drag.node, null); drag.preview(drag.initial); }
  };
  useEffect(() => cancel, []);
  useEffect(() => {
    const node = rail.current;
    registerControlContext(node, () => {
      const commit = menuCommit.current; cancel();
      return { label, valid: () => !!node?.isConnected && rail.current === node,
        resetLabel: "Reset to Center", reset: () => commit(0) };
    });
    return () => registerControlContext(node, null);
  }, [label]);
  return <div ref={rail} data-slider-control className="pan-slider" role="slider" tabIndex={0} aria-label={label} aria-orientation="horizontal"
    aria-valuemin={-100} aria-valuemax={100} aria-valuenow={value}
    aria-valuetext={value === 0 ? "Center" : `${Math.abs(value)}% ${value < 0 ? "left" : "right"}`}
    title="Drag pan · Shift: fine adjustment without center snap · Ctrl-click: center"
    onPointerDown={(e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.currentTarget.focus();
      if (e.ctrlKey) { onCommit(0); return; }
      const extent = Math.max(1, e.currentTarget.clientWidth - 22);
      const onCap = (e.target as HTMLElement).closest(".pan-cap");
      const raw = onCap ? value : bounded((e.clientX - e.currentTarget.getBoundingClientRect().left - e.currentTarget.clientLeft - 11) / extent * 200 - 100);
      const next = onCap ? value : valueAt(raw, extent, e.shiftKey);
      gesture.current = { point: e.clientX, raw, extent, value: next, initial: value, node: e.currentTarget, preview: onPreview, commit: onCommit };
      registerValueGesture(e.currentTarget, cancel);
      e.currentTarget.setPointerCapture(e.pointerId);
      if (!onCap) onPreview(next);
    }}
    onPointerMove={(e) => {
      const drag = gesture.current;
      if (!drag) return;
      // Keep unsnapped travel so dragging through the center always releases it.
      drag.raw = bounded(drag.raw + (e.clientX - drag.point) / drag.extent * 200 * (e.shiftKey ? .12 : 1));
      drag.point = e.clientX;
      drag.value = valueAt(drag.raw, drag.extent, e.shiftKey);
      drag.preview(drag.value);
    }} onPointerUp={finish} onPointerCancel={cancel} onLostPointerCapture={cancel}
    onKeyDown={(e) => {
      if (e.key === "Escape" && gesture.current) { e.preventDefault(); e.stopPropagation(); cancel(); return; }
      if (gesture.current) return;
      let next: number | null = null;
      if (e.key === "ArrowRight" || e.key === "ArrowUp") next = value + 1;
      if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = value - 1;
      if (e.key === "PageUp") next = value + 10;
      if (e.key === "PageDown") next = value - 10;
      if (e.key === "Home") next = -100;
      if (e.key === "End") next = 100;
      if (next !== null) { e.preventDefault(); e.stopPropagation(); onCommit(bounded(next)); }
    }}>
    <i className="pan-groove" aria-hidden="true"/>
    <i className="pan-zero" aria-hidden="true"/>
    <span className="pan-cap" aria-hidden="true" style={{ left: `calc(11px + (100% - 22px) * ${(value + 100) / 200})` }}/>
  </div>;
}
