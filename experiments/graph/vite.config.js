import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_BASE = process.env.VITE_API_BASE ?? ''

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __API_BASE__: JSON.stringify(API_BASE),
  },
  server: {
    proxy: {
      '/graph': { target: 'https://api.theoremsearch.com', changeOrigin: true },
      '/papers': { target: 'https://api.theoremsearch.com', changeOrigin: true },
      '/paper-links': { target: 'https://api.theoremsearch.com', changeOrigin: true },
    },
  },
})
