import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, ChevronRight } from "lucide-react";
import type { ArrangementSelection, MapSelection, TimeRange } from "./model";

export type MenuEntry = {
  label?: string; id?: string; shortcut?: string; action?: () => void | Promise<void>;
  disabled?: string; checked?: boolean; separator?: boolean; danger?: boolean;
  submenu?: MenuEntry[];
};
export type MenuPopup = {
  x: number; y: number; items: MenuEntry[]; title?: string;
  invoker?: HTMLElement | null; appMenu?: string;
  restoreFocus?: () => void;
  navigate?: (direction: -1 | 1) => void;
};
export type ArrangementContext = {
  domain: "audio" | "range" | "lane" | "ruler" | "map" | "map-lane" | "editor";
  x: number; y: number; time: number; trackId?: string; clipId?: string;
  selection?: ArrangementSelection; range?: TimeRange | null;
  map?: MapSelection; mapKind?: "tempo" | "signature"; invoker?: HTMLElement | null;
};
export function menuCommand(entries: MenuEntry[], id: string): MenuEntry | undefined {
  for (const entry of entries) {
    if (entry.id === id) return entry;
    const child = entry.submenu && menuCommand(entry.submenu, id);
    if (child) return child;
  }
}
export function editableText(node: EventTarget | null) {
  const element = node instanceof Element ? node.closest("input,textarea,[contenteditable=true]") : null;
  return element instanceof HTMLTextAreaElement || element instanceof HTMLElement && element.isContentEditable ||
    element instanceof HTMLInputElement && !element.readOnly && element.type !== "range";
}

