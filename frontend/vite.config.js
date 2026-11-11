import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
    base: "./",
    oxc: { jsx: { runtime: "automatic" } },
    build: {
        outDir: fileURLToPath(new URL("../backend/apps/web/static/web/react", import.meta.url)),
        emptyOutDir: true,
        rolldownOptions: {
            input: fileURLToPath(new URL("src/main.jsx", import.meta.url)),
            output: {
                entryFileNames: "app.js",
                chunkFileNames: "chunks/[name]-[hash].js",
            },
        },
    },
});
