import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import path from "node:path"

// Dev: Vite serves the React app and proxies /api/* to the FastAPI backend
// so the session cookie stays same-origin. Prod: `vite build` → FastAPI can
// serve the dist/ bundle.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: {
      // Keep the browser's Host (localhost:5173) on the forwarded request so
      // it matches the Origin header — the backend's CSRF same_origin() check
      // compares the two and would 403 every mutation (incl. login) if the
      // proxy rewrote Host to the backend (changeOrigin:true).
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { outDir: "dist" },
})
