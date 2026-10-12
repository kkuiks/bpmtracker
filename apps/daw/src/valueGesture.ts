// Native menu accelerators cancel an unfinished control/arrangement gesture before project Undo.
const gestures = new WeakMap<HTMLElement, () => void>();
const active = new Set<HTMLElement>();
export function registerValueGesture(node: HTMLElement | null, cancel: (() => void) | null) {
  if (!node) return;
  if (cancel) { gestures.set(node, cancel); active.add(node); }
  else { gestures.delete(node); active.delete(node); }
}
export function cancelMenuGestures() {
  for (const node of [...active]) {
    if (!node.isConnected) { active.delete(node); gestures.delete(node); continue; }
    if (node.closest<HTMLElement>("[data-value-control]")?.dataset.state === "typing") continue;
    cancelValueGesture(node);
  }
}
export function cancelValueGesture(node: HTMLElement | null): boolean {
  const cancel = node && gestures.get(node);
  if (!cancel) return false;
  cancel();
  return true;
}
