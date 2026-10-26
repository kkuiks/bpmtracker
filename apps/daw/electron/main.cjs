const {
  app,
  BrowserWindow,
  Menu,
  dialog,
  ipcMain,
  shell,
  protocol,
  net,
} = require("electron");
const { pathToFileURL } = require("node:url");
const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { randomUUID } = require("node:crypto");
const readline = require("node:readline");
const fsSync = require("node:fs");
const sampleLibrary = require("./sample-library.cjs");
const audioCache = require("./audio-cache.cjs");

let window;
app.setName("BPMTracker");
if (process.env.BPMTRACKER_DATA) {
  // Custom workspaces, including explicit UX audits, also isolate browser preferences/cache.
  app.setPath("userData", path.join(path.resolve(process.env.BPMTRACKER_DATA), "electron-profile"));
}
const projectArgument = (args, cwd) => {
  for (const value of args) {
    if (typeof value !== "string" || value.startsWith("--")) continue;
    const filename = path.resolve(cwd, value);
    if (/\.bpmtracker$/i.test(filename)) return filename;
    try {
      const project = JSON.parse(fsSync.readFileSync(filename, "utf8"));
      if (typeof project?.format === "string" && project.format.endsWith("-project") &&
          [1, 2, 3].includes(project.version)) return filename;
    } catch { /* Ignore non-project startup arguments. */ }
  }
  return null;
};
const initialProject = projectArgument(process.argv.slice(1), process.cwd());
if (!app.requestSingleInstanceLock({ project: initialProject })) { app.quit(); return; }
let rendererReady = false;
const pendingProjects = initialProject ? [initialProject] : [];
app.on("second-instance", (_event, args, cwd, extra) => {
  const file = typeof extra?.project === "string" ? extra.project : projectArgument(args, cwd);
  if (window && !window.isDestroyed()) {
    if (window.isMinimized()) window.restore();
    window.focus();
  }
  if (file) {
    pendingProjects.push(file);
    if (rendererReady) send("open-project", null);
  }
});
protocol.registerSchemesAsPrivileged([
  {
    scheme: "bpmtracker",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);
const jobs = new Map(),
  assets = new Map();
// Only newly requested UI imports are disposable until the arrangement adopts
// them. Existing project media/cache restoration never enters this registry.
const imports = new Map();
const registeredAssets = new Map(), restoringCaches = new Map();
const openingCacheIds = new Set();
let quitting = false, cacheCleanupTimer;
let cacheCleanup = Promise.resolve();
const appRoot = path.resolve(__dirname, "..");
const repository = path.resolve(appRoot, "../..");
const packagedAnalysis = path.join(process.resourcesPath, "analysis");
const bundled = fsSync.existsSync(path.join(packagedAnalysis, "final0.ckpt"));
const analysisRoot = bundled ? packagedAnalysis : repository;
const worker = path.join(appRoot, "backend", "worker.py");
const dataRoot =
  process.env.BPMTRACKER_DATA || path.join(app.getPath("userData"), "workspace");
const python =
  process.env.BPMTRACKER_PYTHON ||
  (bundled
    ? path.join(process.resourcesPath, "python", "python.exe")
    : process.platform === "win32"
      ? path.join(repository, ".venv-daw-win", "Scripts", "python.exe")
      : path.join(repository, ".venv-metronome-v1", "bin", "python"));
const checkpoint = bundled
  ? path.join(packagedAnalysis, "final0.ckpt")
  : path.join(
      repository,
      "data",
      "models",
      "final0.ckpt",
    );
const send = (name, data) => {
  if (window && !window.isDestroyed())
    window.webContents.send(`bpmtracker:${name}`, data);
};
let sampleRoot = process.env.BPMTRACKER_SAMPLE_ROOT || null;
async function sampleLibraryRoot(choose = false) {
  if (choose) {
    const result = await dialog.showOpenDialog(window, {
      title: "Select the formal sample catalog", properties: ["openFile"],
      filters: [{ name: "Sample catalog", extensions: ["json"] }],
    });
    if (result.canceled) return null;
    const root = path.dirname(result.filePaths[0]);
    if (path.basename(result.filePaths[0]) !== "catalog.json") throw new Error("Select data/samples/catalog.json");
    await sampleLibrary.catalog(root);
    sampleRoot = root;
    await atomicJson(path.join(dataRoot, "sample-library.json"), { root });
  }
  if (!sampleRoot) {
    try { sampleRoot = JSON.parse(await fs.readFile(path.join(dataRoot, "sample-library.json"), "utf8")).root; }
    catch { /* First library selection. */ }
  }
  if (!sampleRoot && fsSync.existsSync(path.join(repository, "data/samples/catalog.json")))
    sampleRoot = path.join(repository, "data/samples");
  if (!sampleRoot) return null;
  await sampleLibrary.catalog(sampleRoot);
  return sampleRoot;
}

function validProject(value) {
  if (
    !value ||
    typeof value.format !== "string" || !value.format.endsWith("-project") ||
    ![1, 2, 3].includes(value.version) ||
    !Array.isArray(value.assets) ||
    !Array.isArray(value.clips) ||
    !Array.isArray(value.tracks) ||
    !Array.isArray(value.clocks) ||
    !Array.isArray(value.analyses)
  )
    throw new Error("This is not a supported BPMTracker project");
  if (
    typeof value.id !== "string" || typeof value.name !== "string" ||
    value.sampleRate !== 48000 ||
    !Number.isFinite(value.masterGain) || value.masterGain < 0 ||
    (value.clickGain !== undefined && (!Number.isFinite(value.clickGain) || value.clickGain < 0))
  ) throw new Error("Invalid project or master settings");
  const assetIds = new Set(), trackIds = new Set(), clipIds = new Set();
  for (const asset of value.assets) {
    if (assetIds.has(asset.id) || typeof asset.name !== "string" || typeof asset.sourcePath !== "string" ||
        !Number.isFinite(asset.duration) || asset.duration <= 0 ||
        Math.abs(asset.duration - asset.frames / asset.sampleRate) > 1e-6)
      throw new Error("Invalid or duplicate audio asset in project");
    assetIds.add(asset.id);
  }
  for (const track of value.tracks) {
    if (typeof track.id !== "string" || typeof track.name !== "string" || trackIds.has(track.id))
      throw new Error("Invalid or duplicate track in project");
    trackIds.add(track.id);
  }
  for (const clip of value.clips)
    if (
      ![clip.start, clip.sourceStart, clip.duration].every(Number.isFinite) ||
      clip.start < 0 ||
      clip.sourceStart < 0 ||
      clip.duration <= 0
    )
      throw new Error("Invalid clip geometry in project");
  for (const clip of value.clips) {
    const asset = value.assets.find((asset) => asset.id === clip.assetId);
    if (typeof clip.id !== "string" || clipIds.has(clip.id) || !asset || !trackIds.has(clip.trackId) ||
        clip.sourceStart + clip.duration > asset.duration + 1e-6)
      throw new Error("Invalid audio/track reference or source bounds in project");
    clipIds.add(clip.id);
  }
  for (const asset of value.assets)
    if (
      !/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(asset.id) ||
      ![asset.sampleRate, asset.channels, asset.frames].every(
        Number.isFinite,
      ) ||
      asset.frames <= 0 ||
      asset.sampleRate <= 0 ||
      ![1, 2].includes(asset.channels)
    )
      throw new Error("Invalid audio asset in project");
  for (const track of value.tracks)
    if (
      !Number.isFinite(track.gain) ||
      track.gain < 0 ||
      !Number.isFinite(track.pan) ||
      Math.abs(track.pan) > 1
    )
      throw new Error("Invalid channel settings in project");
  if (value.version >= 2) {
    const hasWholeValues = value.bpm !== undefined || value.signature !== undefined;
    if (hasWholeValues && (!Number.isFinite(value.bpm) || value.bpm < 1 || value.bpm > 1000 ||
        !value.signature || !Number.isInteger(value.signature.numerator) ||
        value.signature.numerator < 1 || value.signature.numerator > 32 ||
        ![1, 2, 4, 8, 16, 32].includes(value.signature.denominator)))
      throw new Error("Invalid whole-project tempo or signature");
    if (!Number.isFinite(value.projectDuration) || value.projectDuration <= 0 ||
        (value.timingPolicy !== undefined && value.timingPolicy !== "persistent") ||
        !["bars", "seconds"].includes(value.rulerFormat) ||
        !Array.isArray(value.tempos) || !Array.isArray(value.signatures) ||
        (!hasWholeValues && (!value.tempos.some((tempo) => tempo.quarter === 0) ||
                            !value.signatures.some((signature) => signature.bar === 1))))
      throw new Error("Invalid project duration or musical map");
    const positions = new Set(), bars = new Set(), mapIds = new Set();
    for (const event of [...value.tempos, ...value.signatures]) {
      if (typeof event.id !== "string" || mapIds.has(event.id) ||
          !["default", "manual", "analysis"].includes(event.origin))
        throw new Error("Invalid or duplicate project map event");
      mapIds.add(event.id);
    }
    for (const tempo of value.tempos) {
      if (!Number.isFinite(tempo.quarter) || tempo.quarter < 0 || positions.has(tempo.quarter) ||
          !Number.isFinite(tempo.bpm) || tempo.bpm < 1 || tempo.bpm > 1000)
        throw new Error("Invalid tempo event in project");
      positions.add(tempo.quarter);
    }
    for (const signature of value.signatures) {
      const position = value.version >= 3 ? signature.quarter : signature.bar;
      if ((value.version >= 3 ? !Number.isFinite(position) || position < 0 : !Number.isInteger(position) || position < 1) || bars.has(position) ||
          !Number.isInteger(signature.bar) || signature.bar < 1 ||
          !Number.isInteger(signature.numerator) || signature.numerator < 1 || signature.numerator > 32 ||
          ![1, 2, 4, 8, 16, 32].includes(signature.denominator))
        throw new Error("Invalid signature event in project");
      bars.add(position);
    }
    for (const track of value.tracks)
      if (!["linear", "musical"].includes(track.timeBase))
        throw new Error("Invalid track time base in project");
    for (const clip of value.clips)
      if (clip.musicalStart !== undefined && (!Number.isFinite(clip.musicalStart) || clip.musicalStart < 0))
        throw new Error("Invalid musical event position in project");
  }
  for (const clock of value.clocks)
    if (
      ![
        clock.sourceStart,
        clock.sourceEnd,
        clock.values.bpm,
        clock.values.offset,
      ].every(Number.isFinite) ||
      clock.sourceEnd <= clock.sourceStart ||
      clock.values.bpm <= 0 ||
      !Number.isInteger(clock.values.numerator) ||
      clock.values.numerator < 1 ||
      clock.values.numerator > 32 ||
      ![1, 2, 4, 8, 16, 32].includes(clock.values.denominator)
    )
      throw new Error("Invalid fixed clock in project");
  value.format = "bpmtracker-project";
  return value;
}
async function atomicJson(filename, value) {
  await fs.mkdir(path.dirname(filename), { recursive: true });
  const temporary = `${filename}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporary, JSON.stringify(value, null, 2));
    await fs.rename(temporary, filename);
  } finally {
    await fs.rm(temporary, { force: true });
  }
}
function requireAsset(id) {
  const asset = assets.get(id);
  if (!asset) throw new Error("Audio is not registered in this project");
  return asset;
}
const audioCacheRoot = path.join(dataRoot, "audio-cache");
const cacheFolderFor = (asset) => audioCache.cacheFolder(audioCacheRoot, asset);
function queueCacheCleanup(all = false) {
  cacheCleanup = cacheCleanup.catch(error => console.warn(error.message)).then(() =>
    audioCache.pruneAudioCache(audioCacheRoot,
      id => !all && (openingCacheIds.has(id) ||
        [...registeredAssets.values()].some(asset => audioCache.cacheId(asset) === id)),
      () => (all || !quitting) && !jobs.size && !imports.size && !restoringCaches.size));
  return cacheCleanup;
}
function scheduleCacheCleanup() {
  if (quitting) return;
  clearTimeout(cacheCleanupTimer);
  cacheCleanupTimer = setTimeout(() => {
    void queueCacheCleanup().catch(error => console.warn("Audio cache cleanup:", error.message));
  }, 250);
}
function ensureAssetCache(asset) {
  if (quitting) return Promise.resolve(null);
  const key = audioCache.cacheId(asset);
  if (restoringCaches.has(key)) return restoringCaches.get(key);
  const task = (async () => {
    const folder = cacheFolderFor(asset);
    playbackCachePaths(asset, folder);
    try { await restoreCachedAsset(asset, folder); return null; }
    catch { /* Rebuild only decoded buffers, never map or original geometry. */ }
    const id = await startJob("decode", {
      files: [{ id: asset.id, cacheId: key, path: asset.sourcePath, name: asset.name, expected: asset }],
      output: audioCacheRoot, restore: true,
    });
    const release = () => {
      if (restoringCaches.get(key) === task) restoringCaches.delete(key);
      scheduleCacheCleanup();
    };
    const child = jobs.get(id);
    if (child && child.exitCode === null && child.signalCode === null) {
      child.once("close", release);
      child.once("error", release);
    } else release();
    return id;
  })();
  restoringCaches.set(key, task);
  const release = () => { if (restoringCaches.get(key) === task) restoringCaches.delete(key); };
  void task.then(id => { if (!id) release(); }, release);
  return task;
}
function playbackCachePaths(asset, cacheFolder) {
  // Decoder playback PCM is always 48 kHz. Saved projects can contain only the
  // original geometry, so do not carry its rate into a restored playback buffer.
  asset.pcmPath = path.join(cacheFolder, "audio.f32");
  asset.peaksPath = path.join(cacheFolder, "peaks.f32");
  asset.playbackPath = asset.sampleRate === 48000
    ? asset.pcmPath : path.join(cacheFolder, "playback.f32");
  asset.playbackRate = 48000;
  asset.playbackFrames = Math.round(asset.frames * 48000 / asset.sampleRate);
}
async function restoreCachedAsset(asset, cacheFolder) {
  const cached = JSON.parse(await fs.readFile(path.join(cacheFolder, "asset.json"), "utf8"));
  if (audioCache.cacheId(cached) !== audioCache.cacheId(asset) || cached.sampleRate !== asset.sampleRate ||
      cached.channels !== asset.channels || cached.frames !== asset.frames)
    throw new Error("Cached audio geometry differs from the saved original");
  const playbackRate = cached.playbackRate ?? (asset.sampleRate === 48000 ? 48000 : null);
  const playbackFrames = cached.playbackFrames ?? (asset.sampleRate === 48000 ? asset.frames : null);
  if (playbackRate !== 48000 || !Number.isSafeInteger(playbackFrames) || playbackFrames <= 0 ||
      Math.abs(playbackFrames / playbackRate - asset.duration) > 1 / playbackRate + 1e-8 ||
      !Number.isSafeInteger(cached.peakBinFrames) || cached.peakBinFrames <= 0 ||
      cached.peakBins !== Math.ceil(asset.frames / cached.peakBinFrames))
    throw new Error("Cached playback metadata is incomplete or inconsistent");
  const [pcm, playback, peaks] = await Promise.all([
    fs.stat(asset.pcmPath), fs.stat(asset.playbackPath), fs.stat(asset.peaksPath),
  ]);
  if (pcm.size !== asset.frames * asset.channels * 4 ||
      playback.size !== playbackFrames * asset.channels * 4 ||
      peaks.size !== cached.peakBins * 2 * 4)
    throw new Error("Cached audio data is incomplete");
  // Only local decoded-buffer metadata is restored. Preserve the saved original
  // rate/frames, source path, clip placement and every project-map declaration.
  Object.assign(asset, { playbackRate, playbackFrames,
    peakBinFrames: cached.peakBinFrames, peakBins: cached.peakBins });
}
async function finishImport(id, keep = false) {
  const record = imports.get(id);
  if (!record) return;
  if (keep) {
    if (!record.complete || record.discard) throw new Error("This import is no longer available.");
    for (const assetId of record.assetIds) {
      const asset = assets.get(assetId);
      if (asset) registeredAssets.set(assetId, asset);
    }
    imports.delete(id);
    await fs.rm(path.join(dataRoot, "jobs", `${id}.json`), { force: true });
    scheduleCacheCleanup();
    return;
  }
  record.discard = true;
  if (record.preparing) return;
  const child = jobs.get(id);
  if (child) { child.kill(); return; } // Cleanup follows worker close, after file handles release.
  if (record.cleaning) return record.cleaning;
  record.cleaning = (async () => {
    for (const assetId of record.assetIds) assets.delete(assetId);
    await Promise.all(record.directories.map((directory) => fs.rm(directory, { recursive: true, force: true })));
    await fs.rm(path.join(dataRoot, "jobs", `${id}.json`), { force: true });
    imports.delete(id);
    scheduleCacheCleanup();
  })();
  return record.cleaning;
}
function preserveProjectImports(project) {
  const ids = new Set(project.assets.map((asset) => asset.id));
  for (const [id, record] of imports) {
    if (record.complete && record.assetIds.every((assetId) => ids.has(assetId))) {
      // A saved/recovery project already owns these files, including assets kept
      // for undo. Closing must not treat them as an abandoned import.
      imports.delete(id);
      void fs.rm(path.join(dataRoot, "jobs", `${id}.json`), { force: true }).catch(() => {});
    }
  }
}
async function startJob(kind, body) {
  await fs.access(python).catch(() => {
    throw new Error(
      "Python audio runtime is missing. Use the packaged Windows app, or set BPMTRACKER_PYTHON to the current model environment.",
    );
  });
  const id = body.id || randomUUID();
  const jobPath = path.join(dataRoot, "jobs", `${id}.json`);
  const job = { ...body, id, kind };
  await atomicJson(jobPath, job);
  if (quitting) throw new Error("BPMTracker is closing");
  const child = spawn(python, ["-u", worker, jobPath], {
    cwd: analysisRoot,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
      // Bind native math libraries before Python imports them. A large default
      // OpenBLAS thread pool can exhaust Windows commit even on a short input.
      OPENBLAS_NUM_THREADS: "4",
      OMP_NUM_THREADS: "4",
      MKL_NUM_THREADS: "4",
      NUMEXPR_NUM_THREADS: "4",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  jobs.set(id, child);
  let errorText = "",
    finished = false;
  child.stderr.on("data", (chunk) => {
    errorText = (errorText + chunk.toString()).slice(-6000);
  });
  readline.createInterface({ input: child.stdout }).on("line", (line) => {
    try {
      const message = JSON.parse(line);
      if (message.stage === "complete") {
        finished = true;
        if (kind === "decode") {
          const record = imports.get(id);
          if (record) record.complete = true;
          for (const asset of message.result.assets)
            assets.set(asset.id, asset);
        }
      }
      if (message.stage === "failed") {
        finished = true;
        if (imports.has(id)) imports.get(id).discard = true;
      }
      send("job", { id, kind, ...message });
    } catch {
      /* External libraries may write non-JSON progress; never execute it. */
    }
  });
  child.on("error", (error) => {
    finished = true;
    send("job", { id, kind, stage: "failed", error: error.message });
    jobs.delete(id);
    if (imports.has(id)) void finishImport(id).catch(() => {});
  });
  child.on("close", (code) => {
    jobs.delete(id);
    const record = imports.get(id);
    if (record && (record.discard || !record.complete)) void finishImport(id).catch(() => {});
    if (!finished)
      send("job", {
        id,
        kind,
        stage: "failed",
        error:
          code === null
            ? "Job cancelled"
            : /MemoryError|memory allocation|paging file|1455|Unable to allocate output buffer/i.test(errorText)
              ? "Not enough available memory for this audio job. Close other memory-heavy applications and retry."
              : errorText || `Audio worker exited with code ${code}`,
      });
    scheduleCacheCleanup();
  });
  return id;
}

app.whenReady().then(async () => {
  await fs.mkdir(dataRoot, { recursive: true });
  scheduleCacheCleanup();
  protocol.handle("bpmtracker", (request) => {
    const url = new URL(request.url);
    const root = path.join(appRoot, "dist");
    const filename = path.resolve(root, "." + decodeURIComponent(url.pathname));
    if (url.hostname !== "app" || !filename.startsWith(root + path.sep))
      return new Response("Not found", { status: 404 });
    return net.fetch(pathToFileURL(filename).toString());
  });
  window = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1000,
    minHeight: 660,
    autoHideMenuBar: true,
    backgroundColor: "#202426",
    title: "BPMTracker",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#202426", symbolColor: "#cbd4da", height: 32 },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  });
  window.webContents.on("context-menu", (_event, params) => {
    if (!params.isEditable) return;
    const flags = params.editFlags;
    Menu.buildFromTemplate([
      { role: "undo", enabled: flags.canUndo }, { role: "redo", enabled: flags.canRedo },
      { type: "separator" },
      { role: "cut", enabled: flags.canCut }, { role: "copy", enabled: flags.canCopy },
      { role: "paste", enabled: flags.canPaste }, { role: "selectAll", enabled: flags.canSelectAll },
    ]).popup({ window });
  });
  window.webContents.on("did-start-loading", () => { rendererReady = false; });
  const command = (name) => () => send("command", name);
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "File",
        submenu: [
          {
            label: "New Project",
            accelerator: "CmdOrCtrl+N",
            click: command("new"),
          },
          {
            label: "Open Project…",
            accelerator: "CmdOrCtrl+O",
            click: command("open"),
          },
          { type: "separator" },
          {
            label: "Import Audio…",
            click: command("import"),
          },
          { label: "Save", accelerator: "CmdOrCtrl+S", click: command("save") },
          {
            label: "Save As…",
            accelerator: "CmdOrCtrl+Shift+S",
            click: command("save-as"),
          },
          { label: "Export Audio & Tempo Map…", click: command("export") },
          { type: "separator" },
          { role: "quit" },
        ],
      },
      {
        label: "Edit",
        submenu: [
          { label: "Undo", click: command("undo") },
          { label: "Redo", click: command("redo") },
          { type: "separator" },
          { label: "Copy", click: command("copy") },
          { label: "Paste", click: command("paste") },
          { label: "Duplicate", click: command("duplicate") },
          { label: "Split at Cursor", click: command("split") },
          { label: "Delete", click: command("delete") },
        ],
      },
      {
        label: "Project",
        submenu: [
          { label: "Add Audio Track…", click: command("add-track") },
          { label: "Duplicate Tracks", click: command("duplicate-tracks") },
          { label: "Remove Selected Tracks…", click: command("remove-tracks") },
          { label: "Select All Events on Tracks", click: command("track-events") },
          { label: "Move Tracks Up", click: command("tracks-up") },
          { label: "Move Tracks Down", click: command("tracks-down") },
          { type: "separator" },
          { label: "Project Setup…", click: command("project-setup") },
          { label: "Analyze Selected Audio…", click: command("analyze") },
          { label: "Linked Stem Editing", click: command("linked") },
        ],
      },
      {
        label: "Transport",
        submenu: [
          { label: "Start / Stop", click: command("play") },
          { label: "Go to Project Start", click: command("rewind") },
          { label: "Set Locators to Selection", click: command("locators") },
          { label: "Cycle", click: command("cycle") },
          { label: "Metronome", click: command("click") },
        ],
      },
      {
        label: "Help",
        submenu: [
          { label: "Keyboard & Mouse Reference", click: command("help") },
        ],
      },
    ]),
  );
  if (process.env.BPMTRACKER_DEV_URL)
    await window.loadURL(process.env.BPMTRACKER_DEV_URL);
  else await window.loadURL("bpmtracker://app/index.html");
});
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (quitting) return;
  event.preventDefault(); quitting = true;
  clearTimeout(cacheCleanupTimer);
  preserveProjectImports({ assets: [...registeredAssets.values()] });
  const pending = [...imports.values()];
  for (const record of pending) record.discard = true;
  for (const child of jobs.values()) child.kill();
  void (async () => {
    // A copied original must finish its outstanding file operation before its
    // private import directory can be removed on Windows.
    await Promise.allSettled(pending.map((record) => record.preparation));
    await Promise.allSettled([...restoringCaches.values()]);
    await Promise.allSettled([...jobs.values()].map((child) => new Promise((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) { resolve(); return; }
      child.once("close", resolve); child.once("error", resolve); child.kill();
    })));
    await Promise.allSettled([...imports.keys()].map((id) => finishImport(id)));
    await queueCacheCleanup(true);
  })().catch(error => console.warn("Audio cache cleanup:", error.message)).finally(() => app.quit());
});

ipcMain.on("bpmtracker:window", (_event, action) => {
  if (action === "minimize") window.minimize();
  else if (action === "maximize")
    window.isMaximized() ? window.unmaximize() : window.maximize();
  else if (action === "close") window.close();
});
ipcMain.handle("bpmtracker:choose-audio", async () => {
  const result = await dialog.showOpenDialog(window, {
    title: "Import Audio",
    properties: ["openFile", "multiSelections"],
    filters: [{ name: "Audio", extensions: ["wav", "mp3", "flac"] }],
  });
  return result.canceled ? [] : result.filePaths;
});
ipcMain.handle("bpmtracker:sample-library", async (_event, choose) => {
  const root = await sampleLibraryRoot(choose === true);
  return root ? sampleLibrary.list(root) : { root: null, tracks: [] };
});
ipcMain.handle("bpmtracker:sample-reference", async (_event, id) => {
  const root = await sampleLibraryRoot();
  if (!root) throw new Error("Select the formal sample catalog first");
  return sampleLibrary.reference(root, id);
});
ipcMain.handle("bpmtracker:choose-candidate-review", async () => {
  const root=await sampleLibraryRoot();
  if(!root)throw new Error("Select the sample catalog before opening a candidate review");
  const result=await dialog.showOpenDialog(window,{
    title:"Open a prepared DAW candidate review",defaultPath:path.join(root,"intakes"),
    properties:["openFile"],filters:[{name:"DAW review descriptor",extensions:["json"]}],
  });
  return result.canceled?null:sampleLibrary.candidateList(root,result.filePaths[0]);
});
ipcMain.handle("bpmtracker:candidate-reference", async (_event, filename, id) => {
  const root=await sampleLibraryRoot();
  if(!root)throw new Error("Select the sample catalog first");
  return sampleLibrary.candidateReference(root,filename,id);
});
ipcMain.handle("bpmtracker:save-sample-draft", async (_event, input) => {
  const project = validProject(input), root = await sampleLibraryRoot();
  if (!root || project.sampleReview?.reference?.libraryRoot !== root)
    throw new Error("Select the original library for this sample before saving its draft");
  return sampleLibrary.saveDraft(root, project);
});
ipcMain.handle("bpmtracker:decode", async (_event, paths, copy, requestId) => {
  if (!Array.isArray(paths) || paths.length === 0 || paths.length > 32)
    throw new Error("Choose between 1 and 32 audio files");
  if (typeof requestId !== "string" || !/^[0-9a-f-]{36}$/i.test(requestId) || imports.has(requestId) || jobs.has(requestId))
    throw new Error("Invalid or duplicate import request");
  if (paths.some((source) => typeof source !== "string" || ![".wav", ".mp3", ".flac"].includes(path.extname(source).toLowerCase())))
    throw new Error("Supported formats: WAV, MP3, FLAC");
  const files = paths.map((source) => ({ id: randomUUID(), source, path: source, name: path.basename(source) }));
  let prepared;
  const record = { assetIds: files.map((file) => file.id), preparing: true, complete: false, discard: false,
    preparation: new Promise((resolve) => { prepared = resolve; }),
    directories: files.flatMap((file) => copy ? [path.join(dataRoot, "media", file.id)] : []) };
  imports.set(requestId, record);
  try {
    const shared = new Map();
    for (const file of files) {
      if (record.discard) throw new Error("Import cancelled");
      if (copy) {
        const folder = path.join(dataRoot, "media", file.id);
        await fs.mkdir(folder, { recursive: true });
        file.path = path.join(folder, file.name);
        await fs.copyFile(file.source, file.path, require("node:fs").constants.COPYFILE_EXCL);
      }
      const info = await fs.stat(file.path);
      const identity = JSON.stringify([path.resolve(file.path), info.size, info.mtimeMs]);
      let cacheId = shared.get(identity);
      file.cacheReuseOnly = Boolean(cacheId);
      if (!cacheId) {
        cacheId = await audioCache.reusableCache(audioCacheRoot, [...registeredAssets.values()], file.path);
        file.cacheReuseOnly = Boolean(cacheId);
        if (!cacheId) {
          cacheId = file.id;
          record.directories.push(path.join(audioCacheRoot, cacheId));
        }
        shared.set(identity, cacheId);
      }
      file.cacheId = cacheId;
    }
    if (record.discard) throw new Error("Import cancelled");
    const id = await startJob("decode", { id: requestId, files, output: path.join(dataRoot, "audio-cache") });
    record.preparing = false;
    if (record.discard) await finishImport(id);
    return id;
  } catch (error) {
    record.preparing = false;
    await finishImport(requestId);
    throw error;
  } finally {
    prepared();
  }
});
ipcMain.handle("bpmtracker:finish-import", (_event, id, keep) => finishImport(id, keep === true));
ipcMain.handle("bpmtracker:register-assets", async (_event, items) => {
  for (const asset of items) audioCache.cacheId(asset);
  registeredAssets.clear();
  for (const asset of items) {
    registeredAssets.set(asset.id, asset);
    assets.set(asset.id, asset);
  }
  openingCacheIds.clear();
  await Promise.allSettled(items.map(ensureAssetCache));
  scheduleCacheCleanup();
});
ipcMain.handle("bpmtracker:peaks", async (_event, id) => {
  const bytes = await fs.readFile(requireAsset(id).peaksPath);
  return bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  );
});
ipcMain.handle("bpmtracker:chunk", async (_event, id, index) => {
  const asset = requireAsset(id);
  if (!Number.isInteger(index) || index < 0)
    throw new Error("Invalid audio chunk");
  const chunkFrames = (asset.playbackRate || asset.sampleRate) * 2;
  const first = index * chunkFrames;
  const count = Math.max(
    0,
    Math.min(chunkFrames, (asset.playbackFrames || asset.frames) - first),
  );
  const bytes = Buffer.alloc(count * asset.channels * 4);
  const handle = await fs.open(asset.playbackPath || asset.pcmPath, "r");
  try {
    await handle.read(bytes, 0, bytes.length, first * asset.channels * 4);
  } finally {
    await handle.close();
  }
  return bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  );
});
ipcMain.handle("bpmtracker:save", async (_event, input, previous, copy) => {
  const project = structuredClone(validProject(input));
  const result = previous
    ? { canceled: false, filePath: previous }
    : await dialog.showSaveDialog(window, {
        title: "Save Project",
        defaultPath: `${project.name}.bpmtracker`,
        filters: [{ name: "BPMTracker Project", extensions: ["bpmtracker"] }],
      });
  if (result.canceled || !result.filePath) return null;
  const target = (previous || result.filePath.endsWith(".bpmtracker"))
    ? result.filePath
    : `${result.filePath}.bpmtracker`;
  project.name = path.basename(target, path.extname(target));
  const directory = path.dirname(target);
  for (const asset of project.assets) {
    if (copy) {
      const media = path.join(
        directory,
        `${path.basename(target, path.extname(target))}.media`,
        asset.id,
      );
      await fs.mkdir(media, { recursive: true });
      const destination = path.join(media, asset.name);
      if (path.resolve(destination) !== path.resolve(asset.sourcePath))
        await fs.copyFile(asset.sourcePath, destination);
      asset.sourcePath = destination;
    }
    asset.sourcePath = path.relative(directory, asset.sourcePath);
  }
  await atomicJson(target, project);
  for (const asset of project.assets) {
    asset.sourcePath = path.resolve(directory, asset.sourcePath);
    assets.set(asset.id, asset);
  }
  return { path: target, project };
});
ipcMain.handle("bpmtracker:pending-projects", () => {
  rendererReady = true;
  return pendingProjects.splice(0);
});
ipcMain.handle("bpmtracker:open", async (_event, requested) => {
  if (requested !== undefined && (typeof requested !== "string" || !path.isAbsolute(requested)))
    throw new Error("Choose a valid .bpmtracker project file.");
  const selected = requested ? null : await dialog.showOpenDialog(window, {
    title: "Open Project",
    properties: ["openFile"],
    filters: [
      { name: "BPMTracker Project", extensions: ["bpmtracker"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (selected?.canceled) return null;
  const filename = requested ?? selected.filePaths[0];
  const project = validProject(JSON.parse(await fs.readFile(filename, "utf8")));
  const missing = [];
  for (const asset of project.assets) openingCacheIds.add(audioCache.cacheId(asset));
  for (const asset of project.assets) {
    asset.sourcePath = path.resolve(path.dirname(filename), asset.sourcePath);
    const cacheFolder = cacheFolderFor(asset);
    playbackCachePaths(asset, cacheFolder);
    try {
      await fs.access(asset.sourcePath);
    } catch {
      const relocate = await dialog.showOpenDialog(window, {
        title: `Locate missing audio: ${asset.name}`,
        properties: ["openFile"],
        filters: [{ name: "Audio", extensions: ["wav", "mp3", "flac"] }],
      });
      if (!relocate.canceled) asset.sourcePath = relocate.filePaths[0];
      else {
        missing.push(asset.name);
        continue;
      }
    }
    assets.set(asset.id, asset);
    await ensureAssetCache(asset);
  }
  return { path: filename, project, missing };
});
ipcMain.handle("bpmtracker:autosave", async (_event, project) =>
  atomicJson(path.join(dataRoot, "recovery.bpmtracker"), {
    project: validProject(project),
    savedAt: new Date().toISOString(),
  }),
);
ipcMain.handle("bpmtracker:recovery", async () => {
  try {
    const recovery = JSON.parse(
      await fs.readFile(path.join(dataRoot, "recovery.bpmtracker"), "utf8"),
    );
    const project = validProject(recovery.project);
    for (const asset of project.assets) {
      const cacheFolder = cacheFolderFor(asset);
      playbackCachePaths(asset, cacheFolder);
      try { await restoreCachedAsset(asset, cacheFolder); }
      catch { /* Registering an accepted recovery rebuilds missing buffers. */ }
    }
    return { ...recovery, project };
  } catch {
    return null;
  }
});
ipcMain.handle(
  "bpmtracker:analyze",
  async (_event, id, start, end, tap, clipId) => {
    const asset = requireAsset(id);
    if (
      ![start, end].every(Number.isFinite) ||
      start < 0 ||
      end > asset.duration + 0.001 ||
      end <= start
    )
      throw new Error("Invalid selected audio range");
    if (tap !== null && (!Number.isFinite(tap) || tap <= 0))
      throw new Error("Tap BPM must be positive");
    await fs.access(checkpoint).catch(() => {
      throw new Error("The official fixed-metronome checkpoint is missing");
    });
    if ([...jobs.values()].some((child) => child.bpmtrackerAnalysis))
      throw new Error("One analysis can run at a time");
    const jobId = randomUUID(),
      hintPath = path.join(dataRoot, "jobs", `${jobId}.hint.json`);
    await atomicJson(hintPath, {
      id: jobId,
      initial_quarter_bpm_tap: tap,
      scope: "initial_section",
      origin: "user_initial_unit_input",
    });
    const result = await startJob("analyze", {
      id: jobId,
      clipId,
      asset,
      sourceStart: start,
      sourceEnd: end,
      hintPath,
      analysisRoot,
      checkpoint,
      output: path.join(dataRoot, "analyses", jobId),
    });
    jobs.get(result).bpmtrackerAnalysis = true;
    return result;
  },
);
ipcMain.handle("bpmtracker:cancel", async (_event, id) => {
  if (imports.has(id)) { await finishImport(id); return; }
  const child = jobs.get(id);
  if (child) child.kill();
});
ipcMain.handle("bpmtracker:export", async (_event, project, options) => {
  validProject(project);
  const result = await dialog.showOpenDialog(window, {
    title: "Choose Export Folder",
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled) return null;
  const name = project.name.replace(/[<>:"/\\|?*]/g, "_") || "Project";
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return startJob("export", {
    project,
    options,
    output: path.join(result.filePaths[0], `${name} ${stamp}`),
  });
});
ipcMain.handle("bpmtracker:reveal", (_event, filename) =>
  shell.showItemInFolder(filename),
);
ipcMain.on("bpmtracker:closing-project", (event, project) => {
  try {
    validProject(project);
    preserveProjectImports(project);
    const filename = path.join(dataRoot, "recovery.bpmtracker");
    const temporary = filename + ".closing.tmp";
    fsSync.writeFileSync(
      temporary,
      JSON.stringify({ project, savedAt: new Date().toISOString() }),
    );
    fsSync.renameSync(temporary, filename);
    event.returnValue = true;
  } catch {
    event.returnValue = false;
  }
});
