import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const BACKEND_ORIGIN = 'http://127.0.0.1:17888';

// Dev and `vite preview` both proxy /api to the local FastAPI server.
// Production serves the built SPA and /api from the same origin, so the app only ever
// requests relative /api/... URLs.
const proxy = {
  '/api': { target: BACKEND_ORIGIN, changeOrigin: false },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy,
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
