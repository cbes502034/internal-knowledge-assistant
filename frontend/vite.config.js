import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  // 後端不在 8000 時，在 frontend/.env.local 設定 API_PROXY_TARGET=http://127.0.0.1:8001
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      port: 5173,
      // 開發時 /api 轉給本機的 FastAPI，瀏覽器看到的是同一個來源，cookie 才會正常運作
      proxy: { '/api': env.API_PROXY_TARGET || 'http://127.0.0.1:8000' },
    },
  };
});
