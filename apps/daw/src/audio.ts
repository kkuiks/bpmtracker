import { audioClips, type AudioClock, type Project, type DesktopApi } from "./model";
import { projectClocks } from "./music";
import type { ReferenceClicks } from "./samples";
import { DEFAULT_CLICK_GAIN } from "./click-level";

export class AudioEngine {
  private context?: AudioContext;
  private node?: AudioWorkletNode;
  private initializing?: Promise<void>;
  private project?: Project;
  private previewClocks?: AudioClock[];
  private referenceClicks?: ReferenceClicks;
  private loaded = new Map<string, number>();
  private loading = new Map<string, Promise<void>>();
  private revision = 0;
  private startingRevision: number | null = null;
  private prefetchTimer?: ReturnType<typeof setInterval>;
  private buffering = false;
  private disposed = false;
  position = 0;
  playing = false;
  playbackStart = 0;
  loop = { enabled: false, start: 0, end: 0 };
  click = false;
  clickGain = DEFAULT_CLICK_GAIN;
  onPosition: (time: number, playing: boolean, peaks: number[]) => void = () => {};
  onBuffering: (buffering: boolean) => void = () => {};
  onError: (message: string) => void = () => {};
  constructor(private api: DesktopApi) {}

  private async ensure() {
    if (!this.initializing) {
      this.initializing = (async () => {
        this.context = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });
        await this.context.audioWorklet.addModule(new URL("transport-worklet.js", document.baseURI).href);
        if (this.disposed) return;
        this.node = new AudioWorkletNode(this.context, "joljak-transport", {
          numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2],
        });
        this.node.port.onmessage = ({ data }) => {
          if (data.type === "need") {
            if (data.revision !== this.revision) return;
            const revision = this.revision;
            void this.loadChunk(data.assetId, data.index).catch((e) => { if (revision === this.revision) this.fail(e); });
            return;
          }
          // A renderer seek/stop invalidates replies from the previous sample-clock state.
          if (data.revision !== this.revision) return;
          if (["transport-ack", "position", "ended", "buffering"].includes(data.type)) {
            this.position = data.position;
            if (data.type === "transport-ack" && data.playing && this.startingRevision === data.revision) {
              this.playbackStart = data.position;
              this.startingRevision = null;
            }
            if (data.type === "ended") {
              this.playing = false;
              this.setBuffering(false);
              this.startingRevision = null;
            }
            this.notify(data.peaks ?? [0, 0]);
          }
          if (data.type === "buffering" && this.playing) void this.recoverBuffer(data.position, data.revision);
        };
        this.node.connect(this.context.destination);
        this.sendProject();
        // A cursor can have been moved before creating the worklet. Seed that position once.
        this.control({ position: this.position, playing: false });
        this.prefetchTimer = setInterval(() => {
          if (this.playing && !this.buffering) {
            const revision = this.revision;
            void this.prefetch(this.position).catch((e) => { if (revision === this.revision) this.fail(e); });
          }
        }, 500);
      })();
    }
    await this.initializing;
    if (this.disposed) return;
    if (this.context?.state !== "running") await this.context?.resume();
  }
  private notify(peaks = [0, 0]) { this.onPosition(this.position, this.playing, peaks); }
  private setBuffering(value: boolean) {
    this.buffering = value;
    this.onBuffering(value);
  }
  private fail(error: unknown) {
    if (this.disposed) return;
    this.pause();
    this.onError(error instanceof Error ? error.message : String(error));
  }
  private async loadChunk(assetId: string, index: number) {
    const key = `${assetId}:${index}`;
    if (this.loaded.has(key) && Date.now() - this.loaded.get(key)! < 8000) return;
    if (this.loading.has(key)) return this.loading.get(key);
    const loading = this.api.chunk(assetId, index).then((buffer) => {
      if (this.disposed) return;
      this.node?.port.postMessage({ type: "chunk", key, buffer }, [buffer]);
      this.loaded.set(key, Date.now());
    }).finally(() => this.loading.delete(key));
    this.loading.set(key, loading);
    return loading;
  }
  private async prefetch(position: number) {
    if (!this.project || !this.node) return;
    const windows = [[position, position + 6]];
    if (this.loop.enabled) windows.push([this.loop.start, this.loop.start + 4]);
    const requests = new Map<string, [string, number]>();
    for (const clip of audioClips(this.project)) for (const [start, end] of windows) {
      if (!clip.audible || clip.start >= end || clip.start + clip.duration <= start) continue;
      const first = Math.max(clip.sourceStart, start - clip.start + clip.sourceStart);
      const last = Math.min(clip.sourceStart + clip.duration, end - clip.start + clip.sourceStart);
      for (let i = Math.floor(first / 2); i <= Math.floor(last / 2); i++) requests.set(`${clip.assetId}:${i}`, [clip.assetId, i]);
    }
    await Promise.all([...requests.values()].map(([assetId, index]) => this.loadChunk(assetId, index)));
  }
  updateProject(project: Project, previewClocks?: AudioClock[], referenceClicks?: ReferenceClicks) {
    if (this.project && this.project.id !== project.id) this.reset();
    this.project = project;
    this.previewClocks = previewClocks;
    this.referenceClicks = referenceClicks;
    this.sendProject();
  }
  private sendProject() {
    if (this.project && this.node) this.node.port.postMessage({
      type: "project", clips: audioClips(this.project), clocks: this.previewClocks ?? projectClocks(this.project),
      referenceClicks: this.referenceClicks,
      masterGain: this.project.masterGain, end: this.project.projectDuration,
    });
  }
  private control(fields: { position?: number; playing?: boolean }, revision = this.revision) {
    this.node?.port.postMessage({ type: "transport", revision, ...fields,
      loop: this.loop, clickEnabled: this.click, clickGain: this.clickGain });
  }
  private async recoverBuffer(position: number, revision: number) {
    this.setBuffering(true);
    try {
      await this.prefetch(position);
      if (revision !== this.revision || !this.playing) return;
      this.setBuffering(false);
      this.control({ position, playing: true }, revision);
    } catch (e) { if (revision === this.revision) this.fail(e); }
  }

  async play(position?: number) {
    if (position === undefined && this.playing) return; // Cubase Start does not toggle pause.
    const target = Math.max(0, position ?? this.position);
    const revision = ++this.revision;
    this.startingRevision = revision;
    this.playing = true;
    this.position = target;
    this.playbackStart = target;
    this.setBuffering(true);
    this.notify();
    if (position !== undefined) this.control({ position: target, playing: false }, revision);
    try {
      await this.ensure();
      if (revision !== this.revision || !this.playing) return;
      await this.prefetch(target);
      if (revision !== this.revision || !this.playing) return;
      this.setBuffering(false);
      // Resume omits position: the worklet retains its exact stop sample, even if
      // the last renderer position notification was a few milliseconds earlier.
      this.control(position === undefined ? { playing: true } : { position: target, playing: true }, revision);
    } catch (e) { if (revision === this.revision) this.fail(e); }
  }
  private pause() {
    ++this.revision;
    this.startingRevision = null;
    this.playing = false;
    this.setBuffering(false);
    this.control({ playing: false });
    this.notify();
  }
  stop() {
    if (this.playing || this.buffering) this.pause();
    else void this.seek(this.playbackStart);
  }
  toggle() {
    if (this.playing || this.buffering) this.pause();
    else void this.play();
  }
  reset(position = 0) {
    ++this.revision;
    this.startingRevision = null;
    this.playing = false;
    this.position = Math.max(0, position);
    this.playbackStart = this.position;
    this.setBuffering(false);
    this.control({ position: this.position, playing: false });
    this.notify();
  }
  async seek(position: number) {
    const target = Math.max(0, position), continuePlaying = this.playing;
    const revision = ++this.revision;
    this.startingRevision = null;
    this.position = target;
    this.setBuffering(continuePlaying);
    this.control({ position: target, playing: false }, revision);
    this.notify();
    if (!continuePlaying) return;
    try {
      await this.ensure();
      if (revision !== this.revision || !this.playing) return;
      await this.prefetch(target);
      if (revision !== this.revision || !this.playing) return;
      this.setBuffering(false);
      this.control({ position: target, playing: true }, revision);
    } catch (e) { if (revision === this.revision) this.fail(e); }
  }
  setLoop(loop: typeof this.loop) { this.loop = loop; this.node?.port.postMessage({ type: "transport", loop }); }
  setClick(enabled: boolean, gain = this.clickGain) {
    this.click = enabled; this.clickGain = gain;
    this.node?.port.postMessage({ type: "transport", clickEnabled: enabled, clickGain: gain });
  }
  dispose() {
    this.disposed = true;
    this.pause();
    if (this.prefetchTimer) clearInterval(this.prefetchTimer);
    void this.context?.close();
  }
}
