import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Docker on Windows doesn't pass file changes from the host to the container,
    // so the dev server polls instead (enabled in docker-compose.yml).
    watch: { usePolling: process.env.CHOKIDAR_USEPOLLING === 'true' },
  },
})