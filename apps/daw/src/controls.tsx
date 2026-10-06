import { useEffect, useRef, useState } from "react";

export function NumberField({
  label,
  value,
  onChange,
  step = 0.001,
  min,
  max,
  suffix,
  commitEqual = false,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number;
  min?: number;
  max?: number;
  suffix?: string;
  commitEqual?: boolean;
}) {
  const [text, setText] = useState(String(Number(value.toFixed(6))));
  const changed = useRef(false);
  useEffect(() => setText(String(Number(value.toFixed(6)))), [value]);
  const commit = () => {
    if (!changed.current) return;
    changed.current = false;
    const n = Number(text);
    if (
      Number.isFinite(n) &&
      (min === undefined || n >= min) &&
      (max === undefined || n <= max)
    ) {
      if (n !== value || commitEqual) onChange(n);
    } else setText(String(value));
  };
  return (
    <label className="number-field">
      <span>{label}</span>
      <div>
        <input
          aria-label={label}
          type="number"
          step={step}
          min={min}
          max={max}
          value={text}
          onChange={(e) => {
            changed.current = true;
            setText(e.target.value);
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              changed.current = false;
              setText(String(value));
              e.currentTarget.blur();
            }
          }}
        />
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
  const dragging = useRef(false);
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
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onChange={(e) => {
        if (dragging.current) onPreview(Number(e.target.value));
        else onCommit(Number(e.target.value));
      }}
      onPointerUp={(e) => {
        if (dragging.current) {
          dragging.current = false;
          onCommit(Number(e.currentTarget.value));
        }
      }}
      onPointerCancel={(e) => {
        if (dragging.current) {
          dragging.current = false;
          onCommit(Number(e.currentTarget.value));
        }
      }}
    />
  );
}
