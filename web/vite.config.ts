import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
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
});
