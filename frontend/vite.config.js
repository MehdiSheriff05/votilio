import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: "external" } })],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../app/static/dist",
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: false,
    lib: {
      entry: "src/main.js",
      name: "VotilioCsvBundle",
      formats: ["iife"],
      fileName: () => "csv-editor.js",
      cssFileName: "csv-editor",
    },
  },
  test: { environment: "node" },
});
