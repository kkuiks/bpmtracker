import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { TimeSignature } from "./model";
import { parseTimeSignature } from "./music";

export type SignatureEdit = { key: string; projectId: string; time: number; id?: string; value: TimeSignature };

export default function SignatureEditor({ edit, left, onCommit, onCancel }: {
  edit: SignatureEdit; left: number;
  onCommit: (value: TimeSignature, returnFocus: boolean) => string | null;
  onCancel: (returnFocus: boolean) => void;
}) {
  const field = useRef<HTMLInputElement>(null), settled = useRef(false);
  const [text, setText] = useState(`${edit.value.numerator}/${edit.value.denominator}`);
  const [error, setError] = useState("");
  useLayoutEffect(() => { field.current?.focus({ preventScroll: true }); field.current?.select(); }, []);
  const cancel = (returnFocus: boolean) => {
    if (settled.current) return;
    settled.current = true; onCancel(returnFocus);
  };
  const accept = (returnFocus: boolean) => {
    if (settled.current) return;
    const value = parseTimeSignature(text);
    if (!value) { setError("Enter a signature such as 3/4 or 6/8. Numerator: 1–32; denominator: 1, 2, 4, 8, 16 or 32."); return; }
    settled.current = true;
    const failure = onCommit(value, returnFocus);
    if (failure) { settled.current = false; setError(failure); }
  };
  const box = field.current?.getBoundingClientRect();
  return <>
    <span className="signature-inline-editor" style={{ left }} onPointerDown={event => event.stopPropagation()}
      onDoubleClick={event => event.stopPropagation()}>
      <input ref={field} aria-label="Time signature" aria-invalid={!!error} aria-describedby={error ? "signature-edit-error" : undefined}
        value={text} spellCheck={false} autoComplete="off" title="Type 3/4 or 6/8 · Enter: apply · Escape: cancel"
        onChange={event => { setText(event.target.value); setError(""); }}
        onBlur={() => { if (parseTimeSignature(text)) accept(false); else cancel(false); }}
        onKeyDown={event => {
          if (["Enter", "Tab", "Escape"].includes(event.key)) {
            event.preventDefault(); event.stopPropagation();
            if (event.key === "Escape") cancel(true); else accept(true);
          }
        }}/>
    </span>
    {error && box && createPortal(<div id="signature-edit-error" role="alert" className="signature-edit-error"
      style={{ left: Math.min(box.left, window.innerWidth - 300), top: box.bottom + 5 }}>{error}</div>, document.body)}
  </>;
}
