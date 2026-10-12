import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { registerValueGesture } from "./valueGesture";
import { registerControlContext, type ControlActions } from "./controlContext";

export type ValueSegment = { text: string; separator: string; label: string; digits: number };
type Props = {
  label: string;
  value: number;
  onChange: (value: number) => void;
  onPreview?: (value: number) => void;
  format?: (value: number) => string;
  inputFormat?: (value: number) => string;
  parse?: (text: string) => number | null;
  parseError?: string;
  adjust?: (value: number, steps: number, segment: number, fine: boolean) => number;
  segments?: (value: number) => ValueSegment[];
  validate?: (value: number) => string | null;
  min?: number;
  max?: number;
  step?: number;
  resetValue?: number;
  resetLabel?: string;
  pixelsPerStep?: number;
  disabled?: boolean;
  commitEqual?: boolean;
  contextKey?: unknown;
  title?: string;
  onEditStart?: () => void;
  onEditEnd?: () => void;
};

export function parseNumber(text: string): number | null {
  const input = text.trim().replace(/−/g, "-");
  const fraction = /^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\/\s*(\d+(?:\.\d*)?|\.\d+)$/.exec(input);
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(input);
  const number = fraction ? Number(fraction[1]) / Number(fraction[2]) : decimal ? Number(input) : NaN;
  return Number.isFinite(number) ? number : null;
}

const displayNumber = (value: number) => String(Number(value.toFixed(6)));
type Edit = {
  value: number;
  onChange: Props["onChange"];
  parse: NonNullable<Props["parse"]>;
  adjust: NonNullable<Props["adjust"]>;
  inputFormat: NonNullable<Props["inputFormat"]>;
  validate: (value: number) => string | null;
  title: string;
  commitEqual: boolean;
  parseError: string;
  onEditEnd?: () => void;
  onPreview?: Props["onPreview"];
  previewed: boolean;
  onEditStart?: () => void;
  resetValue?: number;
  resetLabel?: string;
  contextKey?: unknown;
};