/** One owner for application and contextual menus, including focus and placement. */
export default function ContextMenu({ menu, onClose }: { menu: MenuPopup; onClose: () => void }) {
  const root = useRef<HTMLDivElement>(null), child = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: menu.x, top: menu.y });
  const [submenu, setSubmenu] = useState<number | null>(null);
  const [childPosition, setChildPosition] = useState({ left: 0, top: 0 });
  const [reason, setReason] = useState<string | null>(null);
  const search = useRef({ text: "", time: 0 });
  const latestClose = useRef(onClose); latestClose.current = onClose;
  const rows = (node = root.current) => node ? [...node.querySelectorAll<HTMLButtonElement>(":scope > button")] : [];
  const close = (restore = false) => {
    latestClose.current();
    if (restore && menu.restoreFocus) menu.restoreFocus();
    else if (restore && menu.invoker?.isConnected) menu.invoker.focus({ preventScroll: true });
  };
  const execute = (item: MenuEntry) => {
    if (item.disabled) { setReason(item.disabled); return; }
    close(true); item.action?.();
  };
  useLayoutEffect(() => {
    const node = root.current!;
    setSubmenu(null); setReason(null); search.current = { text: "", time: 0 };
    const place = () => {
      const width = node.offsetWidth, height = node.offsetHeight;
      setPosition({ left: Math.max(8, Math.min(menu.x, innerWidth - width - 8)),
        top: Math.max(8, Math.min(menu.y, innerHeight - height - 8)) });
    };
    place(); node.focus({ preventScroll: true });
    const observer = new ResizeObserver(place); observer.observe(node);
    return () => observer.disconnect();
  }, [menu]);
  useLayoutEffect(() => {
    if (submenu === null || !child.current) return;
    const row = root.current!.querySelector<HTMLElement>(`[data-menu-index="${submenu}"]`)!.getBoundingClientRect();
    const node = child.current;
    const place = () => setChildPosition({
      left: Math.max(8, row.right + node.offsetWidth + 8 <= innerWidth ? row.right + 3 : row.left - node.offsetWidth - 3),
      top: Math.max(8, Math.min(row.top - 5, innerHeight - node.offsetHeight - 8)),
    });
    place(); const observer = new ResizeObserver(place); observer.observe(node);
    return () => observer.disconnect();
  }, [submenu]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if ((event.target as Element)?.closest("[data-owned-menu]")) return;
      close();
      if (event.button === 0) { event.preventDefault(); event.stopPropagation(); }
    };
    const dismiss = () => close();
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("blur", dismiss); window.addEventListener("resize", dismiss);
    return () => { document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("blur", dismiss); window.removeEventListener("resize", dismiss); };
  }, [menu]);
  const keyboard = (event: React.KeyboardEvent<HTMLDivElement>, nested = false) => {
    const buttons = rows(nested ? child.current : root.current), index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const focus = (next: number) => { buttons[next]?.focus({ preventScroll: true }); buttons[next]?.scrollIntoView({ block: "nearest" }); };
    if (event.key === "Tab") { close(true); return; }
    event.stopPropagation();
    if (event.ctrlKey || event.metaKey || event.altKey || event.key === "Delete" || event.code.startsWith("Numpad")) {
      const key = event.code.startsWith("Numpad") ? `Num ${event.code === "NumpadDivide" ? "/" : event.code === "NumpadDecimal" ? "." : event.code.slice(6)}` :
        [event.ctrlKey || event.metaKey ? "Ctrl" : "", event.altKey ? "Alt" : "", event.shiftKey ? "Shift" : "", event.key.length === 1 ? event.key.toUpperCase() : event.key === "Delete" ? "Del" : event.key].filter(Boolean).join(" ");
      const find = (entries: MenuEntry[]): MenuEntry | undefined => entries.find(entry => entry.shortcut?.toLowerCase() === key.toLowerCase()) ?? entries.flatMap(entry => entry.submenu ? [find(entry.submenu)] : []).find(Boolean);
      const item = find(menu.items); if (item) { event.preventDefault(); execute(item); return; }
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 :
        index < 0 ? event.key === "ArrowDown" ? 0 : buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      focus(next); return;
    }
    if (event.key === "Escape" || event.key === "ArrowLeft" && nested) {
      event.preventDefault();
      if (submenu !== null) { const owner = submenu; setSubmenu(null); rows().find(node => Number(node.dataset.menuIndex) === owner)?.focus({ preventScroll: true }); }
      else close(true);
      return;
    }
    if (event.key === "ArrowLeft" && !nested && menu.navigate) { event.preventDefault(); menu.navigate(-1); return; }
    if (event.key === "ArrowRight" && !nested && index >= 0) {
      event.preventDefault(); const item = Number(buttons[index].dataset.menuIndex);
      if (menu.items[item].submenu && !menu.items[item].disabled) { setSubmenu(item); requestAnimationFrame(() => rows(child.current)[0]?.focus({ preventScroll: true })); }
      else if (menu.navigate) menu.navigate(1);
      return;
    }
    if (event.key === "ArrowRight" && !nested && menu.navigate) { event.preventDefault(); menu.navigate(1); return; }
    if (event.key === " " || event.key === "Enter") { event.preventDefault(); buttons[index]?.click(); return; }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault(); const now = performance.now();
      const text = (now - search.current.time < 650 ? search.current.text : "") + event.key.toLowerCase();
      search.current = { text, time: now };
      const target = buttons.findIndex(button => button.textContent?.trim().toLowerCase().startsWith(text));
      if (target >= 0) focus(target);
    }
  };
  const items = (entries: MenuEntry[], nested = false) => entries.map((entry, index) => entry.separator ?
    <div role="separator" className="menu-separator" key={`separator-${index}`}/> :
    <button key={`${entry.id ?? entry.label}-${index}`} type="button" data-menu-index={index}
      role={entry.checked !== undefined ? "menuitemcheckbox" : "menuitem"}
      aria-disabled={!!entry.disabled} aria-checked={entry.checked} aria-haspopup={entry.submenu ? "menu" : undefined}
      aria-expanded={entry.submenu ? submenu === index : undefined} className={entry.danger ? "danger" : ""} tabIndex={-1}
      title={entry.disabled}
      onPointerEnter={() => { setReason(entry.disabled ?? null); if (!nested) setSubmenu(entry.submenu && !entry.disabled ? index : null); }}
      onFocus={() => setReason(entry.disabled ?? null)}
      onClick={() => entry.disabled ? setReason(entry.disabled) : entry.submenu ? setSubmenu(submenu === index ? null : index) : execute(entry)}>
      <span className="menu-check">{entry.checked && <Check size={13}/>}</span><span className="menu-label">{entry.label}</span>
      {entry.submenu ? <ChevronRight size={14}/> : <kbd>{entry.shortcut}</kbd>}
    </button>);
  return <>
    <div ref={root} data-owned-menu role="menu" aria-label={menu.title ?? "Application menu"} tabIndex={-1}
      className={`context-menu owned-menu ${menu.appMenu ? "app-dropdown" : ""}`} style={position}
      onContextMenu={event => event.preventDefault()} onKeyDown={event => keyboard(event)}>
      {menu.title && <div className="menu-caption">{menu.title}</div>}{items(menu.items)}
      {reason && <div className="menu-reason">{reason}</div>}
    </div>
    {submenu !== null && <div ref={child} data-owned-menu role="menu" aria-label={menu.items[submenu].label} tabIndex={-1}
      className="context-menu owned-menu submenu" style={childPosition} onKeyDown={event => keyboard(event, true)}>
      {items(menu.items[submenu].submenu ?? [], true)}
    </div>}
  </>;
}
