import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      // Same-origin /api keeps the app working behind a tunnel or reverse
      // proxy, where the browser cannot reach 127.0.0.1 on the server.
      // Point LEARNFLOW_API_PORT at another port if the backend moves.
      "/api": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
        ws: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./tests/setup.ts",
    exclude: ["tests/e2e/**", "**/node_modules/**", "**/dist/**"],
  },
});
