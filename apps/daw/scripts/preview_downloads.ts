import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

/** Download only the three preview installation artifacts over the UI tunnel. */
export default function previewDownloads(): Plugin {
  const distribution = fileURLToPath(new URL("../../../dist/", import.meta.url));
  const prefix = "/__bpmtracker_preview__/";
  const artifacts = new Map([
    ["Install-BPMTracker-Preview.ps1", fileURLToPath(new URL("./install_remote_preview.ps1", import.meta.url))],
    ["BPMTracker-win-x64.zip", resolve(distribution, "BPMTracker-win-x64.zip")],
    ["BPMTracker-remote-preview-app.zip", resolve(distribution, "BPMTracker-remote-preview-app.zip")],
  ]);
  return {
    name: "bpmtracker-preview-downloads",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const pathname = (request.url ?? "").split("?", 1)[0];
        if (!pathname.startsWith(prefix)) return next();
        const name = pathname.slice(prefix.length), filename = artifacts.get(name);
        if (!filename) { response.statusCode = 404; response.end("Unknown preview artifact"); return; }
        if (request.method !== "GET" && request.method !== "HEAD") {
          response.statusCode = 405; response.setHeader("Allow", "GET, HEAD"); response.end(); return;
        }
        let size: number, modified: Date;
        try {
          const info = await stat(filename);
          if (!info.isFile()) throw new Error("Not a file");
          size = info.size; modified = info.mtime;
        } catch { response.statusCode = 404; response.end("Preview artifact has not been prepared"); return; }
        let start = 0, end = size - 1;
        const range = request.method === "GET" ? request.headers.range : undefined;
        if (range) {
          const match = /^bytes=(\d+)-(\d*)$/.exec(range);
          start = match ? Number(match[1]) : -1;
          end = match?.[2] ? Math.min(size - 1, Number(match[2])) : size - 1;
          if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || start > end) {
            response.statusCode = 416;
            response.setHeader("Content-Range", `bytes */${size}`); response.end(); return;
          }
          response.statusCode = 206;
          response.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
        }
        response.setHeader("Content-Length", end - start + 1);
        response.setHeader("Accept-Ranges", "bytes");
        response.setHeader("Last-Modified", modified.toUTCString());
        response.setHeader("Cache-Control", "no-store");
        response.setHeader("Content-Type", name.endsWith(".zip") ? "application/zip" : "text/plain; charset=utf-8");
        response.setHeader("Content-Disposition", `attachment; filename="${name}"`);
        response.setHeader("X-Content-Type-Options", "nosniff");
        if (request.method === "HEAD") { response.end(); return; }
        const stream = createReadStream(filename, { start, end });
        response.on("close", () => stream.destroy());
        stream.on("error", () => response.destroy());
        stream.pipe(response);
      });
    },
  };
}
