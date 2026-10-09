import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { output: { manualChunks: { charts: ['recharts'], query: ['@tanstack/react-query'] } } } },
  server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], include: ['src/**/*.test.tsx'] },
});
