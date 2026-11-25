import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// A clickable mock of the bid intake. No backend and no model: every call is simulated in the page.
export default defineConfig({
  root: __dirname,
  plugins: [react()],
  server: { port: 5199, strictPort: true },
});
