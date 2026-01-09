import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes to ../public, where Vercel serves it from the CDN and Flask serves index.html for deep links.
// In development Vite runs on 5180 and passes /api to Flask on 5181.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../public", emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    port: 5180,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:5181" },
  },
  preview: { host: "127.0.0.1", port: 5180, strictPort: true },
});
