import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// The API origin the browser is allowed to talk to. Read from the same
// variable the app itself uses, so a deployment that repoints the API does not
// silently ship a CSP that blocks every request it makes.
const API_ORIGIN = process.env.VITE_API_BASE_URL || 'http://localhost:8000'

/**
 * Security headers for the pages Vite serves.
 *
 * The API sets its own — see `backend/app/core/middleware.py`. These are the
 * SPA's, and they have to live here because Vite is what sends them; a header
 * set by FastAPI never reaches a document served on :5173.
 *
 * `script-src` carries `'unsafe-inline'` and that is a real weakening, stated
 * rather than hidden: Vite's dev server injects an inline module preamble and
 * the React Refresh runtime, so a nonce-based policy would leave the page
 * blank and the HMR socket dead. A production deployment serving the built
 * output from a static host has no inline script and should tighten this to
 * hashes or nonces. What is enforced here regardless — no framing, no plugins,
 * no arbitrary `connect-src`, no `base-uri` rewrite — is the part that holds
 * either way.
 *
 * `ws:` in `connect-src` is HMR. Removing it does not break the app, it breaks
 * every reload during development, which is how a CSP gets deleted.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  // Self-hosted @fontsource, so no CDN is needed — see CLAUDE.md > Phase 3.
  "font-src 'self'",
  "img-src 'self' data: blob:",
  // The ambient background clips.
  "media-src 'self'",
  `connect-src 'self' ${API_ORIGIN} ws: wss:`,
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ')

const SECURITY_HEADERS = {
  'Content-Security-Policy': CSP,
  'X-Content-Type-Options': 'nosniff',
  // A report URL carries a report id and a share URL carries a capability
  // token; neither belongs in a Referer sent to a third party.
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy':
    'accelerometer=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()',
}

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
    headers: SECURITY_HEADERS,
  },
  // `npm run preview` serves the built output. It gets the same headers, so
  // "works in dev, unstyled in preview" cannot be a CSP surprise found late.
  preview: {
    port: 4173,
    headers: SECURITY_HEADERS,
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
