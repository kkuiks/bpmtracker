const fs = require("node:fs/promises");
const path = require("node:path");

const cacheFiles = ["audio.f32", "playback.f32", "peaks.f32", "asset.json", "source.json"];

function cacheId(asset) {
  const id = asset.cacheId ?? asset.id;
  if (typeof id !== "string" || !/^[a-zA-Z0-9_-][a-zA-Z0-9._-]{0,127}$/.test(id))
    throw new Error("Invalid audio cache identity");
  return id;
}

function cacheFolder(root, asset) {
  return path.join(root, cacheId(asset));
}

function sourceMatches(cached, source, info) {
  return path.resolve(cached.sourcePath) === path.resolve(source) &&
    cached.originalSize === info.size && Number.isFinite(cached.originalModified) &&
    Math.abs(cached.originalModified - info.mtimeMs) <= 1;
}

async function reusableCache(root, registered, source) {
  const info = await fs.stat(source);
  for (const asset of registered) {
    if (path.resolve(asset.sourcePath) !== path.resolve(source)) continue;
    try {
      const id = cacheId(asset), folder = path.join(root, id);
      const cached = JSON.parse(await fs.readFile(path.join(folder, "asset.json"), "utf8"));
      if (!sourceMatches(cached, source, info)) continue;
      const pcm = await fs.stat(path.join(folder, "audio.f32"));
      const playback = await fs.stat(path.join(folder, cached.sampleRate === 48000 ? "audio.f32" : "playback.f32"));
      const peaks = await fs.stat(path.join(folder, "peaks.f32"));
      if (cached.playbackRate !== 48000 ||
          pcm.size !== cached.frames * cached.channels * 4 ||
          playback.size !== cached.playbackFrames * cached.channels * 4 ||
          peaks.size !== cached.peakBins * 2 * 4) continue;
      return id;
    } catch { /* Missing or incomplete buffers must be decoded again. */ }
  }
  return null;
}

async function pruneAudioCache(root, keep, idle = () => true) {
  let entries;
  try { entries = await fs.readdir(root, { withFileTypes: true }); }
  catch (error) { if (error.code === "ENOENT") return; throw error; }
  for (const entry of entries) {
    if (!idle()) return;
    if (!entry.isDirectory() || entry.isSymbolicLink() || keep(entry.name)) continue;
    const folder = path.join(root, entry.name);
    try {
      let metadata;
      try { metadata = await fs.readFile(path.join(folder, "asset.json"), "utf8"); }
      catch (error) {
        if (error.code !== "ENOENT") throw error;
        metadata = await fs.readFile(path.join(folder, "source.json"), "utf8");
      }
      const cached = JSON.parse(metadata);
      if (cacheId(cached) !== entry.name) continue;
      const files = await fs.readdir(folder, { withFileTypes: true });
      if (files.some(file => !file.isFile() || file.isSymbolicLink() || !cacheFiles.includes(file.name))) continue;
      // A missing or changed original can make the old buffer the only surviving
      // version. Leave it for an explicit owner decision, never automatic cleanup.
      const info = await fs.stat(cached.sourcePath);
      if (!sourceMatches(cached, cached.sourcePath, info)) continue;
      for (const name of cacheFiles) {
        if (!idle() || keep(entry.name)) break;
        await fs.rm(path.join(folder, name), { force: true });
      }
      if (idle() && !keep(entry.name)) await fs.rmdir(folder);
    } catch (error) {
      // Windows may still have a final playback read open. Retry at the next
      // project switch/exit; cleanup must not fail the project operation.
      if (!["ENOENT", "EBUSY", "EPERM", "EACCES", "ENOTEMPTY"].includes(error.code))
        console.warn("Audio cache cleanup skipped:", entry.name, error.message);
    }
  }
}

module.exports = { cacheId, cacheFolder, reusableCache, pruneAudioCache };
