import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "local-development-csp",
      apply: "serve",
      transformIndexHtml(html) {
        // React Refresh injects a local inline preamble. Production retains the
        // stricter policy in index.html; only the local Vite response changes.
        return html.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
          .replace("connect-src 'self' joljak:", "connect-src 'self' joljak: ws://127.0.0.1:8998");
      },
    },
  ],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, target: "chrome140" },
  server: { host: "127.0.0.1", port: 8998, strictPort: true },
});
