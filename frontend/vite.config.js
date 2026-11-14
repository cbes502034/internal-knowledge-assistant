import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 開發時 /api 轉給本機的 FastAPI，瀏覽器看到的是同一個來源，cookie 才會正常運作
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
});
