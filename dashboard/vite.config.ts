import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev the dashboard runs on its own port and proxies API calls to the
// Gateway, so there is no CORS config to get wrong. In production the built
// assets are served by the Gateway itself and the same paths resolve directly.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/agents", "/skills", "/providers", "/costs", "/proposals", "/chat", "/pairing", "/health"].map((path) => [
        path,
        { target: process.env.GATEWAY_URL ?? "http://localhost:3000", changeOrigin: true },
      ])
    ),
  },
  build: { outDir: "dist" },
});
