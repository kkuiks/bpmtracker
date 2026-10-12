import type { MenuEntry } from "./ContextMenu";
export type ControlActions = {
  label: string; valid: () => boolean;
  restoreFocus?: () => void;
  edit?: () => void; copy?: () => Promise<void>; paste?: () => Promise<void>;
  reset?: () => void; resetLabel?: string;
};
const controls = new WeakMap<HTMLElement, () => ControlActions | null>();
export function registerControlContext(node: HTMLElement | null, capture: (() => ControlActions | null) | null) {
  if (!node) return;
  if (capture) controls.set(node, capture); else controls.delete(node);
}
export function controlMenuItems(actions: ControlActions): MenuEntry[] {
  const entries: MenuEntry[] = [];
  if (actions.edit) entries.push({ id: "edit-value", label: "Edit Value…", action: actions.edit });
  if (actions.copy) entries.push({ id: "copy", label: "Copy Exact Value", shortcut: "Ctrl C", action: actions.copy });
  if (actions.paste) entries.push({ id: "paste", label: "Paste Value", shortcut: "Ctrl V", action: actions.paste });
  if (actions.reset) {
    if (entries.length) entries.push({ separator: true });
    entries.push({ id: "reset-value", label: actions.resetLabel ?? "Reset", action: actions.reset });
  }
  return entries;
}
export function captureControlContext(target: Element) {
  const node = target.closest<HTMLElement>("[data-value-control],[data-slider-control]");
  return node ? controls.get(node)?.() ?? null : null;
}
