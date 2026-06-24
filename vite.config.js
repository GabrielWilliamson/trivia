import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  base: "/static/",
  resolve: {
    alias: {
      "@": resolve("./static/"),
    },
  },
  build: {
    copyPublicDir: true,
    manifest: "manifest.json",
    outDir: resolve("./assets/"),
    rollupOptions: {
      input: {
        home: resolve("./static/js/main.js"),
      },
    },
  },
});
