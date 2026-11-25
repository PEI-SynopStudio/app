import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Prefix of the backend API as the browser sees it; the backend's own routes have no prefix.
const API_PREFIX = '/api'
// Outside Docker the backend runs on the host; docker-compose.yml points this to the backend service.
const DEFAULT_API_PROXY_TARGET = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
    server: {
    // Docker on Windows doesn't pass file changes from the host to the container,
    // so the dev server polls instead (enabled in docker-compose.yml).
    watch: { usePolling: process.env.CHOKIDAR_USEPOLLING === 'true' },
    // The browser calls the API on its own origin, so the session cookie works without CORS;
    // the prefix is removed before the request reaches the backend. ws: the progress WebSocket.
    proxy: {
      [`${API_PREFIX}/`]: {
        target: process.env.API_PROXY_TARGET ?? DEFAULT_API_PROXY_TARGET,
        ws: true,
        rewrite: (path) => path.slice(API_PREFIX.length),
      },
    },
  },
})