function ValueError({ input, id, message }: { input: HTMLInputElement | null; id: string; message: string }) {
  const [position, setPosition] = useState({ left: 0, top: 0 });
  useLayoutEffect(() => {
    if (!input) return;
    const place = () => {
      const bounds = input.getBoundingClientRect();
      setPosition({ left: Math.max(8, Math.min(bounds.left, window.innerWidth - 278)),
        top: bounds.bottom + 52 < window.innerHeight ? bounds.bottom + 6 : Math.max(8, bounds.top - 52) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [input]);
  return createPortal(<div id={id} className="value-error" role="alert" style={position}>
    <b aria-hidden="true">!</b><span>{message}</span>
  </div>, document.body);
}

/** One editing transaction, whether initiated by typing, scrubbing or hover stepping. */
export default function ValueField(props: Props) {
  const { label, value, disabled = false, format = displayNumber, segments } = props;
  const input = useRef<HTMLInputElement>(null);
  const control = useRef<HTMLDivElement>(null);
  const current = useRef(props); current.current = props;
  const edit = useRef<Edit | null>(null);
  const textRef = useRef("");
  const changed = useRef(false);
  const pointerFocus = useRef(false);
  const drag = useRef<{ y: number; steps: number; travel: number; value: number; moved: boolean; segment: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mode, setMode] = useState<"idle" | "typing" | "scrubbing" | "stepping">("idle");
  const modeRef = useRef(mode); modeRef.current = mode;
  const [text, setText] = useState("");
  const [draft, setDraft] = useState(value);
  const draftRef = useRef(value);
  const [segment, setSegment] = useState(0);
  const segmentRef = useRef(0);
  const [error, setError] = useState("");
  const errorId = useId();
  const clearTimer = () => { if (timer.current !== null) clearTimeout(timer.current); timer.current = null; };
  const snapshot = (): Edit => {
    const p = current.current;
    const validate = (number: number) => {
      if (!Number.isFinite(number)) return "Enter a valid number.";
      if (p.min !== undefined && number < p.min || p.max !== undefined && number > p.max)
        return p.min !== undefined && p.max !== undefined ? `Enter a value from ${p.min} to ${p.max}.`
          : p.min !== undefined ? `Enter a value of ${p.min} or more.` : `Enter a value of ${p.max} or less.`;
      return p.validate?.(number) ?? null;
    };
    return { value: p.value, onChange: p.onChange, parse: p.parse ?? parseNumber,
      inputFormat: p.inputFormat ?? String, validate,
      adjust: p.adjust ?? ((n, steps, _segment, fine) => Math.min(p.max ?? Infinity,
        Math.max(p.min ?? -Infinity, Number((n + steps * (p.step ?? .001) * (fine ? .1 : 1)).toPrecision(14))))),
      title: p.title ?? "Drag up/down · Double-click to type · Shift: fine · Escape: cancel",
      parseError: p.parseError ?? "Enter a valid number or fraction, such as 120 or 400/3.",
      onEditEnd: p.onEditEnd,
      onEditStart: p.onEditStart, resetValue: p.resetValue, resetLabel: p.resetLabel, contextKey: p.contextKey,
      onPreview: p.onPreview, previewed: false,
      commitEqual: p.commitEqual ?? false };
  };
  const begin = (captured?: Edit) => {
    if (edit.current) return edit.current;
    const transaction = captured ?? snapshot();
    edit.current = transaction;
    changed.current = false;
    draftRef.current = transaction.value; setDraft(transaction.value);
    registerValueGesture(input.current, () => finish(true));
    transaction.onEditStart?.();
    return edit.current;
  };
  const finish = (cancel = false, next = draftRef.current, force = false) => {
    const transaction = edit.current;
    clearTimer(); drag.current = null; edit.current = null; changed.current = false;
    registerValueGesture(input.current, null);
    modeRef.current = "idle"; setMode("idle"); setError("");
    // Return to the captured baseline before committing once to project history.
    if (transaction?.previewed) transaction.onPreview?.(transaction.value);
    if (!cancel && transaction && (next !== transaction.value || force && transaction.commitEqual))
      transaction.onChange(next);
    transaction?.onEditEnd?.();
  };
  const enterText = (initial?: string, captured?: Edit) => {
    clearTimer();
    const transaction = begin(captured);
    const next = initial ?? transaction.inputFormat(draftRef.current);
    textRef.current = next; setText(next); changed.current = initial !== undefined;
    modeRef.current = "typing"; setMode("typing"); setError("");
    queueMicrotask(() => { input.current?.focus({ preventScroll: true }); if (initial === undefined) input.current?.select(); });
  };
  const commitText = () => {
    if (!changed.current) { finish(true); return; }
    const transaction = edit.current;
    if (!transaction) return;
    const number = transaction.parse(textRef.current);
    const problem = number === null ? transaction.parseError : transaction.validate(number);
    if (problem) { setError(problem); return; }
    finish(false, number!, true);
  };
  const step = (direction: number, fine: boolean) => {
    const transaction = begin();
    const typing = modeRef.current === "typing";
    const original = typing ? transaction.parse(textRef.current) : draftRef.current;
    if (original === null) { setError("Correct the value before adjusting it."); return; }
    const next = transaction.adjust(original, direction, segmentRef.current, fine);
    const problem = transaction.validate(next);
    if (problem) { setError(problem); return; }
    changed.current = true; draftRef.current = next; setDraft(next); setError("");
    if (transaction.onPreview) { transaction.previewed = true; transaction.onPreview(next); }
    if (typing) { textRef.current = transaction.inputFormat(next); setText(textRef.current); }
    else {
      modeRef.current = "stepping"; setMode("stepping"); clearTimer();
      timer.current = setTimeout(() => finish(), 220);
    }
  };
  const wheelStep = useRef(step); wheelStep.current = step;
  useEffect(() => {
    const node = control.current;
    if (!node) return;
    const wheel = (event: WheelEvent) => {
      if (disabled || event.ctrlKey || !event.deltaY || drag.current) return;
      event.preventDefault(); event.stopPropagation();
      const part = (event.target as Element).closest<HTMLElement>("[data-value-segment]");
      if (part) { segmentRef.current = Number(part.dataset.valueSegment); setSegment(segmentRef.current); }
      wheelStep.current(event.deltaY < 0 ? 1 : -1, event.shiftKey);
    };
    node.addEventListener("wheel", wheel, { passive: false });
    return () => node.removeEventListener("wheel", wheel);
  }, [disabled]);
  useEffect(() => {
    // A different selected object/project must not inherit a pending edit.
    finish(true);
  }, [props.contextKey]);
  useEffect(() => { const node = input.current; return () => {
    clearTimer();
    const transaction = edit.current;
    edit.current = null; drag.current = null; registerValueGesture(node, null);
    if (transaction?.previewed) transaction.onPreview?.(transaction.value);
    transaction?.onEditEnd?.();
  }; }, []);
  const displayed = mode === "idle" ? value : draft;
  const parts = segments?.(displayed);
  const typing = mode === "typing";
  const startPointer = (event: { button: number; clientY: number; pointerId: number; ctrlKey: boolean; preventDefault: () => void }) => {
    // A right click on a readout opens its value menu without starting text entry.
    if (event.button === 2 && modeRef.current !== "typing") { event.preventDefault(); return; }
    if (event.button !== 0 || modeRef.current === "typing" || disabled) return;
    event.preventDefault(); pointerFocus.current = true;
    input.current?.focus({ preventScroll: true }); pointerFocus.current = false;
    if (event.ctrlKey && props.resetValue !== undefined) { begin(); finish(false, props.resetValue); return; }
    begin();
    drag.current = { y: event.clientY, steps: 0, travel: 0, value: draftRef.current, moved: false, segment: segmentRef.current };
    input.current?.setPointerCapture(event.pointerId);
  };
  const menuCapture = useRef<() => ControlActions | null>(() => null);
  menuCapture.current = () => {
    if (current.current.disabled || modeRef.current === "typing") return null;
    const captured = edit.current ? { ...edit.current, previewed: false } : snapshot();
    if (edit.current) finish(true);
    const node = input.current!, owner = control.current!;
    const valid = () => node.isConnected && control.current === owner && !current.current.disabled && current.current.contextKey === captured.contextKey;
    return { label: current.current.label, valid,
      restoreFocus: () => { if (valid()) { pointerFocus.current = true; node.focus({ preventScroll: true }); pointerFocus.current = false; } },
      edit: () => { if (valid()) enterText(undefined, captured); },
      copy: async () => { if (valid()) await navigator.clipboard.writeText(captured.inputFormat(captured.value)); },
      paste: async () => { const text = await navigator.clipboard.readText(); if (valid()) enterText(text, captured); },
      reset: captured.resetValue === undefined ? undefined : () => { if (valid()) { begin(captured); finish(false, captured.resetValue); } },
      resetLabel: captured.resetLabel ?? (captured.resetValue === undefined ? undefined : `Reset to ${captured.inputFormat(captured.resetValue)}`),
    };
  };
  useEffect(() => {
    const node = control.current;
    registerControlContext(node, () => menuCapture.current());
    return () => registerControlContext(node, null);
  }, []);
  return <div ref={control} className={`value-control ${parts ? "segmented" : ""} ${error ? "invalid" : ""}`}
    data-value-control data-state={mode} onDoubleClick={() => { if (!disabled) enterText(); }}>
    <input ref={input} aria-label={label} type="text" inputMode="text" disabled={disabled}
      role={typing ? undefined : "spinbutton"} aria-valuenow={typing ? undefined : displayed}
      aria-valuemin={typing ? undefined : props.min} aria-valuemax={typing ? undefined : props.max}
      aria-valuetext={typing ? undefined : format(displayed)} aria-invalid={!!error}
      aria-describedby={error ? errorId : undefined} readOnly={!typing}
      value={typing ? text : format(displayed)}
      title={`${edit.current?.title ?? props.title ?? "Drag up/down · Double-click to type · Shift: fine · Escape: cancel"}\nValue: ${(props.inputFormat ?? String)(displayed)}`}
      onFocus={() => { if (!pointerFocus.current && modeRef.current === "idle") enterText(); }}
      onChange={event => { changed.current = true; textRef.current = event.target.value; setText(event.target.value); setError(""); }}
      onCopy={event => {
        if (modeRef.current === "typing") return;
        event.preventDefault(); event.stopPropagation();
        event.clipboardData.setData("text/plain", (props.inputFormat ?? String)(value));
      }}
      onCut={event => {
        if (modeRef.current === "typing") return;
        event.preventDefault(); event.stopPropagation();
        event.clipboardData.setData("text/plain", (props.inputFormat ?? String)(value)); enterText("");
      }}
      onPaste={event => {
        event.preventDefault(); event.stopPropagation(); enterText(event.clipboardData.getData("text/plain"));
      }}
      onBlur={() => { if (modeRef.current === "typing") commitText(); else if (!drag.current) finish(); }}
      onPointerDown={startPointer}
      onPointerMove={event => {
        const gesture = drag.current, transaction = edit.current;
        if (!gesture || !transaction) return;
        const movement = gesture.y - event.clientY;
        gesture.travel += movement;
        gesture.steps += movement / (props.pixelsPerStep ?? 4); gesture.y = event.clientY;
        if (!gesture.moved && Math.abs(gesture.travel) < 3) return;
        gesture.moved = true;
        const steps = Math.trunc(gesture.steps); gesture.steps -= steps;
        if (!steps) return;
        const next = transaction.adjust(gesture.value, steps, gesture.segment, event.shiftKey);
        if (transaction.validate(next)) return;
        gesture.value = next;
        if (transaction.onPreview) { transaction.previewed = true; transaction.onPreview(next); }
        draftRef.current = next; setDraft(next); modeRef.current = "scrubbing"; setMode("scrubbing");
      }}
      onPointerUp={() => {
        const gesture = drag.current;
        if (!gesture) return;
        if (gesture.moved) finish(); else { drag.current = null; finish(true); }
      }}
      onPointerCancel={() => finish(true)}
      onLostPointerCapture={() => { if (drag.current) finish(true); }}
      onKeyDown={event => {
        if (event.key === "Escape") {
          if (edit.current || error) { event.preventDefault(); event.stopPropagation(); finish(true); }
          return;
        }
        if ((event.ctrlKey || event.metaKey) && ["c", "x", "v"].includes(event.key.toLowerCase())) {
          event.stopPropagation();
          if (modeRef.current !== "typing") {
            if (event.key.toLowerCase() === "v") enterText(); else input.current?.select();
          }
          return;
        }
        if (event.key === "Enter") {
          event.preventDefault(); event.stopPropagation();
          if (modeRef.current === "typing") commitText(); else enterText();
          return;
        }
        if (drag.current) { if (event.key !== "Shift" && event.key !== "Control") event.stopPropagation(); return; }
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault(); event.stopPropagation(); step(event.key === "ArrowUp" ? 1 : -1, event.shiftKey); return;
        }
        if (modeRef.current !== "typing" && parts && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
          event.preventDefault(); event.stopPropagation();
          segmentRef.current = Math.max(0, Math.min(parts.length - 1, segmentRef.current + (event.key === "ArrowRight" ? 1 : -1)));
          setSegment(segmentRef.current); return;
        }
        if (modeRef.current !== "typing" && !event.ctrlKey && !event.metaKey && !event.altKey && /^[\d.+\-/]$/.test(event.key)) {
          event.preventDefault(); event.stopPropagation(); enterText(event.key);
        }
        if (modeRef.current !== "typing" && (event.key === "Delete" || event.key === "Backspace")) {
          event.preventDefault(); event.stopPropagation(); enterText("");
        }
        if (modeRef.current === "typing") event.stopPropagation();
      }}/>
    {parts && !typing && <div className="value-segments" aria-hidden="true">
      {parts.map((part, index) => <span key={index} className={segment === index ? "current-segment" : ""}
        data-value-segment={index} style={{ width: `${part.digits + part.separator.length}ch` }}
        title={`${part.label} · Drag up/down · Double-click to type`}
        onPointerDown={event => {
          segmentRef.current = index; setSegment(index);
          startPointer(event);
        }}><span className="value-segment-number">{part.text}</span><i style={{ width: `${part.separator.length}ch` }}>{part.separator}</i></span>)}
    </div>}
    {error && <ValueError input={input.current} id={errorId} message={error}/>}
  </div>;
}
