import type { Project, Asset, Analysis } from "./model";

export class ProjectHistory {
  private past: { label: string; project: Project }[] = [];
  private future: { label: string; project: Project }[] = [];
  private assets = new Map<string, Asset>();
  private analyses = new Map<string, Analysis>();
  constructor(public current: Project) {
    this.remember(current);
  }
  private remember(project: Project) {
    for (const asset of project.assets) this.assets.set(asset.id, asset);
    for (const analysis of project.analyses)
      this.analyses.set(analysis.id, analysis);
  }
  private preserved(project: Project): Project {
    return {
      ...project,
      assets: [...this.assets.values()],
      analyses: [...this.analyses.values()],
    };
  }
  commit(next: Project, label: string): Project {
    if (next === this.current) return this.current;
    this.past.push({ label, project: this.current });
    if (this.past.length > 100) this.past.shift();
    this.future = [];
    this.remember(next);
    this.current = this.preserved(next);
    return this.current;
  }
  replace(next: Project): void {
    this.assets.clear();
    this.analyses.clear();
    this.remember(next);
    this.current = next;
    this.past = [];
    this.future = [];
  }
  saved(next: Project): void {
    this.remember(next);
    this.current = this.preserved(next);
  }
  restoreAssets(items: Asset[]): Project {
    const restored = new Map<string, Asset>();
    for (const asset of items) {
      const existing = this.assets.get(asset.id);
      if (!existing) continue;
      if (asset.sampleRate !== existing.sampleRate || asset.channels !== existing.channels || asset.frames !== existing.frames)
        throw new Error("Restored audio differs from the saved original");
      const updated = { ...existing, ...asset };
      restored.set(asset.id, updated);
      this.assets.set(asset.id, updated);
    }
    const refresh = (project: Project): Project => ({
      ...project, assets: project.assets.map(asset => restored.get(asset.id) ?? asset),
    });
    this.past = this.past.map(item => ({ ...item, project: refresh(item.project) }));
    this.future = this.future.map(item => ({ ...item, project: refresh(item.project) }));
    this.current = this.preserved(refresh(this.current));
    return this.current;
  }
  record(analysis: Analysis): Project {
    this.analyses.set(analysis.id, analysis);
    this.current = this.preserved(this.current);
    return this.current;
  }
  undo(): Project {
    const item = this.past.pop();
    if (item) {
      this.future.push({ label: item.label, project: this.current });
      this.current = item.project;
    }
    this.current = this.preserved(this.current);
    return this.current;
  }
  redo(): Project {
    const item = this.future.pop();
    if (item) {
      this.past.push({ label: item.label, project: this.current });
      this.current = item.project;
    }
    this.current = this.preserved(this.current);
    return this.current;
  }
  get undoLabel() {
    return this.past.at(-1)?.label;
  }
  get redoLabel() {
    return this.future.at(-1)?.label;
  }
}
