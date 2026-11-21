import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Dev: `/api` is proxied to the backend (or to the mock server, see mock/server.mjs).
const target = process.env.API_TARGET ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { '/api': { target, changeOrigin: false } } },
  build: { outDir: '../src/fact_extractor/web/static', emptyOutDir: true, chunkSizeWarningLimit: 1000 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
