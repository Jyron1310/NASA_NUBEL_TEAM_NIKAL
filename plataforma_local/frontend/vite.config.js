import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Base de la interfaz: rama `dante` (Firewatch Perú). En desarrollo (`npm run dev`), las llamadas a
// /api y /health van al backend FastAPI local (firecal serve, puerto 8000).
export default defineConfig({
  plugins: [react()],
  base: './',
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
