import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export default function ResizablePane({ axis, initialSize, minSize, maxSize, storageKey, label, className, children, resetKey = 0 }: {
  axis: "x" | "y"; initialSize: number; minSize: number; maxSize: number;
  storageKey: string; label: string; className: string;
  children: ReactNode | ((size: number) => ReactNode);
  resetKey?: number;
}) {
  const clamp = (value: number) => Math.max(minSize, Math.min(maxSize, value));
  const [size, setSize] = useState(() => {
    try { const stored = localStorage.getItem(storageKey); return stored === null ? initialSize : clamp(Number(stored) || initialSize); }
    catch { return initialSize; }
  });
  const [actualSize, setActualSize] = useState(size);
  const node = useRef<HTMLDivElement>(null);
  const latestSize = useRef(size); latestSize.current = size;
  const previousReset = useRef(resetKey);
  const gesture = useRef<{ point: number; size: number; original: number } | null>(null);
  const resize = (value: number) => { const next = clamp(value); latestSize.current = next; setSize(next); };
  const remember = () => { try { localStorage.setItem(storageKey, String(latestSize.current)); } catch { /* Layout still works without storage. */ } };
  const finish = (cancel = false) => {
    const drag = gesture.current;
    if (!drag) return;
    gesture.current = null;
    if (cancel) resize(drag.original); else remember();
  };
  useLayoutEffect(() => {
    if (previousReset.current === resetKey) return;
    previousReset.current = resetKey;
    gesture.current = null;
    resize(initialSize);
  }, [resetKey, initialSize]);
  useLayoutEffect(() => {
    const element = node.current!;
    const observer = new ResizeObserver(() => setActualSize(axis === "x" ? element.clientWidth : element.clientHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, [axis]);
  return <div ref={node} className={`resizable-pane pane-${axis} ${className}`} style={axis === "x" ? { width: size } : { height: size }}>
    {typeof children === "function" ? children(actualSize) : children}
    <div className="pane-resize-handle" role="separator" tabIndex={0} aria-label={label}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"} aria-valuemin={minSize} aria-valuemax={maxSize} aria-valuenow={actualSize}
      title={`${label} · drag to resize`}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault(); event.stopPropagation(); event.currentTarget.focus({ preventScroll: true });
        event.currentTarget.setPointerCapture(event.pointerId);
        gesture.current = { point: axis === "x" ? event.clientX : event.clientY, size: actualSize, original: size };
      }}
      onPointerMove={(event) => {
        const drag = gesture.current; if (!drag) return;
        const point = axis === "x" ? event.clientX : event.clientY;
        resize(drag.size + (point - drag.point) * (axis === "x" ? 1 : -1));
      }}
      onPointerUp={() => finish()} onPointerCancel={() => finish(true)} onLostPointerCapture={() => finish()}
      onKeyDown={(event) => {
        if (event.key === "Escape" && gesture.current) { event.preventDefault(); event.stopPropagation(); finish(true); return; }
        const decrease = axis === "x" ? "ArrowLeft" : "ArrowDown", increase = axis === "x" ? "ArrowRight" : "ArrowUp";
        if (event.key !== decrease && event.key !== increase) return;
        event.preventDefault(); event.stopPropagation();
        resize(actualSize + (event.key === increase ? 1 : -1) * (event.shiftKey ? 2 : 10)); remember();
      }}/>
  </div>;
}
