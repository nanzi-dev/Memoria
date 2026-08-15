import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src'),
    },
  },
  assetsInclude: ['**/*.glb'],
  build: {
    // 保持 Vite 默认的 1600 KB 告警阈值。不要为了消除告警调高阈值：
    // Lanyard 等依赖生成的大 chunk 是后续需要按需拆分/懒加载的债务。
    chunkSizeWarningLimit: 1600,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
});
