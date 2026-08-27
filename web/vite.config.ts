import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Normalise a Pages base path into the form Vite wants: leading and trailing
 * slash, or a bare "/".
 *
 * `actions/configure-pages` reports `/soulfinder` for a project site and `/`
 * for a user site, and a custom domain changes it again — so the value is
 * normalised here rather than assumed in the workflow. Getting this wrong is
 * the classic Pages failure: the page loads, every asset 404s, and the app
 * renders blank with no obvious cause.
 */
function normalizeBase(raw: string | undefined): string {
  const trimmed = (raw ?? "").replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}/` : "/";
}

export default defineConfig(({ command }) => ({
  // Only the production build is served from a subpath; the dev server always
  // runs at the root so `npm run dev` needs no special URL.
  base: command === "build" ? normalizeBase(process.env.BASE_PATH) : "/",
  plugins: [react()],
  server: { port: 5173 },
  build: {
    // deck.gl is large; splitting it keeps the app chunk reviewable in the
    // bundle report instead of hiding it inside a single 2MB blob.
    rollupOptions: {
      output: {
        manualChunks: {
          deck: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/react", "@deck.gl/aggregation-layers"],
        },
      },
    },
  },
}));
