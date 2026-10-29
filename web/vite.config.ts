import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      // OSMD plus motion put the main chunk just past workbox's 2 MiB precache default.
      workbox: { maximumFileSizeToCacheInBytes: 3 * 1024 * 1024 },
      manifest: {
        id: '/',
        name: 'Folio',
        short_name: 'Folio',
        description: 'One score for the whole ensemble',
        start_url: '/',
        scope: '/',
        // The launch frame is the app's own light ground (--ground); the dark theme is applied by the first paint.
        theme_color: '#e6e8eb',
        background_color: '#e6e8eb',
        display: 'standalone',
        orientation: 'any',
        // PNGs in public/: the forte f, ink on paper (icon.svg is the master). The maskable one keeps the f inside the safe zone.
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  server: {
    // Expose on the LAN so iPads on the same wifi can open the dev server.
    host: true,
    port: 5173,
    // Let Cloudflare tunnels (random *.trycloudflare.com hosts or your own hostname) reach the dev server.
    allowedHosts: ['.trycloudflare.com'],
  },
})
