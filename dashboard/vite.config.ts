import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The dashboard is a pure API consumer (ARCHITECTURE §2.3); in dev,
    // proxy the control plane so the app can use relative /v1 URLs.
    proxy: {
      "/v1": "http://localhost:8420",
    },
  },
});
