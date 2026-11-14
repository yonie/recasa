import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Backend the dev server proxies /api to. Point it at another instance with
// e.g. `RECASA_API=http://192.168.1.129:7001 npm run dev`.
const apiTarget = process.env.RECASA_API || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    // Sourcemaps are cheap and only fetched when devtools are open.
    sourcemap: true,
    rollupOptions: {
      output: {
        // Libraries change far less often than app code, so a separate chunk
        // stays cached in the browser across upgrades.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query", "zustand"],
        },
      },
    },
  },
});
