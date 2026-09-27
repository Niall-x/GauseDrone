import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development the API runs separately (uvicorn on :8000); in production
// FastAPI serves the built dist/ itself, so no proxy is involved.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { chunkSizeWarningLimit: 2500 },
});
