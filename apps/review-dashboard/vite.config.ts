import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to the local Python server (services/local_api/server.py, port 8770).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8770", "/img": "http://127.0.0.1:8770" },
  },
});
