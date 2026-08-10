import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Absolute imports via `@/` — see CLAUDE.md > Conventions.
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Required so the dev server is reachable from outside the container.
    host: true,
  },
  test: {
    // In this config rather than a separate vitest.config.js so the tests
    // resolve `@/` through the same alias the app does. Two configs would be
    // two chances for the test build and the real build to disagree.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
})
