import { defineConfig, searchForWorkspaceRoot } from "vite";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import previewDownloads from "./scripts/preview_downloads.ts";

export default defineConfig({
  define: {
    BPMTRACKER_DESIGN_ASSETS: JSON.stringify(
      `/@fs${fileURLToPath(new URL("../../.daw-state/u2-redesign-20261011/assets/", import.meta.url))}`,
    ),
  },
  plugins: [
    react(),
    previewDownloads(),
    {
      name: "local-development-csp",
      apply: "serve",
      transformIndexHtml(html) {
        // React Refresh injects a local inline preamble. Production retains the
        // stricter policy in index.html; only the local Vite response changes.
        return html.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
          .replace("connect-src 'self' bpmtracker:", "connect-src 'self' bpmtracker: ws://127.0.0.1:8998");
      },
    },
  ],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, target: "chrome140" },
  server: {
    host: "127.0.0.1", port: 8998, strictPort: true,
    fs: { allow: [searchForWorkspaceRoot(process.cwd()),
      fileURLToPath(new URL("../../.daw-state/u2-redesign-20261011/", import.meta.url))] },
  },
});
