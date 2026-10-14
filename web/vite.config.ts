import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app talks to `canon serve`, which listens on 8790. CANON_API points elsewhere.
const api = process.env.CANON_API || 'http://localhost:8790'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: api, changeOrigin: true },
      '/auth': { target: api, changeOrigin: true },
    },
  },
})
