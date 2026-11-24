import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to FastAPI, so the browser never needs CORS in development.
// API_TARGET (an environment variable) lets a second dev server point at another API, for example a test instance on another port.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "API_");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/api": env.API_TARGET || "http://127.0.0.1:8000" },
    },
  };
});
