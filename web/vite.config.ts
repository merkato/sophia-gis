import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// W trybie dev (npm run dev) żądania /api i /ows idą do lokalnego stosu Docker (proxy Caddy).
const target = process.env.SOPHIA_URL ?? "https://localhost";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target, changeOrigin: true, secure: false },
      "/ows": { target, changeOrigin: true, secure: false },
    },
  },
});
