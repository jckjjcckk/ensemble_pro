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
      // OSMD plus motion put the main chunk just past workbox's 2 MiB precache default.
      workbox: { maximumFileSizeToCacheInBytes: 3 * 1024 * 1024 },
      manifest: {
        name: 'Folio',
        short_name: 'Folio',
        description: 'One score for the whole ensemble',
        theme_color: '#111111',
        background_color: '#111111',
        display: 'standalone',
        orientation: 'any',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
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
