import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Fully client-side app: Vite only compiles to static assets (no backend). The
// runtime-data archive lives in public/ and is served as-is at the site root;
// Pyodide is CDN-injected at runtime (see src/lib/pyodide-boot.ts).
export default defineConfig({
  plugins: [svelte()],
  // Relative base so the built dist/ works when served from any sub-path.
  base: "./",
  server: {
    // Headless gate + dev both bind to an ephemeral port chosen at launch.
    port: 5179,
    strictPort: false,
  },
  build: {
    target: "esnext",
    chunkSizeWarningLimit: 2000,
  },
});
