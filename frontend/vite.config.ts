import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Ports are env-driven so the two servers can move together without edits.
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT ?? 5173);
const BACKEND_PORT = Number(process.env.BACKEND_PORT ?? 8420);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: FRONTEND_PORT,
    strictPort: true,
    host: "127.0.0.1",
    proxy: {
      "/api": { target: `http://127.0.0.1:${BACKEND_PORT}`, changeOrigin: true },
    },
  },
});
